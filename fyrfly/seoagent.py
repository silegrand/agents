"""
Fyrfly SEO Analysis Agent v2
==============================
Reads the existing fyrfly_seo_audit.csv (crawl data already captured)
and runs Claude analysis on each page to produce recommendations.

WHY v2 EXISTS
-------------
v1 failed because Claude returned explanatory text around the JSON,
breaking the parser. v2 uses Claude's tool_use feature which FORCES
structured output — Claude cannot return anything except valid JSON
when tool_use is active. This is the correct approach for agents.

HOW TO RUN
----------
1. Upload fyrfly_seo_audit.csv to your Colab session
   (drag it into the file browser panel on the left)
2. Run:  !pip install anthropic
3. Paste and run this script
4. Two output files are produced:
      fyrfly_seo_audit_v2.csv
      fyrfly_seo_report_v2.txt
"""

import anthropic
import csv
import json
import time
import re
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────────

INPUT_CSV   = "fyrfly_seo_audit.csv"      # the file you already have
OUTPUT_CSV  = "fyrfly_seo_audit_v2.csv"
REPORT_FILE = "fyrfly_seo_report_v2.txt"
MODEL       = "claude-sonnet-4-6"
DELAY       = 1.0   # seconds between API calls

SITE_CONTEXT = """
Fyrfly Systems — physical security company, Faversham, Kent.
Services: CCTV, access control, intruder alarms, fire systems, wireless networks, 24/7 monitoring.
Primary sectors: schools, public sector, local authorities, NHS estates.
Compliance focus: Martyn's Law, KCSiE 2025, UK GDPR, DfE protective security.
Geography: South East England — Kent, London, Surrey, Essex, Sussex.
Audience: headteachers, school business managers, governors, LA estates managers.
Accreditations: NSI NACOSS Gold, SSAIB, BAFE, Constructionline Gold, Crown Commercial Service.
"""

# Page type lookup — affects scoring thresholds and schema recommendations
PAGE_TYPES = {
    "/":                             "homepage",
    "/index.html":                   "homepage",
    "/blog.html":                    "blog_index",
    "/education.html":               "sector",
    "/public-sector.html":           "sector",
    "/cctv.html":                    "service",
    "/access-control.html":          "service",
    "/wireless-networks.html":       "service",
    "/intruder-alarms.html":         "service",
    "/fire-systems.html":            "service",
    "/monitoring.html":              "service",
    "/support-maintenance.html":     "service",
    "/ai-analytics.html":            "service",
    "/cctv-tower.html":              "product",
    "/security-policy-review.html":  "service",
    "/invisible-shield.html":        "guide",
    "/connected-council.html":       "guide",
    "/legal.html":                   "legal",
}

def get_page_type(url: str) -> str:
    path = "/" + url.replace("https://www.fyrflysystems.com", "").lstrip("/")
    # local area pages
    if "school-security-" in path or "public-sector-security-" in path:
        return "local_area"
    # article pages
    if "article-" in path:
        return "article"
    # tool pages
    if any(t in path for t in ["tool", "planner", "estimator", "analyser"]):
        return "tool"
    return PAGE_TYPES.get(path, "content")


# ── TOOL DEFINITION ────────────────────────────────────────────────────────────
# Using Claude's tool_use feature guarantees structured JSON output.
# Claude MUST call this tool — it cannot respond with plain text.

SEO_TOOL = {
    "name": "submit_seo_audit",
    "description": "Submit the SEO audit results for a page",
    "input_schema": {
        "type": "object",
        "properties": {
            "seo_score": {
                "type": "integer",
                "description": "Overall SEO health score 0-100"
            },
            "target_keyword": {
                "type": "string",
                "description": "The single best keyword this page should target"
            },
            "recommended_title": {
                "type": "string",
                "description": "Optimised title tag, 50-60 characters, contains target keyword"
            },
            "recommended_meta": {
                "type": "string",
                "description": "Optimised meta description, 150-160 characters, contains keyword, ends with call to action"
            },
            "h1_needs_change": {
                "type": "boolean",
                "description": "Whether the H1 needs to be changed"
            },
            "recommended_h1": {
                "type": "string",
                "description": "Improved H1 if h1_needs_change is true, else leave empty"
            },
            "recommended_schema": {
                "type": "string",
                "description": "Best schema.org type for this page e.g. LocalBusiness, Article, FAQPage, Service"
            },
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of specific SEO issues found on this page"
            },
            "priority_fixes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "priority": {"type": "integer"},
                        "fix": {"type": "string"},
                        "impact": {"type": "string"}
                    }
                },
                "description": "Ordered list of fixes, most impactful first"
            },
            "content_gaps": {
                "type": "string",
                "description": "Key topics or keywords missing from the page content"
            },
            "internal_linking_note": {
                "type": "string",
                "description": "Specific internal linking improvements needed"
            },
            "quick_win": {
                "type": "boolean",
                "description": "True if the main issues can be fixed in under 10 minutes"
            }
        },
        "required": [
            "seo_score", "target_keyword",
            "recommended_title", "recommended_meta",
            "h1_needs_change", "recommended_schema",
            "issues", "priority_fixes", "quick_win"
        ]
    }
}


# ── ANALYSIS ───────────────────────────────────────────────────────────────────

def analyse_page(client, row: dict) -> dict:
    """Analyse one page using tool_use for guaranteed structured output."""

    url       = row.get("url", "")
    page_type = get_page_type(url)

    prompt = f"""You are an expert SEO specialist. Audit this page and call the submit_seo_audit tool with your findings.

SITE CONTEXT:
{SITE_CONTEXT}

PAGE DATA:
URL: {url}
Page type: {page_type}
Current title: {row.get('current_title', 'MISSING')} ({len(row.get('current_title',''))} chars)
Current meta description: {row.get('current_meta', 'MISSING')} ({len(row.get('current_meta',''))} chars)
Current H1: {row.get('current_h1', 'MISSING')}
Word count: {row.get('word_count', 0)}
Images missing alt text: {row.get('img_issues', 0)}
HTTP status: {row.get('http_status', 0)}

SEO SCORING GUIDE:
- Title present and 50-60 chars: +15 pts
- Meta present and 150-160 chars: +15 pts
- Single H1 that matches page intent: +10 pts
- Word count appropriate for page type (articles 1500+, service pages 500+): +10 pts
- Schema markup present: +10 pts
- No images missing alt text: +5 pts
- Canonical tag: +5 pts
- Strong target keyword in title and H1: +10 pts
- Internal links to related pages: +10 pts
- Content covers topic comprehensively: +10 pts

For the recommended_title: make it 50-60 chars, include the target keyword, include "Fyrfly Systems" or "| Fyrfly" at the end.
For the recommended_meta: make it exactly 150-160 chars. Include the keyword near the start. End with a specific call to action like "Free site survey available." or "Speak to our team today."
For articles: target keyword should be the article's specific topic e.g. "school security specification UK"
For local area pages: target keyword should be location-specific e.g. "school security Kent"
For tool pages: target keyword should reflect the tool purpose e.g. "Martyn's Law compliance checklist schools"

Call the submit_seo_audit tool now with your complete analysis."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            tools=[SEO_TOOL],
            tool_choice={"type": "any"},   # forces tool use
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract tool input from response
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_seo_audit":
                result = block.input
                result["url"] = url
                return result

        # Fallback if somehow no tool call (shouldn't happen with tool_choice=any)
        return {"url": url, "seo_score": 0, "issues": ["No tool call returned"], "error": True}

    except Exception as e:
        print(f"    ! Error for {url}: {e}")
        return {"url": url, "seo_score": 0, "issues": [f"API error: {str(e)}"], "error": True}


# ── CROSS-SITE ANALYSIS ───────────────────────────────────────────────────────

CROSS_SITE_TOOL = {
    "name": "submit_cross_site_analysis",
    "description": "Submit cross-site SEO analysis findings",
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword_cannibalism": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "competing_pages": {"type": "array", "items": {"type": "string"}},
                        "recommendation": {"type": "string"}
                    }
                }
            },
            "likely_orphan_pages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs likely to have no internal links pointing to them"
            },
            "top_linking_gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_page": {"type": "string"},
                        "should_link_to": {"type": "string"},
                        "reason": {"type": "string"}
                    }
                }
            },
            "content_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Important topics missing from the site"
            },
            "top_priorities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Top 5-8 cross-site actions ranked by impact"
            }
        },
        "required": ["keyword_cannibalism", "likely_orphan_pages",
                     "top_linking_gaps", "content_gaps", "top_priorities"]
    }
}


def cross_site_analysis(client, all_audits: list) -> dict:
    """Run cross-site analysis using tool_use."""
    print("\nRunning cross-site analysis...")

    lines = []
    for a in all_audits[:65]:
        lines.append(
            f"{a.get('url','').replace('https://www.fyrflysystems.com','')} | "
            f"score={a.get('seo_score',0)} | "
            f"keyword={a.get('target_keyword','')[:35]} | "
            f"title={a.get('recommended_title', a.get('current_title',''))[:50]}"
        )

    prompt = f"""You are an expert SEO strategist. Analyse all pages on www.fyrflysystems.com 
and identify cross-site issues. Call the submit_cross_site_analysis tool.

SITE CONTEXT: {SITE_CONTEXT}

ALL PAGES:
{chr(10).join(lines)}

Look for:
- Keyword cannibalism: multiple pages targeting the same term
- Orphan pages: tool pages, local area pages and article pages rarely linked to internally
- Linking gaps: service pages not linked from relevant articles, articles not linking to tools
- Content gaps: topics the site should cover but doesn't (e.g. MAT case studies, pricing guides)
- Quick structural wins

Call submit_cross_site_analysis now."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            tools=[CROSS_SITE_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}]
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.input
    except Exception as e:
        print(f"  Cross-site error: {e}")
    return {}


# ── SAVE AND REPORT ───────────────────────────────────────────────────────────

def save_csv(audits: list, original_rows: list, path: str):
    orig_by_url = {r["url"]: r for r in original_rows}

    output_rows = []
    for audit in audits:
        url  = audit.get("url", "")
        orig = orig_by_url.get(url, {})
        issues = "; ".join(audit.get("issues", []))
        fixes  = "; ".join(
            f"[{f.get('priority','?')}] {f.get('fix','')}"
            for f in audit.get("priority_fixes", [])
        )
        output_rows.append({
            "url":               url,
            "page_type":         get_page_type(url),
            "seo_score":         audit.get("seo_score", 0),
            "target_keyword":    audit.get("target_keyword", ""),
            "current_title":     orig.get("current_title", ""),
            "recommended_title": audit.get("recommended_title", ""),
            "title_len_current": len(orig.get("current_title", "")),
            "title_len_new":     len(audit.get("recommended_title", "")),
            "current_meta":      orig.get("current_meta", ""),
            "recommended_meta":  audit.get("recommended_meta", ""),
            "meta_len_current":  len(orig.get("current_meta", "")),
            "meta_len_new":      len(audit.get("recommended_meta", "")),
            "current_h1":        orig.get("current_h1", ""),
            "recommended_h1":    audit.get("recommended_h1", "") if audit.get("h1_needs_change") else "OK — no change needed",
            "recommended_schema": audit.get("recommended_schema", ""),
            "word_count":        orig.get("word_count", 0),
            "img_issues":        orig.get("img_issues", 0),
            "issues":            issues,
            "priority_fixes":    fixes,
            "content_gaps":      audit.get("content_gaps", ""),
            "internal_linking":  audit.get("internal_linking_note", ""),
            "quick_win":         audit.get("quick_win", False),
            "h1_needs_change":   audit.get("h1_needs_change", False),
            "http_status":       orig.get("http_status", 0),
        })

    # Sort: lowest score first so worst pages are at the top
    output_rows.sort(key=lambda x: (x.get("seo_score", 0)))

    cols = [
        "url","page_type","seo_score","target_keyword",
        "current_title","recommended_title","title_len_current","title_len_new",
        "current_meta","recommended_meta","meta_len_current","meta_len_new",
        "current_h1","recommended_h1","recommended_schema",
        "word_count","img_issues",
        "issues","priority_fixes","content_gaps","internal_linking",
        "quick_win","h1_needs_change","http_status"
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(output_rows)

    print(f"Saved: {path}  ({len(output_rows)} pages)")
    return output_rows


def write_report(output_rows: list, cross_site: dict, path: str):
    lines = []
    S = "=" * 70
    D = "-" * 70

    lines += [S, "FYRFLY SYSTEMS — SEO AUDIT REPORT v2",
              f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}",
              f"Pages audited: {len(output_rows)}", S]

    scores = [r["seo_score"] for r in output_rows if r.get("seo_score", 0) > 0]
    if scores:
        avg = sum(scores) / len(scores)
        lines += [
            "", "SITE HEALTH OVERVIEW", D,
            f"  Average SEO score:    {avg:.1f} / 100",
            f"  Highest score:        {max(scores)} / 100",
            f"  Lowest score:         {min(scores)} / 100",
            f"  Pages scoring 70+:    {sum(1 for s in scores if s >= 70)}",
            f"  Pages scoring 50-69:  {sum(1 for s in scores if 50 <= s < 70)}",
            f"  Pages scoring below 50: {sum(1 for s in scores if s < 50)}",
        ]

    # Quick wins
    qw = [r for r in output_rows if r.get("quick_win")]
    lines += ["", S, f"QUICK WINS — {len(qw)} pages (fix these first, under 10 min each)", D]
    for r in qw[:20]:
        lines += [
            f"\n  [{r['seo_score']}/100] {r['url']}",
            f"  Keyword: {r['target_keyword']}",
            f"  NEW TITLE ({r['title_len_new']} chars): {r['recommended_title']}",
            f"  NEW META  ({r['meta_len_new']} chars): {r['recommended_meta']}",
        ]
        if r.get("h1_needs_change") and r.get("recommended_h1") != "OK — no change needed":
            lines.append(f"  NEW H1: {r['recommended_h1']}")
        for issue in r.get("issues","").split("; ")[:3]:
            if issue:
                lines.append(f"    - {issue}")

    # All rewrites — every page
    lines += ["", S, "ALL PAGE REWRITES — complete list sorted by score (lowest first)", D]
    for r in output_rows:
        if not r.get("recommended_title") and not r.get("recommended_meta"):
            continue
        lines += [
            f"\n{r['url']}",
            f"  Score: {r['seo_score']}/100  |  Type: {r['page_type']}  |  Words: {r['word_count']}",
            f"  Target keyword: {r['target_keyword']}",
        ]
        if r.get("recommended_title"):
            curr_t = r.get("current_title","")
            lines.append(f"  CURRENT TITLE ({r['title_len_current']} chars): {curr_t}")
            lines.append(f"  NEW TITLE     ({r['title_len_new']} chars): {r['recommended_title']}")
        if r.get("recommended_meta"):
            curr_m = r.get("current_meta","")[:80]
            lines.append(f"  CURRENT META ({r['meta_len_current']} chars): {curr_m}...")
            lines.append(f"  NEW META     ({r['meta_len_new']} chars): {r['recommended_meta']}")
        if r.get("h1_needs_change") and r.get("recommended_h1") not in ("", "OK — no change needed"):
            lines.append(f"  CURRENT H1: {r.get('current_h1','')[:70]}")
            lines.append(f"  NEW H1:     {r['recommended_h1']}")
        if r.get("recommended_schema"):
            lines.append(f"  SCHEMA: Add {r['recommended_schema']} markup")
        if r.get("issues"):
            for issue in r["issues"].split("; ")[:3]:
                if issue:
                    lines.append(f"  ISSUE: {issue}")

    # Cross-site findings
    if cross_site:
        lines += ["", S, "CROSS-SITE ANALYSIS", D]

        cannibal = cross_site.get("keyword_cannibalism", [])
        if cannibal:
            lines += ["", "KEYWORD CANNIBALISM:"]
            for c in cannibal:
                lines += [
                    f"  Keyword: {c.get('keyword','')}",
                    f"  Competing: {', '.join(c.get('competing_pages',[]))}",
                    f"  Fix: {c.get('recommendation','')}",
                ]

        orphans = cross_site.get("likely_orphan_pages", [])
        if orphans:
            lines += ["", f"LIKELY ORPHAN PAGES ({len(orphans)}):"]
            for o in orphans:
                lines.append(f"  {o}")

        gaps = cross_site.get("top_linking_gaps", [])
        if gaps:
            lines += ["", f"TOP INTERNAL LINKING GAPS ({len(gaps)}):"]
            for g in gaps[:10]:
                lines += [
                    f"  FROM: {g.get('from_page','')}",
                    f"  ADD LINK TO: {g.get('should_link_to','')}",
                    f"  WHY: {g.get('reason','')}",
                    ""
                ]

        content = cross_site.get("content_gaps", [])
        if content:
            lines += ["", "CONTENT GAPS — pages/topics the site should add:"]
            for cg in content:
                lines.append(f"  - {cg}")

        priorities = cross_site.get("top_priorities", [])
        if priorities:
            lines += ["", "TOP CROSS-SITE ACTIONS (do these in order):"]
            for i, p in enumerate(priorities, 1):
                lines.append(f"  {i}. {p}")

    lines += ["", S, "END OF REPORT", S]

    report = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Saved: {path}")

    # Print first 4000 chars to screen
    print("\n" + report[:4000])
    if len(report) > 4000:
        print(f"\n... ({len(report)-4000} more chars in file)")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("FYRFLY SEO ANALYSIS AGENT v2")
    print("Using tool_use for guaranteed structured output")
    print("=" * 60)
    print(f"\nReading crawl data from: {INPUT_CSV}")
    print(f"Model: {MODEL}")
    print(f"Estimated cost: $10-18  |  Estimated time: 20-30 min\n")

    # Read existing crawl data
    try:
        with open(INPUT_CSV, encoding="utf-8") as f:
            original_rows = list(csv.DictReader(f))
        print(f"Loaded {len(original_rows)} pages from {INPUT_CSV}")
    except FileNotFoundError:
        print(f"ERROR: {INPUT_CSV} not found.")
        print("Please upload fyrfly_seo_audit.csv to this Colab session first.")
        print("(Drag it into the file browser panel on the left side)")
        return

    api_key = input("\nPaste your Anthropic API key (sk-ant-...): ").strip()
    client  = anthropic.Anthropic(api_key=api_key)

    # Run analysis on each page
    print(f"\nAnalysing {len(original_rows)} pages...")
    all_audits = []

    for i, row in enumerate(original_rows, 1):
        url_short = row.get("url","").replace("https://www.fyrflysystems.com","") or "/"
        print(f"  [{i:3d}/{len(original_rows)}] {url_short[:60]}")

        audit = analyse_page(client, row)
        # Preserve current values for the output
        audit["current_title"] = row.get("current_title", "")
        audit["current_meta"]  = row.get("current_meta", "")
        all_audits.append(audit)

        score = audit.get("seo_score", "?")
        kw    = audit.get("target_keyword", "")[:35]
        ok    = "OK" if not audit.get("error") else "FAILED"
        print(f"           {ok}  score={score}/100  keyword={kw}")
        time.sleep(DELAY)

    # Cross-site
    cross_site = cross_site_analysis(client, all_audits)

    # Save
    print("\nSaving outputs...")
    output_rows = save_csv(all_audits, original_rows, OUTPUT_CSV)
    write_report(output_rows, cross_site, REPORT_FILE)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"\nDownload from the Colab file browser (folder icon, left sidebar):")
    print(f"  {OUTPUT_CSV}     — open in Google Sheets")
    print(f"  {REPORT_FILE}  — readable priority report")


if __name__ == "__main__":
    main()

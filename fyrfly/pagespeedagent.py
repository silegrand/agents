"""
Fyrfly Systems — PageSpeed Audit Agent
========================================
Tests every important page on www.fyrflysystems.com against the
Google PageSpeed Insights API (Lighthouse 13) for both mobile
and desktop, then uses Claude to write a prioritised fix plan.

HOW TO RUN IN GOOGLE COLAB
---------------------------
1. Get a FREE Google API key (2 minutes):
   a. Go to https://console.cloud.google.com
   b. Create a new project (or select an existing one)
   c. Go to APIs & Services > Library
   d. Search "PageSpeed Insights API" and click Enable
   e. Go to APIs & Services > Credentials
   f. Click Create Credentials > API Key
   g. Copy the key (looks like AIzaSy...)

2. In Colab:
   Cell 1:  !pip install anthropic requests
   Cell 2:  paste this script and run it

3. When prompted, enter:
   - Your Google API key
   - Your Anthropic API key

4. Two files are saved:
   fyrfly_pagespeed.csv       — scores for every page, open in Sheets
   fyrfly_pagespeed_report.txt — prioritised fix plan

COST
----
Google PageSpeed API:  completely FREE (25,000 requests/day quota)
Anthropic (Claude):    approximately $1-3 for the analysis summary
Time:                  approximately 8-12 minutes
"""

import anthropic
import requests
import csv
import time
import json
from datetime import datetime

# ── CONFIGURATION ──────────────────────────────────────────────────────────────

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
BASE_URL      = "https://www.fyrflysystems.com"
MODEL         = "claude-sonnet-4-6"
OUTPUT_CSV    = "fyrfly_pagespeed.csv"
REPORT_FILE   = "fyrfly_pagespeed_report.txt"
DELAY         = 3   # seconds between API calls — be polite to Google

# The pages to test — focused on the ones that matter for SEO and conversion.
# Tool pages and legal pages are excluded (not indexable or not traffic-critical).
PAGES_TO_TEST = [
    # Core pages — highest priority
    {"url": "/",                            "type": "homepage",     "priority": 1},
    {"url": "/education.html",              "type": "sector",       "priority": 1},
    {"url": "/public-sector.html",          "type": "sector",       "priority": 1},
    # Service pages
    {"url": "/cctv.html",                   "type": "service",      "priority": 2},
    {"url": "/access-control.html",         "type": "service",      "priority": 2},
    {"url": "/intruder-alarms.html",        "type": "service",      "priority": 2},
    {"url": "/fire-systems.html",           "type": "service",      "priority": 2},
    {"url": "/wireless-networks.html",      "type": "service",      "priority": 2},
    {"url": "/monitoring.html",             "type": "service",      "priority": 2},
    {"url": "/ai-analytics.html",           "type": "service",      "priority": 2},
    {"url": "/cctv-tower.html",             "type": "product",      "priority": 2},
    {"url": "/support-maintenance.html",    "type": "service",      "priority": 2},
    # Key tools — these drive enquiries
    {"url": "/martyns-law-tool.html",       "type": "tool",         "priority": 2},
    {"url": "/lockdown-procedure-tool.html","type": "tool",         "priority": 2},
    {"url": "/security-policy-review.html", "type": "service",      "priority": 2},
    # Blog + top articles
    {"url": "/blog.html",                   "type": "blog_index",   "priority": 2},
    {"url": "/article-complete-guide-school-security-2026.html", "type": "article", "priority": 2},
    {"url": "/article-martyns-law-protect-duty-schools-public-sector.html", "type": "article", "priority": 3},
    {"url": "/article-school-security-specification.html",       "type": "article", "priority": 3},
    {"url": "/article-independent-school-security.html",         "type": "article", "priority": 3},
    {"url": "/article-martyns-law-physical-security-checklist.html","type": "article","priority": 3},
    # Top local pages
    {"url": "/school-security-kent.html",   "type": "local",        "priority": 3},
    {"url": "/school-security-london.html", "type": "local",        "priority": 3},
    {"url": "/public-sector-security-kent.html", "type": "local",   "priority": 3},
    # Guides
    {"url": "/invisible-shield.html",       "type": "guide",        "priority": 3},
    {"url": "/connected-council.html",      "type": "guide",        "priority": 3},
]

# Score thresholds — matches Google's traffic light system
def score_label(score: float) -> str:
    if score >= 0.9:  return "GOOD"
    if score >= 0.5:  return "NEEDS WORK"
    return "POOR"

def score_emoji(score: float) -> str:
    if score >= 0.9:  return "GREEN"
    if score >= 0.5:  return "AMBER"
    return "RED"


# ── PAGESPEED API CALL ─────────────────────────────────────────────────────────

def run_pagespeed(url: str, strategy: str, api_key: str) -> dict:
    """
    Call the PageSpeed Insights API for one URL and strategy.
    strategy: 'mobile' or 'desktop'
    Returns a dict of extracted metrics, or error info.
    """
    params = {
        "url":      url,
        "strategy": strategy,
        "key":      api_key,
        "category": ["performance", "accessibility", "best-practices", "seo"],
    }

    try:
        r = requests.get(PSI_ENDPOINT, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.Timeout:
        return {"error": "Timeout — Google took too long to analyse this page"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}

    lh = data.get("lighthouseResult", {})

    # ── Category scores (0.0 to 1.0) ──
    cats = lh.get("categories", {})
    perf_score  = cats.get("performance",     {}).get("score", None)
    a11y_score  = cats.get("accessibility",   {}).get("score", None)
    bp_score    = cats.get("best-practices",  {}).get("score", None)
    seo_score   = cats.get("seo",             {}).get("score", None)

    # ── Core Web Vitals (lab data from Lighthouse) ──
    audits = lh.get("audits", {})

    def audit_val(key):
        a = audits.get(key, {})
        return a.get("displayValue", "n/a"), a.get("numericValue"), a.get("score")

    lcp_disp, lcp_num, lcp_score   = audit_val("largest-contentful-paint")
    fcp_disp, fcp_num, fcp_score   = audit_val("first-contentful-paint")
    tbt_disp, tbt_num, tbt_score   = audit_val("total-blocking-time")
    cls_disp, cls_num, cls_score   = audit_val("cumulative-layout-shift")
    si_disp,  si_num,  si_score    = audit_val("speed-index")
    tti_disp, tti_num, tti_score   = audit_val("interactive")
    inp_disp, inp_num, inp_score   = audit_val("interaction-to-next-paint")
    ttfb_disp, ttfb_num, ttfb_score = audit_val("server-response-time")

    # ── Opportunities (things that would speed up the page) ──
    opportunities = []
    for audit_id, audit in audits.items():
        if audit.get("details", {}).get("type") == "opportunity":
            savings_ms = audit.get("details", {}).get("overallSavingsMs", 0) or 0
            if savings_ms > 50 or audit.get("score", 1) < 0.9:
                opportunities.append({
                    "id":          audit_id,
                    "title":       audit.get("title", ""),
                    "description": audit.get("description", "")[:150],
                    "savings_ms":  round(savings_ms),
                    "score":       audit.get("score"),
                    "display":     audit.get("displayValue", ""),
                })
    # Sort by savings descending
    opportunities.sort(key=lambda x: x["savings_ms"], reverse=True)

    # ── Diagnostics (not direct savings but important issues) ──
    diagnostics = []
    diagnostic_ids = [
        "uses-long-cache-ttl", "total-byte-weight", "dom-size",
        "render-blocking-resources", "unused-javascript", "unused-css-rules",
        "uses-optimized-images", "uses-responsive-images",
        "uses-text-compression", "font-display", "third-party-summary",
        "uses-rel-preload", "critical-request-chains",
    ]
    for did in diagnostic_ids:
        audit = audits.get(did, {})
        if audit and audit.get("score", 1) < 0.9:
            diagnostics.append({
                "id":      did,
                "title":   audit.get("title", ""),
                "display": audit.get("displayValue", ""),
                "score":   audit.get("score"),
            })

    # ── Field data (real user metrics from CrUX) ──
    field = data.get("loadingExperience", {}).get("metrics", {})
    field_lcp = field.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("category", "NO DATA")
    field_cls = field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("category", "NO DATA")
    field_inp = field.get("INTERACTION_TO_NEXT_PAINT", {}).get("category", "NO DATA")
    field_fcp = field.get("FIRST_CONTENTFUL_PAINT_MS", {}).get("category", "NO DATA")
    overall_field = data.get("loadingExperience", {}).get("overall_category", "NO DATA")

    return {
        "perf_score":    perf_score,
        "a11y_score":    a11y_score,
        "bp_score":      bp_score,
        "seo_score":     seo_score,
        # Lab metrics
        "lcp":           lcp_disp,
        "lcp_ms":        round(lcp_num) if lcp_num else None,
        "lcp_score":     lcp_score,
        "fcp":           fcp_disp,
        "fcp_ms":        round(fcp_num) if fcp_num else None,
        "tbt":           tbt_disp,
        "tbt_ms":        round(tbt_num) if tbt_num else None,
        "cls":           cls_disp,
        "cls_val":       cls_num,
        "si":            si_disp,
        "tti":           tti_disp,
        "inp":           inp_disp,
        "ttfb":          ttfb_disp,
        # Field data
        "field_lcp":     field_lcp,
        "field_cls":     field_cls,
        "field_inp":     field_inp,
        "field_fcp":     field_fcp,
        "field_overall": overall_field,
        # Issues
        "opportunities": opportunities[:8],
        "diagnostics":   diagnostics[:8],
    }


# ── TEST ALL PAGES ─────────────────────────────────────────────────────────────

def test_all_pages(google_key: str) -> list:
    results = []
    total   = len(PAGES_TO_TEST)

    print(f"\nTesting {total} pages × 2 strategies = {total*2} API calls")
    print(f"Estimated time: {total * DELAY * 2 // 60}-{total * (DELAY+2) * 2 // 60} minutes\n")

    for i, page in enumerate(PAGES_TO_TEST, 1):
        full_url  = BASE_URL + page["url"]
        url_short = page["url"] or "/"

        print(f"[{i:2d}/{total}] {url_short}")

        row = {
            "url":       full_url,
            "path":      page["url"] or "/",
            "page_type": page["type"],
            "priority":  page["priority"],
        }

        for strategy in ["mobile", "desktop"]:
            print(f"         {strategy}...", end="", flush=True)
            result = run_pagespeed(full_url, strategy, google_key)

            if "error" in result:
                print(f" ERROR: {result['error']}")
                row[f"{strategy}_error"] = result["error"]
                continue

            ps = result.get("perf_score")
            print(f" perf={int((ps or 0)*100)}/100  "
                  f"LCP={result.get('lcp','?')}  "
                  f"CLS={result.get('cls','?')}  "
                  f"TBT={result.get('tbt','?')}")

            prefix = strategy[0]  # 'm' or 'd'
            row[f"{prefix}_perf"]         = round((result["perf_score"] or 0) * 100)
            row[f"{prefix}_a11y"]         = round((result["a11y_score"] or 0) * 100)
            row[f"{prefix}_bp"]           = round((result["bp_score"]   or 0) * 100)
            row[f"{prefix}_seo"]          = round((result["seo_score"]  or 0) * 100)
            row[f"{prefix}_perf_label"]   = score_label(result["perf_score"] or 0)
            row[f"{prefix}_lcp"]          = result["lcp"]
            row[f"{prefix}_lcp_ms"]       = result["lcp_ms"]
            row[f"{prefix}_fcp"]          = result["fcp"]
            row[f"{prefix}_tbt"]          = result["tbt"]
            row[f"{prefix}_tbt_ms"]       = result["tbt_ms"]
            row[f"{prefix}_cls"]          = result["cls"]
            row[f"{prefix}_si"]           = result["si"]
            row[f"{prefix}_tti"]          = result["tti"]
            row[f"{prefix}_inp"]          = result["inp"]
            row[f"{prefix}_ttfb"]         = result["ttfb"]
            row[f"{prefix}_field_lcp"]    = result["field_lcp"]
            row[f"{prefix}_field_cls"]    = result["field_cls"]
            row[f"{prefix}_field_inp"]    = result["field_inp"]
            row[f"{prefix}_field_overall"]= result["field_overall"]
            # Store top opportunities as a readable string
            row[f"{prefix}_opportunities"] = " | ".join(
                f"{o['title']} ({o['savings_ms']}ms)"
                for o in result["opportunities"][:5]
            )
            row[f"{prefix}_diagnostics"] = " | ".join(
                d["title"] for d in result["diagnostics"][:5]
            )
            # Keep full opportunity data for Claude
            row[f"{prefix}_opps_full"] = result["opportunities"]
            row[f"{prefix}_diag_full"] = result["diagnostics"]

            time.sleep(DELAY)

        results.append(row)

    return results


# ── CLAUDE ANALYSIS ────────────────────────────────────────────────────────────

ANALYSIS_TOOL = {
    "name": "submit_pagespeed_analysis",
    "description": "Submit the PageSpeed analysis and recommendations",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall_summary": {
                "type": "string",
                "description": "2-3 sentence plain-English summary of the site's speed health"
            },
            "biggest_issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The 5-7 most impactful issues found across the site"
            },
            "priority_fixes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank":        {"type": "integer"},
                        "fix":         {"type": "string"},
                        "why":         {"type": "string"},
                        "how":         {"type": "string"},
                        "impact":      {"type": "string"},
                        "effort":      {"type": "string"},
                        "affects":     {"type": "string"}
                    }
                },
                "description": "Ordered action list, most impactful first"
            },
            "worst_pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url":          {"type": "string"},
                        "mobile_score": {"type": "integer"},
                        "main_issue":   {"type": "string"}
                    }
                },
                "description": "Pages with the lowest mobile performance scores"
            },
            "github_pages_notes": {
                "type": "string",
                "description": "Specific advice for improving speed on a GitHub Pages static site"
            },
            "quick_wins": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Things that can be fixed in under 30 minutes with high impact"
            }
        },
        "required": ["overall_summary", "biggest_issues", "priority_fixes",
                     "worst_pages", "quick_wins"]
    }
}


def analyse_with_claude(client, results: list) -> dict:
    """Pass aggregated results to Claude for interpretation and recommendations."""
    print("\nSending results to Claude for analysis...")

    # Build a compact summary — Claude doesn't need every field, just the key signals
    page_summaries = []
    for r in results:
        if r.get("m_perf") is None and r.get("d_perf") is None:
            continue
        opps = r.get("m_opps_full", [])[:4]
        opp_str = "; ".join(f"{o['title']} saves {o['savings_ms']}ms" for o in opps)

        page_summaries.append(
            f"PATH: {r['path']} ({r['page_type']})\n"
            f"  Mobile:  perf={r.get('m_perf','?')} a11y={r.get('m_a11y','?')} "
            f"seo={r.get('m_seo','?')}\n"
            f"  Desktop: perf={r.get('d_perf','?')}\n"
            f"  LCP={r.get('m_lcp','?')} TBT={r.get('m_tbt','?')} "
            f"CLS={r.get('m_cls','?')} TTFB={r.get('m_ttfb','?')}\n"
            f"  Field LCP={r.get('m_field_lcp','?')} CLS={r.get('m_field_cls','?')}\n"
            f"  Top opportunities: {opp_str}\n"
            f"  Diagnostics: {r.get('m_diagnostics','')}"
        )

    prompt = f"""You are a web performance expert. Analyse these PageSpeed results for 
www.fyrflysystems.com, a static site hosted on GitHub Pages.

IMPORTANT CONTEXT:
- This is a pure HTML/CSS/JS static site on GitHub Pages
- No server-side code, no CMS, no database
- Fixes must be implementable in static HTML/CSS/JS files
- The site owner is non-technical but can edit HTML files

PAGE RESULTS:
{chr(10).join(page_summaries)}

SCORING REFERENCE:
- LCP (Largest Contentful Paint): Good < 2.5s, Needs Work 2.5-4s, Poor > 4s
- TBT (Total Blocking Time): Good < 200ms, Needs Work 200-600ms, Poor > 600ms  
- CLS (Cumulative Layout Shift): Good < 0.1, Needs Work 0.1-0.25, Poor > 0.25
- Performance score: Good 90-100, Needs Work 50-89, Poor 0-49

Call the submit_pagespeed_analysis tool with your findings and recommendations.
For each priority fix, explain HOW to implement it specifically for a GitHub Pages 
static HTML site. Use plain English — the site owner is not a developer."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}]
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.input
    except Exception as e:
        print(f"Claude analysis error: {e}")

    return {}


# ── SAVE CSV ───────────────────────────────────────────────────────────────────

def save_csv(results: list, path: str):
    cols = [
        "url", "path", "page_type", "priority",
        # Mobile scores
        "m_perf", "m_perf_label", "m_a11y", "m_bp", "m_seo",
        "m_lcp", "m_lcp_ms", "m_fcp", "m_tbt", "m_tbt_ms",
        "m_cls", "m_si", "m_tti", "m_inp", "m_ttfb",
        "m_field_lcp", "m_field_cls", "m_field_inp", "m_field_overall",
        "m_opportunities", "m_diagnostics",
        # Desktop scores
        "d_perf", "d_a11y", "d_bp", "d_seo",
        "d_lcp", "d_fcp", "d_tbt", "d_cls",
        "d_field_overall",
        "d_opportunities", "d_diagnostics",
    ]

    # Sort by mobile performance score ascending (worst first)
    sorted_results = sorted(
        results,
        key=lambda x: x.get("m_perf", 100)
    )

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted_results)

    print(f"Saved: {path}  ({len(sorted_results)} pages)")


# ── WRITE REPORT ──────────────────────────────────────────────────────────────

def write_report(results: list, analysis: dict, path: str):
    lines = []
    S = "=" * 70
    D = "-" * 70

    lines += [
        S,
        "FYRFLY SYSTEMS — PAGE SPEED REPORT",
        f"Generated: {datetime.now().strftime('%d %B %Y %H:%M')}",
        f"Pages tested: {len(results)}  |  Strategies: Mobile + Desktop",
        f"Tool: Google PageSpeed Insights API v5 (Lighthouse 13)",
        S,
    ]

    # Overall summary from Claude
    if analysis.get("overall_summary"):
        lines += ["", "OVERALL SUMMARY", D, analysis["overall_summary"], ""]

    # Score table
    lines += ["", "SCORES AT A GLANCE", D]
    lines.append(f"{'PAGE':<45} {'MOB PERF':>9} {'MOB LCP':>9} {'MOB TBT':>9} {'MOB CLS':>8} {'DSK PERF':>9}")
    lines.append(D)

    for r in sorted(results, key=lambda x: x.get("m_perf", 100)):
        path_col = r.get("path", "")[:43]
        m_perf   = r.get("m_perf", "?")
        m_lcp    = r.get("m_lcp",  "?")
        m_tbt    = r.get("m_tbt",  "?")
        m_cls    = r.get("m_cls",  "?")
        d_perf   = r.get("d_perf", "?")

        # Flag poor scores
        perf_flag = " !" if isinstance(m_perf, int) and m_perf < 50 else \
                    " ~" if isinstance(m_perf, int) and m_perf < 90 else "  "

        lines.append(
            f"{path_col:<45} {str(m_perf)+perf_flag:>9} "
            f"{str(m_lcp):>9} {str(m_tbt):>9} {str(m_cls):>8} {str(d_perf):>9}"
        )

    lines.append("")
    lines.append("  ! = POOR (below 50)   ~ = NEEDS WORK (50-89)   (blank) = GOOD (90+)")

    # Core Web Vitals field data
    lines += ["", S, "CORE WEB VITALS — REAL USER DATA (from Google CrUX)", D]
    lines.append(f"{'PAGE':<45} {'LCP':>8} {'CLS':>8} {'INP':>8} {'OVERALL':>10}")
    lines.append(D)
    for r in sorted(results, key=lambda x: x.get("path","")):
        lines.append(
            f"{r.get('path','')[:43]:<45} "
            f"{str(r.get('m_field_lcp','?'))[:8]:>8} "
            f"{str(r.get('m_field_cls','?'))[:8]:>8} "
            f"{str(r.get('m_field_inp','?'))[:8]:>8} "
            f"{str(r.get('m_field_overall','?'))[:10]:>10}"
        )
    lines.append("\n  GOOD = passing  NEEDS_IMPROVEMENT = borderline  SLOW = failing")
    lines.append("  NO DATA = not enough real-user visits yet (normal for new site)")

    # Quick wins
    qw = analysis.get("quick_wins", [])
    if qw:
        lines += ["", S, f"QUICK WINS — {len(qw)} fixes you can do today", D]
        for i, w in enumerate(qw, 1):
            lines.append(f"  {i}. {w}")

    # Priority fixes from Claude
    fixes = analysis.get("priority_fixes", [])
    if fixes:
        lines += ["", S, f"PRIORITY FIX PLAN — {len(fixes)} actions ranked by impact", D]
        for fix in fixes:
            lines += [
                f"\n#{fix.get('rank','?')}  {fix.get('fix','')}",
                f"    Why it matters: {fix.get('why','')}",
                f"    How to fix:     {fix.get('how','')}",
                f"    Impact:         {fix.get('impact','')}",
                f"    Effort:         {fix.get('effort','')}",
                f"    Affects:        {fix.get('affects','')}",
            ]

    # Biggest issues
    issues = analysis.get("biggest_issues", [])
    if issues:
        lines += ["", S, "BIGGEST ISSUES FOUND", D]
        for issue in issues:
            lines.append(f"  - {issue}")

    # Worst pages
    worst = analysis.get("worst_pages", [])
    if worst:
        lines += ["", S, "PAGES NEEDING MOST ATTENTION", D]
        for p in worst:
            lines += [
                f"  {p.get('url','')}",
                f"  Mobile score: {p.get('mobile_score','?')}/100",
                f"  Main issue:   {p.get('main_issue','')}",
                "",
            ]

    # GitHub Pages specific notes
    gh_notes = analysis.get("github_pages_notes", "")
    if gh_notes:
        lines += ["", S, "GITHUB PAGES — SPECIFIC ADVICE", D, gh_notes]

    # Per-page opportunities (raw data)
    lines += ["", S, "PER-PAGE TOP OPPORTUNITIES", D]
    for r in sorted(results, key=lambda x: x.get("m_perf", 100)):
        opps = r.get("m_opps_full", [])
        if not opps:
            continue
        lines.append(f"\n{r.get('path','')}  (mobile perf: {r.get('m_perf','?')}/100)")
        for o in opps[:5]:
            savings = f"saves {o['savings_ms']}ms" if o["savings_ms"] > 0 else ""
            lines.append(f"  - {o['title']} {savings}")
            if o.get("description"):
                lines.append(f"    {o['description'][:100]}")

    lines += ["", S, "END OF REPORT", S]

    report_text = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"Saved: {path}")
    print("\n" + report_text[:3500])
    if len(report_text) > 3500:
        print(f"\n... ({len(report_text) - 3500} more chars — download the file for full report)")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("FYRFLY PAGE SPEED AUDIT AGENT")
    print("=" * 60)
    print(f"Pages to test:    {len(PAGES_TO_TEST)}")
    print(f"API calls:        {len(PAGES_TO_TEST) * 2} (mobile + desktop per page)")
    print(f"Google API cost:  FREE")
    print(f"Anthropic cost:   ~$1-3")
    print(f"Estimated time:   8-12 minutes\n")

    print("You need two API keys:")
    print("  1. Google API key — get free at console.cloud.google.com")
    print("     (Enable 'PageSpeed Insights API', then Credentials > Create API Key)")
    print("  2. Anthropic API key — your existing sk-ant-... key\n")

    google_key = input("Google API key (AIzaSy...): ").strip()
    anthr_key  = input("Anthropic API key (sk-ant-...): ").strip()

    client = anthropic.Anthropic(api_key=anthr_key)

    # Run PageSpeed tests
    results = test_all_pages(google_key)

    # Claude analysis
    analysis = analyse_with_claude(client, results)

    # Save outputs
    print("\nSaving outputs...")
    save_csv(results, OUTPUT_CSV)
    write_report(results, analysis, REPORT_FILE)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"\nTwo files saved — download from Colab file browser (folder icon, left):")
    print(f"  {OUTPUT_CSV}      — all scores in spreadsheet form")
    print(f"  {REPORT_FILE}  — full analysis and fix plan")


if __name__ == "__main__":
    main()

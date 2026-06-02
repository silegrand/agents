"""
Fyrfly Systems - Backlink Opportunity Research Agent v2
=======================================================
Finds, evaluates and ranks backlink opportunities for www.fyrflysystems.com

HOW TO RUN IN GOOGLE COLAB
---------------------------
1. Go to https://colab.research.google.com
2. File > New notebook
3. Cell 1 - paste and run:   !pip install anthropic
4. Cell 2 - paste this entire script and run it
5. Enter your Anthropic API key when prompted
6. Results saved as fyrfly_backlink_opportunities.csv

ESTIMATED COST: approximately $5-12 for a full run
ESTIMATED TIME: 15-25 minutes
"""

import anthropic
import json
import csv
import time
import re
from datetime import datetime

# ── CONFIGURATION ──────────────────────────────────────────────────────────────

TARGET_SITE    = "www.fyrflysystems.com"
MODEL          = "claude-haiku-4-5-20251001"   # fast + cheap, ideal for bulk research
OUTPUT_FILE    = "fyrfly_backlink_opportunities.csv"
QUERIES_PER_CATEGORY = 3   # raise to 5 for more results (costs more)
MIN_SCORE      = 5          # discard opportunities scored below this

TARGET_DESCRIPTION = """
Fyrfly Systems is a physical security company based in Faversham, Kent.
Services: CCTV, access control, intruder alarms, fire systems, 24/7 monitoring.
Sectors: schools (primary, secondary, academies, independent), public sector,
local authorities, NHS estates.
Key compliance topics: Martyn's Law, KCSiE, UK GDPR, DfE protective security.
Geography: South East England (Kent, London, Surrey, Essex, Sussex).
"""

# ── OPPORTUNITY CATEGORIES ─────────────────────────────────────────────────────

CATEGORIES = [
    {
        "name": "Security Industry Associations",
        "queries": [
            "BSIA British Security Industry Association member supplier directory site:bsia.co.uk",
            "NSI NACOSS approved installers find a company directory",
            "SSAIB approved security companies directory listing UK",
            "IFSEC Global security suppliers exhibitor directory UK",
            "Security Institute UK members directory listing",
        ],
        "link_type": "Membership / approved supplier listing",
        "effort": "Medium — membership application required",
    },
    {
        "name": "Education Sector Resources",
        "queries": [
            "school business manager SBM resources links security safeguarding suppliers UK",
            "ISBA independent schools bursar resources useful links suppliers",
            "school safeguarding resources page KCSiE useful links security",
            "education estates facilities management resources security suppliers UK",
            "NASBM ISBL school business professional network resources security",
        ],
        "link_type": "Resource page / supplier directory",
        "effort": "Low-Medium — email to request resource link",
    },
    {
        "name": "Martyn's Law Resources",
        "queries": [
            "Martyn's Law schools guidance resources useful links security",
            "Terrorism Protection of Premises Act 2025 education resources links",
            "ProtectUK ACT awareness education resources security suppliers",
            "Martyn's Law compliance checklist schools resources links 2026",
        ],
        "link_type": "Resource / guidance page outbound links",
        "effort": "Low — email suggesting Fyrfly tools as a useful resource",
    },
    {
        "name": "Kent and South East Business Directories",
        "queries": [
            "Invicta Chamber of Commerce Kent member directory listing",
            "Kent Invicta Chamber business directory security companies",
            "Faversham Swale business directory companies listing",
            "South East England security companies business directory",
            "Kent business network directory add listing security",
        ],
        "link_type": "Local business directory",
        "effort": "Low — online form submission",
    },
    {
        "name": "High Authority UK Business Directories",
        "queries": [
            "Yell.com add business listing security systems Kent",
            "FreeIndex security companies Kent add listing",
            "Kompass UK security systems companies directory submit",
            "Hotfrog UK business directory security companies listing",
            "Cylex UK directory security companies add listing",
        ],
        "link_type": "Business directory listing",
        "effort": "Very low — free online registration",
    },
    {
        "name": "Procurement and Public Sector Portals",
        "queries": [
            "Crown Commercial Service security systems framework suppliers list",
            "Constructionline approved security contractors directory",
            "Find a Tender public sector security CCTV access control supplier",
            "Contracts Finder security systems schools public sector Kent",
        ],
        "link_type": "Supplier register / framework listing",
        "effort": "High — formal accreditation application",
    },
    {
        "name": "Guest Post Opportunities",
        "queries": [
            "school security write for us guest post contribute article",
            "education safeguarding blog guest post security submission",
            "SecEd magazine contribute article school security",
            "Headteacher Update magazine contribute security article",
            "facilities management UK magazine write for us security",
        ],
        "link_type": "Guest article / contributed content",
        "effort": "Medium — pitch then write 600-800 word article",
    },
    {
        "name": "Resource Pages and Link Round-ups",
        "queries": [
            "school security useful resources links safeguarding page",
            "KCSiE resources page useful links schools security suppliers",
            "Martyn's Law resources links schools public sector compliance 2026",
            "education health and safety resources links security compliance",
        ],
        "link_type": "Resource page inclusion",
        "effort": "Low — email to suggest Fyrfly as a resource",
    },
]

# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────────
# This is the instruction set given to Claude for every research call.
# It is very explicit about returning JSON only — this fixes the v1 bug
# where Claude returned explanatory text instead of structured data.

SYSTEM_PROMPT = """You are a specialist SEO researcher. Your ONLY job is to 
identify real backlink opportunities and return them as a JSON array.

You must ALWAYS respond with a valid JSON array and NOTHING else.
No introduction. No explanation. No markdown. No code blocks.
Just the raw JSON array starting with [ and ending with ].

If you cannot find opportunities, return an empty array: []
"""

# ── CORE FUNCTIONS ─────────────────────────────────────────────────────────────

def research_query(client, query: str, category: dict) -> list:
    """Send one research query to Claude and return parsed opportunities."""

    user_prompt = f"""Find backlink opportunities for this website:

WEBSITE: {TARGET_SITE}
DESCRIPTION: {TARGET_DESCRIPTION}

SEARCH QUERY TO RESEARCH: {query}
OPPORTUNITY CATEGORY: {category['name']}
EXPECTED LINK TYPE: {category['link_type']}

Return 3 to 6 REAL opportunities that exist right now. Only include sites you 
are confident actually exist. Do not invent URLs.

Return this exact JSON structure (array of objects):
[
  {{
    "name": "Organisation or website name",
    "url": "https://exact-url.com/specific-page",
    "why_relevant": "One sentence explaining why this is relevant to Fyrfly",
    "authority": "High",
    "link_type": "DoFollow",
    "action": "Exact step to get the link e.g. complete form at /submit",
    "score": 8
  }}
]

authority must be one of: High, Medium, Low
link_type must be one of: DoFollow, NoFollow, Unknown
score must be an integer from 1 to 10

Return ONLY the JSON array. Nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )

        raw = response.content[0].text.strip()

        # Remove any accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Find the JSON array even if there is stray text
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group(0)

        results = json.loads(raw)

        # Attach category metadata
        for item in results:
            item["category"] = category["name"]
            item["effort"]   = category["effort"]
            item["query"]    = query

        return results

    except json.JSONDecodeError:
        print(f"    ! Could not parse JSON for: {query[:55]}...")
        print(f"    ! Raw response: {raw[:200]}")
        return []
    except Exception as e:
        print(f"    ! Error: {e}")
        return []


def deduplicate(items: list) -> list:
    """Keep only one entry per URL (highest score wins)."""
    seen = {}
    for item in items:
        key = item.get("url", "").lower().rstrip("/")
        if not key:
            continue
        if key not in seen or item.get("score", 0) > seen[key].get("score", 0):
            seen[key] = item
    return list(seen.values())


def rank(items: list) -> list:
    """Add a composite score and sort by it descending."""
    auth_pts   = {"High": 3, "Medium": 2, "Low": 1}
    effort_pts = {
        "Very low — free online registration":          5,
        "Low — online form submission":                 4,
        "Low — email to suggest Fyrfly as a resource":  4,
        "Low-Medium — email to request resource link":  3,
        "Medium — email to request resource link":      3,
        "Medium — pitch then write 600-800 word article": 2,
        "Medium — membership application required":     2,
        "High — formal accreditation application":      1,
    }

    for item in items:
        s = item.get("score", 5)
        a = auth_pts.get(item.get("authority", "Low"), 1)
        e = effort_pts.get(item.get("effort", ""), 2)
        f = 2 if item.get("link_type") == "DoFollow" else 0
        item["composite"] = (s * 2) + (a * 1.5) + e + f

    ranked = sorted(items, key=lambda x: x.get("composite", 0), reverse=True)
    for i, item in enumerate(ranked, 1):
        item["rank"] = i
    return ranked


def save_csv(items: list, path: str):
    if not items:
        print("Nothing to save.")
        return
    cols = ["rank","name","url","category","score","authority","link_type",
            "why_relevant","action","effort","composite","query"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    print(f"\nSaved {len(items)} opportunities to {path}")


def print_report(items: list):
    print("\n" + "="*70)
    print("FYRFLY SYSTEMS — BACKLINK OPPORTUNITIES")
    print(f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}")
    print(f"Total unique opportunities: {len(items)}")
    print("="*70)

    # Category breakdown
    cats = {}
    for item in items:
        cats.setdefault(item["category"], []).append(item)
    print("\nBy category:")
    for cat, opps in cats.items():
        avg = sum(o.get("score",0) for o in opps) / len(opps)
        print(f"  {cat}: {len(opps)} opportunities  (avg score {avg:.1f}/10)")

    # Top 20
    print(f"\nTOP 20 PRIORITY OPPORTUNITIES")
    print("-"*70)
    for item in items[:20]:
        print(f"\n#{item['rank']}  {item['name']}")
        print(f"    {item['url']}")
        print(f"    Score {item['score']}/10  |  {item['authority']} authority  |  {item['link_type']}")
        print(f"    Action: {item['action']}")
        print(f"    Effort: {item['effort']}")

    # Quick wins
    print("\n" + "="*70)
    print("QUICK WINS  (score 7+, low/very-low effort)")
    print("-"*70)
    wins = [o for o in items
            if o.get("score",0) >= 7
            and ("Very low" in o.get("effort","") or o.get("effort","").lower().startswith("low"))]
    for o in wins[:15]:
        print(f"  [{o['score']}/10] {o['name']}")
        print(f"         {o['url']}")
        print(f"         {o['action']}")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    print("="*60)
    print("FYRFLY BACKLINK RESEARCH AGENT v2")
    print("="*60)
    print(f"Model: {MODEL}")
    total_q = sum(min(len(c["queries"]), QUERIES_PER_CATEGORY) for c in CATEGORIES)
    print(f"Queries to run: {total_q} across {len(CATEGORIES)} categories")
    print(f"Estimated cost: $5-12  |  Estimated time: 15-25 min\n")

    api_key = input("Paste your Anthropic API key (sk-ant-...): ").strip()
    client  = anthropic.Anthropic(api_key=api_key)

    all_results = []

    for i, cat in enumerate(CATEGORIES, 1):
        print(f"\n[{i}/{len(CATEGORIES)}] {cat['name']}")
        queries = cat["queries"][:QUERIES_PER_CATEGORY]

        for j, q in enumerate(queries, 1):
            print(f"  {j}/{len(queries)}: {q[:60]}...")
            found = research_query(client, q, cat)
            valid = [o for o in found if o.get("score", 0) >= MIN_SCORE]
            all_results.extend(valid)
            print(f"       -> {len(valid)} opportunities found  (running total: {len(all_results)})")
            if j < len(queries):
                time.sleep(1)  # gentle rate limiting

    print(f"\nResearch done. Processing {len(all_results)} raw results...")
    unique = deduplicate(all_results)
    print(f"After deduplication: {len(unique)} unique opportunities")
    ranked = rank(unique)
    save_csv(ranked, OUTPUT_FILE)
    print_report(ranked)
    print(f"\nDone. Download {OUTPUT_FILE} from the Colab file browser (folder icon, left sidebar).")


if __name__ == "__main__":
    main()

"""
Sunday finalizer.
Reads curated articles, runs tournament ranking via Gemini,
generates the final edition JSON and HTML email.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from llm_client import ProjectError, generate_json
from edition import CONTENT_DIR, RAW_DIR, get_edition, set_edition, date_label, date_range_label
from dedupe import dedupe_articles, DEFAULT_THRESHOLD

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

EDITORIAL_PROMPT = """You are the editor-in-chief of "Cybersecurity Weekly" — a premium newsletter read by CISOs, security engineers, and practitioners. Your readers are smart, time-crunched professionals who need to act on what they read.

I am giving you this week's cybersecurity stories, already grouped by topic. Each group may contain coverage from multiple sources about the SAME real-world event.

{stories_json}

YOUR JOB — write the actual newsletter, not a list of links:

1. SELECT 8-12 of the most important DISTINCT stories (quality over quantity)
2. For each selected story:
   - Synthesize the best details from ALL source versions in the group
   - Write with authority and specificity — name vendors, CVEs, threat actors, affected sectors
   - Do NOT hedge with "reportedly" or "according to" — state facts directly
3. ASSIGN each story a tier:
   - tier 1 (BREAKING): Active exploitation, mass impact, critical CVEs, nation-state campaigns. 1-3/week.
   - tier 2 (FOCUS): 5G, indoor cells, NMS, webapp management, significant but contained. 2-4/week.
   - tier 3 (NOTABLE): Important but not urgent — research, policy, vendor disclosures. The rest.
4. WRITE a week_intro — 2-3 sentences from the editor's perspective identifying the theme of this week's threat landscape. Example: "Patch Tuesday dominated the week with 206 Microsoft fixes, but the real story is the trio of supply-chain attacks that hit both Linux and enterprise SaaS platforms simultaneously."
5. WRITE a subject_line — factual, specific, attention-grabbing but NOT clickbait. Lead with the biggest story.

DEPTH REQUIREMENTS by tier:
- tier 1: full synthesis (3-4 sentences) + "impact" (1-2 sentences: what does this mean for security teams?) + "action" (1 sentence: what should teams do this week?)
- tier 2: focused synthesis (2-3 sentences) + "impact" (1 sentence)
- tier 3: sharp one-liner (1-2 sentences), no impact/action needed

RULES:
- Each story appears EXACTLY ONCE in your output
- Use the canonical_id from the group's first source as the article id
- Include all source URLs in a "sources" array (not just one)
- If the group has multiple sources, use the primary/government source URL as the main url

Respond ONLY with this JSON (no extra text):
{{
  "subject_line": "...",
  "week_intro": "...",
  "articles": [
    {{
      "id": "...",
      "title": "...",
      "summary": "...",
      "impact": "...",
      "action": "...",
      "tier": 1,
      "sources": [{{"name": "...", "url": "..."}}],
      "url": "...",
      "publishedDate": "...",
      "cve_ids": [],
      "affected_systems": [],
      "threat_actor": null
    }}
  ]
}}

Order: tier 1 first, then tier 2, then tier 3. Within each tier, most important first.
"""


def generate_email_html(content: dict) -> str:
    template_path = TEMPLATES_DIR / "email.html"
    with open(template_path) as f:
        template = Template(f.read())

    site_url = os.environ.get("SITE_URL", "https://vishakadatta.github.io/cybersecurity-weekly/")
    # Brevo per-recipient unsubscribe URL — falls back to a static manage-preferences
    # page if the env var is unset (e.g. when running locally without Brevo configured).
    # In production Brevo replaces {{ params.unsubscribe }} per-recipient.
    unsubscribe_url = os.environ.get(
        "UNSUBSCRIBE_URL",
        "{{ params.unsubscribe }}",
    )

    return template.render(
        subject_line=content["subjectLine"],
        week_intro=content.get("weekIntro", ""),
        edition_label=content.get("editionLabel", content["edition"]),
        year=content["year"],
        articles=content["articles"],
        site_url=site_url,
        unsubscribe_url=unsubscribe_url,
    )


def main():
    year, edition = get_edition()
    print(f"Edition: {edition} ({date_range_label(edition)})")

    curated_file = RAW_DIR / f"{edition}-curated.json"
    if not curated_file.exists():
        print(f"ERROR: No curated file found at {curated_file}", file=sys.stderr)
        sys.exit(1)

    with open(curated_file) as f:
        articles = json.load(f)

    print(f"Loaded {len(articles)} curated articles")

    # Cluster articles by story before passing to the LLM.
    # This gives the LLM all source versions of each real-world event
    # so it can synthesize across them instead of just picking one.
    print("Clustering by story for cross-source synthesis...")
    canonicals, clusters = dedupe_articles(articles, threshold=0.72)
    print(f"  {len(articles)} articles → {len(canonicals)} story clusters")

    # Sort clusters by best relevance_score and take top 35 stories
    scored_clusters = []
    for canonical, cluster in zip(canonicals, clusters):
        best_score = max(a.get("relevance_score", 0) for a in cluster)
        scored_clusters.append((best_score, canonical, cluster))
    scored_clusters.sort(key=lambda x: -x[0])
    top_clusters = scored_clusters[:35]

    # Build story groups for the prompt — each group has one canonical
    # plus all alternate-source versions so the LLM can synthesize them.
    story_groups = []
    for _score, canonical, cluster in top_clusters:
        group: dict = {
            "canonical_id": canonical["id"],
            "sources": [
                {
                    "source": a.get("source", ""),
                    "title": a.get("title", ""),
                    "summary": a.get("summary", a.get("summary_raw", ""))[:400],
                    "url": a.get("url", ""),
                    "source_quality": a.get("source_quality", "reporting"),
                    "relevance_score": a.get("relevance_score", 5),
                    "publishedDate": a.get("publishedDate", ""),
                }
                for a in cluster
            ],
        }
        # Surface richer metadata on the group level for the LLM
        cve_ids = list({c for a in cluster for c in a.get("cve_ids", [])})
        affected_systems = list({s for a in cluster for s in a.get("affected_systems", [])})
        threat_actors = list({a["threat_actor"] for a in cluster if a.get("threat_actor")})
        urgency_rank = {"patch-now": 4, "this-week": 3, "monitor": 2, "informational": 1}
        urgency = max((a.get("urgency", "informational") for a in cluster),
                      key=lambda u: urgency_rank.get(u, 1))
        tags = list({t for a in cluster for t in a.get("tags", [])})
        if cve_ids:
            group["cve_ids"] = cve_ids
        if affected_systems:
            group["affected_systems"] = affected_systems
        if threat_actors:
            group["threat_actors"] = threat_actors
        group["urgency"] = urgency
        group["tags"] = tags[:8]
        story_groups.append(group)

    print(f"Running editorial synthesis on {len(story_groups)} story clusters...")
    prompt = EDITORIAL_PROMPT.format(stories_json=json.dumps(story_groups, indent=2))

    try:
        result = generate_json(prompt, backend="groq", temperature=0.5)
    except ProjectError as e:
        print(f"\nABORTING: Unrecoverable project error — {e}", file=sys.stderr)
        sys.exit(1)

    if not result:
        print("ERROR: Editorial synthesis failed after retries", file=sys.stderr)
        sys.exit(1)

    raw_selected = result.get("articles", [])

    # Hard dedupe on LLM output as a safety net (first-seen wins)
    seen_ids: set[str] = set()
    deduped_selected = []
    for a in raw_selected:
        aid = a.get("id", "")
        if aid and aid in seen_ids:
            print(f"  [dedup] dropped repeated id={aid}: {a.get('title','')[:60]}")
            continue
        seen_ids.add(aid)
        deduped_selected.append(a)

    if len(deduped_selected) < len(raw_selected):
        print(f"  [dedup] {len(raw_selected)} → {len(deduped_selected)} after removing LLM repeats")

    content = {
        "edition": edition,
        "year": year,
        "editionLabel": date_range_label(edition),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "subjectLine": result.get("subject_line", result.get("subjectLine", "Cybersecurity Weekly")),
        "weekIntro": result.get("week_intro", ""),
        "articles": deduped_selected,
    }

    tier_counts = {1: 0, 2: 0, 3: 0}
    for a in content["articles"]:
        tier_counts[a.get("tier", 3)] += 1

    print(f"\nSelected {len(content['articles'])} articles:")
    print(f"  Tier 1 (Breaking): {tier_counts[1]}")
    print(f"  Tier 2 (Focus):    {tier_counts[2]}")
    print(f"  Tier 3 (Notable):  {tier_counts[3]}")
    print(f"  Subject: {content['subjectLine']}")

    year_dir = CONTENT_DIR / year
    year_dir.mkdir(parents=True, exist_ok=True)
    final_file = year_dir / f"{edition}.json"
    with open(final_file, "w") as f:
        json.dump(content, f, indent=2)
    print(f"\nSaved finalized content to {final_file}")

    set_edition(edition)

    email_html = generate_email_html(content)
    email_file = RAW_DIR / f"{edition}-email.html"
    with open(email_file, "w") as f:
        f.write(email_html)
    print(f"Saved email HTML to {email_file}")


if __name__ == "__main__":
    main()

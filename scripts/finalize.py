"""
Sunday finalizer.
Reads curated articles, runs tournament ranking via Gemini,
generates the final edition JSON and HTML email.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from gemini_client import ProjectError, create_client, generate_json
from edition import CONTENT_DIR, RAW_DIR, get_edition, set_edition, date_label, date_range_label

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

RANKING_PROMPT = """You are the editor-in-chief of "Cybersecurity Weekly", a premium cybersecurity newsletter. You must select and rank the TOP stories from this week.

Here are all the curated articles from this week, already scored for relevance:

{articles_json}

Your tasks:
1. SELECT the top 8-12 most important articles (quality over quantity)
2. ASSIGN each a tier:
   - tier 1 (BREAKING): Major stories with widespread impact. Usually 1-3 per week.
   - tier 2 (FOCUS): Stories about 5G, indoor cells, NMS, webapp management. Usually 2-4 per week.
   - tier 3 (NOTABLE): Other significant stories worth knowing. The rest.
3. RANK articles within each tier by importance
4. Write a CATCHY subject line for the newsletter (factual but attention-grabbing, not clickbait)
   Example: "Iran-Linked Hackers Hit Medical Devices + Critical 5G Flaw Exposed"

IMPORTANT: If an article touches on 5G, indoor cells, NMS, or network management, it should be tier 2 at minimum, even if the relevance score is lower.

Respond with JSON in this exact format:
{{
  "subjectLine": "...",
  "articles": [
    {{
      "id": "...",
      "title": "...",
      "summary": "...",
      "source": "...",
      "url": "...",
      "tier": 1,
      "publishedDate": "..."
    }}
  ]
}}

Order articles: all tier 1 first, then tier 2, then tier 3.
"""


def generate_email_html(content: dict) -> str:
    template_path = TEMPLATES_DIR / "email.html"
    with open(template_path) as f:
        template = Template(f.read())

    site_url = "https://vishakadatta.github.io/cybersecurity-weekly/"
    unsubscribe_url = "https://github.com/Vishakadatta/cybersecurity-weekly/issues/new?template=unsubscribe.yml&title=Unsubscribe"

    return template.render(
        subject_line=content["subjectLine"],
        edition_label=content.get("editionLabel", content["edition"]),
        year=content["year"],
        articles=content["articles"],
        site_url=site_url,
        unsubscribe_url=unsubscribe_url,
    )


def main():
    client = create_client()

    year, edition = get_edition()
    print(f"Edition: {edition} ({date_range_label(edition)})")

    curated_file = RAW_DIR / f"{edition}-curated.json"
    if not curated_file.exists():
        print(f"ERROR: No curated file found at {curated_file}", file=sys.stderr)
        sys.exit(1)

    with open(curated_file) as f:
        articles = json.load(f)

    print(f"Loaded {len(articles)} curated articles")
    print("Running tournament ranking via Gemini...")

    top_articles = articles[:40]
    articles_for_prompt = [{
        "id": a["id"],
        "title": a.get("title", "Untitled"),
        "summary": a.get("summary", a.get("summary_raw", ""))[:300],
        "source": a.get("source", "Unknown"),
        "url": a.get("url", ""),
        "relevance_score": a.get("relevance_score", 5),
        "tags": a.get("tags", []),
        "publishedDate": a.get("publishedDate", ""),
    } for a in top_articles]

    prompt = RANKING_PROMPT.format(articles_json=json.dumps(articles_for_prompt, indent=2))

    try:
        result = generate_json(client, prompt, temperature=0.4)
    except ProjectError as e:
        print(f"\nABORTING: Unrecoverable project error — {e}", file=sys.stderr)
        sys.exit(1)

    if not result:
        print("ERROR: Gemini ranking failed after retries", file=sys.stderr)
        sys.exit(1)

    content = {
        "edition": edition,
        "year": year,
        "editionLabel": date_range_label(edition),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "subjectLine": result.get("subjectLine", "Cybersecurity Weekly"),
        "articles": result.get("articles", []),
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

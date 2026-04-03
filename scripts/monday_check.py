"""
Monday morning emergency check.
Quick scrape of all sources to see if anything major broke overnight.
If a high-impact story is found, injects it into the finalized content.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gemini_client import create_client, generate_json

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
CONTENT_DIR = ROOT_DIR / "content"
RAW_DIR = CONTENT_DIR / "raw"

PT = timezone(timedelta(hours=-7))

EMERGENCY_CHECK_PROMPT = """You are a cybersecurity news editor. Here is a list of articles scraped this Monday morning. Compare them against the already-finalized newsletter articles below.

FINALIZED NEWSLETTER ARTICLES:
{existing_json}

NEW ARTICLES FROM MONDAY MORNING:
{new_json}

Question: Are any of the new Monday morning articles SO important that they should be added to the newsletter? This means:
- Critical zero-day being actively exploited
- Major nation-state attack discovered
- Widespread infrastructure compromise
- Something that would make the newsletter look outdated if excluded

If YES, respond with JSON:
{{"inject": true, "articles": [array of articles to add, each with: id, title, summary, source, url, tier (1 or 2), publishedDate]}}

If NO (the existing newsletter is still comprehensive and up-to-date), respond with:
{{"inject": false, "reason": "brief explanation"}}
"""


def get_current_week() -> tuple[str, str]:
    now = datetime.now(PT)
    year = str(now.year)
    week = f"w{now.isocalendar()[1]:02d}"
    return year, week


def main():
    client = create_client()

    year, week = get_current_week()
    content_file = CONTENT_DIR / year / f"{week}.json"

    if not content_file.exists():
        print(f"No finalized content found at {content_file}, skipping emergency check")
        return

    with open(content_file) as f:
        content = json.load(f)

    sys.path.insert(0, str(SCRIPTS_DIR))
    from scrape import load_sources, fetch_rss

    cutoff = datetime.now(timezone.utc) - timedelta(hours=18)
    sources = load_sources()

    monday_articles = []
    for source in sources:
        articles = fetch_rss(source, cutoff)
        monday_articles.extend(articles)

    if not monday_articles:
        print("No new articles found this Monday morning. Newsletter is good to go.")
        return

    print(f"Found {len(monday_articles)} articles from the last 18 hours")

    existing_summary = [
        {"title": a["title"], "source": a["source"], "tier": a["tier"]}
        for a in content["articles"]
    ]
    new_summary = [
        {"id": a["id"], "title": a["title"], "source": a["source"], "url": a["url"],
         "raw_summary": a.get("summary_raw", "")[:200], "publishedDate": a.get("publishedDate", "")}
        for a in monday_articles[:30]
    ]

    prompt = EMERGENCY_CHECK_PROMPT.format(
        existing_json=json.dumps(existing_summary, indent=2),
        new_json=json.dumps(new_summary, indent=2),
    )

    result = generate_json(client, prompt, temperature=0.2)

    if not result:
        print("[WARN] Gemini check failed, proceeding with existing newsletter")
        return

    if not result.get("inject"):
        print(f"No emergency additions needed: {result.get('reason', 'Newsletter is comprehensive')}")
        return

    new_articles = result.get("articles", [])
    print(f"EMERGENCY: Injecting {len(new_articles)} breaking stories!")

    for article in new_articles:
        content["articles"].insert(0, article)

    if new_articles:
        top_title = new_articles[0].get("title", "")
        content["subjectLine"] = f"BREAKING: {top_title[:60]} + {content['subjectLine']}"

    content["generatedAt"] = datetime.now(timezone.utc).isoformat()

    with open(content_file, "w") as f:
        json.dump(content, f, indent=2)
    print(f"Updated {content_file} with emergency additions")

    from finalize import generate_email_html
    email_html = generate_email_html(content)
    email_file = RAW_DIR / f"{year}-{week}-email.html"
    with open(email_file, "w") as f:
        f.write(email_html)
    print(f"Regenerated email HTML at {email_file}")


if __name__ == "__main__":
    main()

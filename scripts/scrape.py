"""
Friday + Saturday + Sunday scraper.
Fetches articles from all configured RSS sources, deduplicates,
and saves raw articles as JSON for the current edition.
"""

import json
import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from dateutil import parser as dateparser
from dateutil import tz as dateutz

from edition import RAW_DIR, compute_friday, set_edition

SCRIPTS_DIR = Path(__file__).parent
SOURCES_FILE = SCRIPTS_DIR / "sources.json"

# A realistic User-Agent — some feeds (Schneier on Security, others behind WAFs)
# 429 or 403 on the default httpx UA. Identifying ourselves honestly avoids that.
USER_AGENT = (
    "CybersecurityWeeklyBot/1.0 (+https://github.com/Vishakadatta/cybersecurity-weekly; "
    "weekly RSS aggregator for newsletter)"
)

# Polite delay between feed fetches so we don't hammer hosts that share infra.
INTER_FEED_DELAY = 1.0

# Map common US timezone abbreviations so dateutil.parser can resolve dates like
# "Fri, 06 Jun 2026 14:32:00 PDT" without emitting UnknownTimezoneWarning.
TZINFOS = {
    "PDT": dateutz.gettz("America/Los_Angeles"),
    "PST": dateutz.gettz("America/Los_Angeles"),
    "MDT": dateutz.gettz("America/Denver"),
    "MST": dateutz.gettz("America/Denver"),
    "CDT": dateutz.gettz("America/Chicago"),
    "CST": dateutz.gettz("America/Chicago"),
    "EDT": dateutz.gettz("America/New_York"),
    "EST": dateutz.gettz("America/New_York"),
    "BST": dateutz.gettz("Europe/London"),
    "CEST": dateutz.gettz("Europe/Berlin"),
    "CET": dateutz.gettz("Europe/Berlin"),
}


def load_sources() -> list[dict]:
    with open(SOURCES_FILE) as f:
        return json.load(f)


def article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def fetch_rss(source: dict, cutoff: datetime) -> list[dict]:
    articles = []
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    }
    try:
        resp = httpx.get(source["url"], timeout=30, follow_redirects=True, headers=headers)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        for entry in feed.entries:
            published = None
            for date_field in ("published", "updated", "created"):
                raw_date = getattr(entry, date_field, None)
                if raw_date:
                    try:
                        published = dateparser.parse(raw_date, tzinfos=TZINFOS)
                        break
                    except (ValueError, TypeError):
                        continue

            if not published:
                published = datetime.now(timezone.utc)

            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)

            if published < cutoff:
                continue

            link = getattr(entry, "link", "")
            title = getattr(entry, "title", "No title")
            summary = getattr(entry, "summary", getattr(entry, "description", ""))
            if len(summary) > 2000:
                summary = summary[:2000] + "..."

            articles.append({
                "id": article_id(link),
                "title": title,
                "summary_raw": summary,
                "source": source["name"],
                "url": link,
                "publishedDate": published.isoformat(),
                "scrapedAt": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        print(f"  [WARN] Failed to fetch {source['name']}: {e}", file=sys.stderr)

    return articles


def merge_articles(existing: list[dict], new: list[dict]) -> list[dict]:
    seen = {a["id"] for a in existing}
    merged = list(existing)
    added = 0
    for article in new:
        if article["id"] not in seen:
            seen.add(article["id"])
            merged.append(article)
            added += 1
    print(f"  Merged: {added} new, {len(merged)} total")
    return merged


def main():
    edition = compute_friday()
    set_edition(edition)
    day = datetime.now(timezone(timedelta(hours=-7))).strftime("%A").lower()
    sources = load_sources()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=8)

    raw_file = RAW_DIR / f"{edition}-{day}.json"
    cumulative_file = RAW_DIR / f"{edition}-cumulative.json"

    existing = []
    if cumulative_file.exists():
        with open(cumulative_file) as f:
            existing = json.load(f)
        print(f"Loaded {len(existing)} existing articles from cumulative file")

    all_new = []
    for i, source in enumerate(sources):
        print(f"Scraping: {source['name']}...")
        articles = fetch_rss(source, cutoff)
        print(f"  Found {len(articles)} articles within date range")
        all_new.extend(articles)
        # Polite delay between feeds — avoids 429 from shared-infra hosts.
        if i < len(sources) - 1:
            time.sleep(INTER_FEED_DELAY)

    with open(raw_file, "w") as f:
        json.dump(all_new, f, indent=2)
    print(f"\nSaved {len(all_new)} articles to {raw_file.name}")

    merged = merge_articles(existing, all_new)
    with open(cumulative_file, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"Cumulative total: {len(merged)} articles in {cumulative_file.name}")


if __name__ == "__main__":
    main()

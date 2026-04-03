"""
Friday + Saturday + Sunday scraper.
Fetches articles from all configured RSS sources, deduplicates,
and saves raw articles as JSON for the current week.
"""

import json
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from dateutil import parser as dateparser

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
CONTENT_DIR = ROOT_DIR / "content"
RAW_DIR = CONTENT_DIR / "raw"
SOURCES_FILE = SCRIPTS_DIR / "sources.json"

PT = timezone(timedelta(hours=-7))


def get_current_week() -> tuple[str, str]:
    now = datetime.now(PT)
    year = str(now.year)
    week = f"w{now.isocalendar()[1]:02d}"
    return year, week


def load_sources() -> list[dict]:
    with open(SOURCES_FILE) as f:
        return json.load(f)


def article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def fetch_rss(source: dict, cutoff: datetime) -> list[dict]:
    """Fetch and parse an RSS feed, returning articles newer than cutoff."""
    articles = []
    try:
        resp = httpx.get(source["url"], timeout=30, follow_redirects=True)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        for entry in feed.entries:
            published = None
            for date_field in ("published", "updated", "created"):
                raw_date = getattr(entry, date_field, None)
                if raw_date:
                    try:
                        published = dateparser.parse(raw_date)
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
    """Merge new articles into existing, deduplicating by id."""
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
    year, week = get_current_week()
    day = datetime.now(PT).strftime("%A").lower()
    sources = load_sources()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=8)

    raw_file = RAW_DIR / f"{year}-{week}-{day}.json"
    cumulative_file = RAW_DIR / f"{year}-{week}-cumulative.json"

    existing = []
    if cumulative_file.exists():
        with open(cumulative_file) as f:
            existing = json.load(f)
        print(f"Loaded {len(existing)} existing articles from cumulative file")

    all_new = []
    for source in sources:
        print(f"Scraping: {source['name']}...")
        articles = fetch_rss(source, cutoff)
        print(f"  Found {len(articles)} articles within date range")
        all_new.extend(articles)

    with open(raw_file, "w") as f:
        json.dump(all_new, f, indent=2)
    print(f"\nSaved {len(all_new)} articles to {raw_file.name}")

    merged = merge_articles(existing, all_new)
    with open(cumulative_file, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"Cumulative total: {len(merged)} articles in {cumulative_file.name}")


if __name__ == "__main__":
    main()

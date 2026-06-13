"""
Shared edition helper. All scripts use this to identify the current edition.

Edition ID = the Friday date (YYYY-MM-DD) when scraping started.
Friday sets it, Saturday/Sunday/Monday read it from content/latest.json.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

PT = timezone(timedelta(hours=-7))
ROOT_DIR = Path(__file__).parent.parent
CONTENT_DIR = ROOT_DIR / "content"
RAW_DIR = CONTENT_DIR / "raw"
LATEST_FILE = CONTENT_DIR / "latest.json"


def compute_friday() -> str:
    """Return the most recent Friday's date as YYYY-MM-DD."""
    now = datetime.now(PT)
    days_since_friday = (now.weekday() - 4) % 7
    friday = now.date() - timedelta(days=days_since_friday)
    return friday.isoformat()


def get_edition() -> tuple[str, str]:
    """
    Get the current edition (year, edition_id).
    Reads from latest.json if it exists, otherwise computes from Friday date.
    """
    if LATEST_FILE.exists():
        with open(LATEST_FILE) as f:
            data = json.load(f)
        if "edition" in data:
            return data["year"], data["edition"]

    edition = compute_friday()
    year = edition[:4]
    return year, edition


def set_edition(edition: str):
    """Write the current edition to latest.json (called by scrape.py on Friday)."""
    year = edition[:4]
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LATEST_FILE, "w") as f:
        json.dump({"year": year, "edition": edition}, f, indent=2)


def date_label(edition: str) -> str:
    """Convert '2026-04-10' to 'April 10, 2026'."""
    d = datetime.strptime(edition, "%Y-%m-%d")
    return d.strftime("%B %-d, %Y")


def date_range_label(edition: str) -> str:
    """Convert '2026-06-12' to 'Jun 5 – 12, 2026' (trailing 8-day scrape window)."""
    fri = datetime.strptime(edition, "%Y-%m-%d")
    start = fri - timedelta(days=7)
    if start.month == fri.month:
        return f"{start.strftime('%b %-d')} – {fri.strftime('%-d, %Y')}"
    return f"{start.strftime('%b %-d')} – {fri.strftime('%b %-d, %Y')}"

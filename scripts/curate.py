"""
Saturday curator.
Reads cumulative raw articles, sends them to Gemini for summarization
and categorization, saves the enriched dataset.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google import genai
from google.genai import types

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
CONTENT_DIR = ROOT_DIR / "content"
RAW_DIR = CONTENT_DIR / "raw"

PT = timezone(timedelta(hours=-7))

MODEL = "gemini-2.5-flash"

SUMMARIZE_PROMPT = """You are a cybersecurity news editor. I will give you a list of raw articles scraped from security news sources this week.

For each article, produce:
1. A clean, concise title (fix any RSS formatting artifacts)
2. A 2-3 sentence summary that captures the key facts and why it matters
3. A relevance_score from 1-10 (10 = most important/impactful)
4. Tags: an array of relevant topic tags (e.g. "ransomware", "zero-day", "5G", "indoor-cells", "NMS", "APT", "vulnerability", "data-breach", "policy")

Focus areas that should get higher relevance scores:
- 5G security, indoor small cells, cellular infrastructure
- NMS (Network Management Systems), webapp management
- Critical zero-days, nation-state attacks, widespread impact

Respond with a JSON array. Each element must have these fields:
- id (string, keep the original)
- title (string, cleaned up)
- summary (string, 2-3 sentences)
- relevance_score (number, 1-10)
- tags (array of strings)

Here are the articles:

"""


def get_current_week() -> tuple[str, str]:
    now = datetime.now(PT)
    year = str(now.year)
    week = f"w{now.isocalendar()[1]:02d}"
    return year, week


def chunk_articles(articles: list[dict], chunk_size: int = 15) -> list[list[dict]]:
    return [articles[i:i + chunk_size] for i in range(0, len(articles), chunk_size)]


def summarize_batch(client: genai.Client, articles: list[dict]) -> list[dict]:
    input_data = []
    for a in articles:
        input_data.append({
            "id": a["id"],
            "title": a["title"],
            "raw_summary": a.get("summary_raw", "")[:500],
            "source": a["source"],
            "url": a["url"],
        })

    prompt = SUMMARIZE_PROMPT + json.dumps(input_data, indent=2)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )

    try:
        results = json.loads(response.text)
        if isinstance(results, dict) and "articles" in results:
            results = results["articles"]
        return results
    except (json.JSONDecodeError, TypeError):
        print(f"  [WARN] Failed to parse Gemini response, skipping batch", file=sys.stderr)
        return []


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    year, week = get_current_week()
    cumulative_file = RAW_DIR / f"{year}-{week}-cumulative.json"

    if not cumulative_file.exists():
        print(f"ERROR: No cumulative file found at {cumulative_file}", file=sys.stderr)
        sys.exit(1)

    with open(cumulative_file) as f:
        articles = json.load(f)

    print(f"Loaded {len(articles)} articles for summarization")

    articles_by_id = {a["id"]: a for a in articles}
    chunks = chunk_articles(articles)
    all_summaries = []

    for i, chunk in enumerate(chunks):
        print(f"Processing batch {i + 1}/{len(chunks)} ({len(chunk)} articles)...")
        try:
            summaries = summarize_batch(client, chunk)
            all_summaries.extend(summaries)
            print(f"  Got {len(summaries)} summaries")
        except Exception as e:
            print(f"  [ERROR] Batch {i + 1} failed: {e}", file=sys.stderr)
        if i < len(chunks) - 1:
            time.sleep(2)

    for summary in all_summaries:
        aid = summary.get("id")
        if aid and aid in articles_by_id:
            articles_by_id[aid]["title"] = summary.get("title", articles_by_id[aid]["title"])
            articles_by_id[aid]["summary"] = summary.get("summary", "")
            articles_by_id[aid]["relevance_score"] = summary.get("relevance_score", 5)
            articles_by_id[aid]["tags"] = summary.get("tags", [])

    enriched = list(articles_by_id.values())
    enriched.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)

    curated_file = RAW_DIR / f"{year}-{week}-curated.json"
    with open(curated_file, "w") as f:
        json.dump(enriched, f, indent=2)

    print(f"\nSaved {len(enriched)} curated articles to {curated_file.name}")
    print(f"Top 5 by relevance:")
    for a in enriched[:5]:
        print(f"  [{a.get('relevance_score', '?')}] {a.get('title', 'Untitled')}")


if __name__ == "__main__":
    main()

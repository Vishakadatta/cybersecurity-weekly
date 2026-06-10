"""
Saturday curator.
Reads cumulative raw articles, sends them to Gemini for summarization
and categorization, saves the enriched dataset.
"""

import json
import sys
from pathlib import Path

from llm_client import ProjectError, generate_json, throttle
from edition import RAW_DIR, get_edition
from dedupe import dedupe_articles
from discover import discover as discovery_pass

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

Respond with a JSON object containing a single key "articles" whose value is an array. Each element of the array must have these fields:
- id (string, keep the original)
- title (string, cleaned up)
- summary (string, 2-3 sentences)
- relevance_score (number, 1-10)
- tags (array of strings)

Here are the articles:

"""


def chunk_articles(articles: list[dict], chunk_size: int = 10) -> list[list[dict]]:
    return [articles[i:i + chunk_size] for i in range(0, len(articles), chunk_size)]


def main():
    year, edition = get_edition()
    cumulative_file = RAW_DIR / f"{edition}-cumulative.json"

    if not cumulative_file.exists():
        print(f"ERROR: No cumulative file found at {cumulative_file}", file=sys.stderr)
        sys.exit(1)

    with open(cumulative_file) as f:
        articles = json.load(f)

    print(f"Edition: {edition}")
    print(f"Loaded {len(articles)} total articles")

    curated_file = RAW_DIR / f"{edition}-curated.json"
    already_curated = {}
    if curated_file.exists():
        with open(curated_file) as f:
            for a in json.load(f):
                if a.get("summary"):
                    already_curated[a["id"]] = a

    articles_by_id = {a["id"]: a for a in articles}
    if already_curated:
        for aid, curated in already_curated.items():
            if aid in articles_by_id:
                articles_by_id[aid].update({
                    k: curated[k] for k in ("title", "summary", "relevance_score", "tags")
                    if k in curated
                })

    uncurated_all = [a for a in articles if not a.get("summary")]

    if uncurated_all:
        print(f"  Deduping {len(uncurated_all)} uncurated articles by title embedding...")
        canonicals, _ = dedupe_articles(uncurated_all)
        suppressed = len(uncurated_all) - len(canonicals)
        if suppressed:
            print(f"  Suppressed {suppressed} near-duplicate articles from LLM input")
        canonical_ids = {a["id"] for a in canonicals}
        for a in uncurated_all:
            if a["id"] not in canonical_ids:
                articles_by_id[a["id"]]["duplicate_of_canonical"] = True

        # Discovery pass — Llama 4 Maverick filters cybersecurity-irrelevant noise
        # before we spend tokens summarizing it.
        print(f"  Discovery pass over {len(canonicals)} canonicals (Llama 4 Maverick)...")
        try:
            kept, dropped = discovery_pass(canonicals)
        except ProjectError as e:
            print(f"\nABORTING: Unrecoverable project error during discovery — {e}", file=sys.stderr)
            sys.exit(1)
        print(f"  Discovery kept {len(kept)}, dropped {len(dropped)} as irrelevant")
        # Merge discovery scores back into the main article store for audit.
        for a in kept + dropped:
            target = articles_by_id.get(a["id"])
            if target is not None:
                target["discovery_score"] = a.get("discovery_score")
                target["discovery_reason"] = a.get("discovery_reason")
                target["security_topic"] = a.get("security_topic")
        for a in dropped:
            articles_by_id[a["id"]]["dropped_by_discovery"] = True
        uncurated = kept
    else:
        uncurated = []

    print(f"  Already curated: {len(already_curated)}, need curation: {len(uncurated)}")

    if not uncurated:
        print("All articles already curated, nothing to do.")
        enriched = list(articles_by_id.values())
        enriched.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)
        with open(curated_file, "w") as f:
            json.dump(enriched, f, indent=2)
        print(f"Saved {len(enriched)} curated articles to {curated_file.name}")
        return

    chunks = chunk_articles(uncurated)
    all_summaries = []
    failed_batches = 0

    for i, chunk in enumerate(chunks):
        print(f"\nProcessing batch {i + 1}/{len(chunks)} ({len(chunk)} articles)...")

        input_data = [{
            "id": a["id"],
            "title": a["title"],
            "raw_summary": a.get("summary_raw", "")[:500],
            "source": a["source"],
            "url": a["url"],
        } for a in chunk]

        prompt = SUMMARIZE_PROMPT + json.dumps(input_data, indent=2)

        try:
            result = generate_json(prompt, backend="groq", temperature=0.3)
        except ProjectError as e:
            print(f"\nABORTING: Unrecoverable project error — {e}", file=sys.stderr)
            print("Fix your API key / project, then re-run.", file=sys.stderr)
            sys.exit(1)

        if result:
            if isinstance(result, dict) and "articles" in result:
                result = result["articles"]
            if isinstance(result, list):
                all_summaries.extend(result)
                print(f"  Got {len(result)} summaries")
            else:
                print(f"  [WARN] Unexpected response format, skipping batch")
                failed_batches += 1
        else:
            failed_batches += 1

        if i < len(chunks) - 1:
            throttle()

    if failed_batches == len(chunks):
        print("ERROR: All batches failed. Check API key and quota.", file=sys.stderr)
        sys.exit(1)

    for summary in all_summaries:
        aid = summary.get("id")
        if aid and aid in articles_by_id:
            articles_by_id[aid]["title"] = summary.get("title", articles_by_id[aid]["title"])
            articles_by_id[aid]["summary"] = summary.get("summary", "")
            articles_by_id[aid]["relevance_score"] = summary.get("relevance_score", 5)
            articles_by_id[aid]["tags"] = summary.get("tags", [])

    enriched = list(articles_by_id.values())
    enriched.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)

    with open(curated_file, "w") as f:
        json.dump(enriched, f, indent=2)

    print(f"\nSaved {len(enriched)} curated articles to {curated_file.name}")
    print(f"Batches: {len(chunks) - failed_batches} succeeded, {failed_batches} failed")
    print(f"Top 5 by relevance:")
    for a in enriched[:5]:
        print(f"  [{a.get('relevance_score', '?')}] {a.get('title', 'Untitled')}")


if __name__ == "__main__":
    main()

"""
Discovery pass — Llama 4 Maverick (or whatever is at the head of
PREFERRED_GROQ_MODELS) reads every canonical article and scores it for actual
cybersecurity relevance. Articles below the relevance threshold are dropped
before the summarizer ever sees them.

This is the "200B+ model finds the real cybersecurity news" stage. It
de-noises the scraped feed — feeds like Ars Technica or Security Now mix
true security stories with general tech, gadget reviews, podcast banter,
etc. Pre-filtering here cuts the summarizer's token spend and improves
the signal/noise of the final tournament.
"""

import json
import os
import sys
from pathlib import Path

from llm_client import ProjectError, generate_json, throttle
from edition import RAW_DIR, get_edition

# Articles scoring below this are dropped. Override via env var.
MIN_RELEVANCE = float(os.environ.get("DISCOVERY_MIN_RELEVANCE", "5"))
BATCH_SIZE = int(os.environ.get("DISCOVERY_BATCH_SIZE", "15"))

DISCOVERY_PROMPT = """You are a senior cybersecurity analyst. I will give you a batch of headlines and short summaries scraped from news feeds. Score each one on how much it belongs in a cybersecurity newsletter aimed at security professionals and CISOs.

A 10 is a major breach, zero-day, nation-state campaign, critical CVE actively exploited, infrastructure compromise, or a story directly touching 5G / indoor cells / NMS / web-app management platforms.

A 7-9 is a meaningful security story: new vulnerability disclosures, ransomware activity, threat-actor research, significant policy or regulation, defensive tooling that matters.

A 4-6 is loosely related: general tech with a security angle, opinion pieces on cyber topics, podcast episodes that touch on security among other things.

A 1-3 is noise that should NOT be in the newsletter: pure consumer-tech news, product launches with no security relevance, gadget reviews, podcast banter that doesn't focus on a security story, generic AI news, unrelated business news.

For each article, return:
- id (keep the exact original)
- score (number 1-10)
- reason (one short clause — why this score)
- security_topic (string: one of "breach", "vulnerability", "ransomware", "nation-state", "policy", "research", "tooling", "5G", "indoor-cells", "NMS", "webapp-mgmt", "ai-security", "supply-chain", "other", or "none" if score < 4)

Respond with a single JSON object: { "articles": [ ... ] }

Articles:

"""


def chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def discover(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Returns (kept, dropped). Kept articles get a `discovery_score`,
    `discovery_reason`, and `security_topic` field merged in.
    """
    if not articles:
        return [], []

    by_id = {a["id"]: a for a in articles}
    decisions: dict[str, dict] = {}

    for batch in chunks(articles, BATCH_SIZE):
        payload = [{
            "id": a["id"],
            "title": a.get("title", ""),
            "source": a.get("source", ""),
            "raw_summary": (a.get("summary_raw") or a.get("summary") or "")[:400],
        } for a in batch]

        prompt = DISCOVERY_PROMPT + json.dumps(payload, indent=2)
        result = generate_json(prompt, backend="groq", temperature=0.2)
        if not result:
            print(f"  [discover] batch failed, keeping all {len(batch)} articles by default", flush=True)
            for a in batch:
                decisions[a["id"]] = {"score": MIN_RELEVANCE, "reason": "discovery-failed-keep", "security_topic": "other"}
            continue
        if isinstance(result, dict) and "articles" in result:
            result = result["articles"]
        if not isinstance(result, list):
            print(f"  [discover] unexpected payload shape, keeping batch", flush=True)
            for a in batch:
                decisions[a["id"]] = {"score": MIN_RELEVANCE, "reason": "discovery-bad-shape-keep", "security_topic": "other"}
            continue

        for entry in result:
            aid = entry.get("id")
            if aid in by_id:
                decisions[aid] = {
                    "score": float(entry.get("score", MIN_RELEVANCE)),
                    "reason": str(entry.get("reason", ""))[:200],
                    "security_topic": str(entry.get("security_topic", "other"))[:40],
                }

        throttle(extra_delay=2)

    kept, dropped = [], []
    for a in articles:
        d = decisions.get(a["id"], {"score": MIN_RELEVANCE, "reason": "no-decision-keep", "security_topic": "other"})
        a["discovery_score"] = d["score"]
        a["discovery_reason"] = d["reason"]
        a["security_topic"] = d["security_topic"]
        if d["score"] >= MIN_RELEVANCE:
            kept.append(a)
        else:
            dropped.append(a)

    return kept, dropped


def main():
    """CLI usage: python discover.py [<input.json>]"""
    if len(sys.argv) > 1:
        in_path = Path(sys.argv[1])
    else:
        _, edition = get_edition()
        in_path = RAW_DIR / f"{edition}-cumulative.json"

    if not in_path.exists():
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    with open(in_path) as f:
        articles = json.load(f)

    print(f"Discovery pass over {len(articles)} articles (min score {MIN_RELEVANCE})...")
    try:
        kept, dropped = discover(articles)
    except ProjectError as e:
        print(f"ABORT: project-level error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Kept:    {len(kept)}")
    print(f"  Dropped: {len(dropped)}")
    out_path = in_path.with_name(in_path.stem + "-discovered.json")
    with open(out_path, "w") as f:
        json.dump({"kept": kept, "dropped": dropped}, f, indent=2)
    print(f"  Saved decisions to {out_path}")


if __name__ == "__main__":
    main()

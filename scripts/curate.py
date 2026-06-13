"""
Saturday curator.
Reads cumulative raw articles, sends them to the LLM for summarization
and categorization, saves the enriched dataset.

Resumable: reads/writes checkpoint state so quota exhaustion mid-run
produces a partial result that the next sweeper continues from.
"""

import json
import sys
from pathlib import Path

from llm_client import ProjectError, QuotaExhausted, generate_json, throttle
from edition import RAW_DIR, get_edition
from dedupe import dedupe_articles
from discover import discover as discovery_pass
from state import (
    load_state, save_state, get_stage_status, set_stage_status,
    get_done_set, add_done,
)

SUMMARIZE_PROMPT = """You are a senior cybersecurity analyst and newsletter editor. I will give you a batch of raw articles scraped from security news sources this week.

For each article, extract structured intelligence — not a generic summary. Think like a sysadmin or security engineer reading this before their Monday morning standup.

For each article produce:
1. title — clean, precise headline (fix RSS artifacts, remove clickbait).
2. summary — 2-3 sentences of what happened and why it matters to a practitioner.
3. relevance_score — 1-10:
   - 9-10: actively exploited critical CVE, major breach, nation-state campaign, or a high-impact Linux/OSS supply-chain compromise
   - 7-8: significant vulnerability disclosure, ransomware activity, notable threat-actor research
   - 5-6: vendor advisory, policy change, research with practical implications
   - 3-4: opinion, podcast summary, general AI/tech with minor security angle
   - 1-2: not really security news
4. tags — topic tags from: ransomware, zero-day, linux-distro, oss-package, supply-chain, APT, vulnerability, data-breach, policy, patch-tuesday, ai-security, cloud, identity, network, mobile
5. cve_ids — array of CVE IDs mentioned (e.g. ["CVE-2024-1234"]). Empty array if none.
6. affected_systems — array of affected products/vendors, be specific (e.g. ["Linux kernel 6.x", "OpenSSL 3.3"]).
7. threat_actor — name if attributed (e.g. "Lazarus Group", "Volt Typhoon"). null if unknown.
8. urgency — one of: "patch-now", "this-week", "monitor", "informational".
9. source_quality — one of: "primary" (original research/government advisory), "reporting" (news outlet covering it), "vendor" (vendor blog/advisory).

Focus areas that should score higher:
- Linux distro security: kernel, glibc, OpenSSL, sudo/systemd-class CVEs, distro advisories (USN, DSA, RHSA)
- Open-source supply-chain security: npm/PyPI/crates/Go module malware, backdoored releases, CI/GitHub Actions compromise
- Critical zero-days being actively exploited
- Supply-chain attacks and nation-state campaigns

Respond with a JSON object only, no prose, no markdown fences:
{ "articles": [ ... ] }
"""


def chunk_articles(articles: list[dict], chunk_size: int = 10) -> list[list[dict]]:
    return [articles[i:i + chunk_size] for i in range(0, len(articles), chunk_size)]


def main():
    year, edition = get_edition()
    cumulative_file = RAW_DIR / f"{edition}-cumulative.json"

    if not cumulative_file.exists():
        print(f"ERROR: No cumulative file found at {cumulative_file}", file=sys.stderr)
        sys.exit(1)

    # --- Checkpoint: check if already complete ---
    state = load_state(edition)
    if get_stage_status(state, "curate") == "complete":
        print(f"Curate stage already complete for {edition}, skipping.")
        return

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
        print(f"  Deduping {len(uncurated_all)} uncurated articles by title+summary embedding...")
        canonicals, _ = dedupe_articles(uncurated_all)
        suppressed = len(uncurated_all) - len(canonicals)
        if suppressed:
            print(f"  Suppressed {suppressed} near-duplicate articles from LLM input")
        canonical_ids = {a["id"] for a in canonicals}
        for a in uncurated_all:
            if a["id"] not in canonical_ids:
                articles_by_id[a["id"]]["duplicate_of_canonical"] = True

        # Discovery pass
        print(f"  Discovery pass over {len(canonicals)} canonicals...")
        try:
            kept, dropped = discovery_pass(canonicals)
        except ProjectError as e:
            print(f"\nABORTING: Unrecoverable project error during discovery — {e}", file=sys.stderr)
            sys.exit(1)
        except QuotaExhausted as e:
            print(f"\n  Quota exhausted during discovery ({e}), checkpointing...")
            set_stage_status(state, "curate", "partial")
            save_state(edition, state)
            _save_partial(articles_by_id, curated_file)
            print("PARTIAL: curate checkpointed, will resume on next sweeper")
            return

        print(f"  Discovery kept {len(kept)}, dropped {len(dropped)} as irrelevant")
        for a in kept + dropped:
            target = articles_by_id.get(a["id"])
            if target is not None:
                target["discovery_score"] = a.get("discovery_score")
                target["discovery_reason"] = a.get("discovery_reason")
        for a in dropped:
            articles_by_id[a["id"]]["dropped_by_discovery"] = True
        uncurated = kept
    else:
        uncurated = []

    # Filter out already-done articles from checkpoint
    done_ids = get_done_set(state, "curate")
    uncurated = [a for a in uncurated if a["id"] not in done_ids]

    print(f"  Already curated: {len(already_curated)}, checkpoint done: {len(done_ids)}, need curation: {len(uncurated)}")

    if not uncurated:
        print("All articles already curated, nothing to do.")
        enriched = list(articles_by_id.values())
        enriched.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)
        with open(curated_file, "w") as f:
            json.dump(enriched, f, indent=2)
        set_stage_status(state, "curate", "complete")
        save_state(edition, state)
        print(f"Saved {len(enriched)} curated articles to {curated_file.name}")
        return

    chunks = chunk_articles(uncurated)
    all_summaries = []
    failed_batches = 0
    quota_hit = False

    for i, chunk in enumerate(chunks):
        print(f"\nProcessing batch {i + 1}/{len(chunks)} ({len(chunk)} articles)...")

        input_data = [{
            "id": a["id"],
            "title": a["title"],
            "raw_summary": a.get("summary_raw", "")[:600],
            "source": a["source"],
            "url": a["url"],
            "source_type": a.get("source_quality", "reporting"),
        } for a in chunk]

        prompt = SUMMARIZE_PROMPT + json.dumps(input_data, indent=2)

        try:
            result = generate_json(prompt, task="summarize", temperature=0.3)
        except ProjectError as e:
            print(f"\nABORTING: Unrecoverable project error — {e}", file=sys.stderr)
            sys.exit(1)
        except QuotaExhausted as e:
            print(f"\n  Quota exhausted ({e}), checkpointing...")
            quota_hit = True
            break

        if result:
            if isinstance(result, dict) and "articles" in result:
                result = result["articles"]
            if isinstance(result, list):
                all_summaries.extend(result)
                for entry in result:
                    aid = entry.get("id")
                    if aid:
                        add_done(state, "curate", aid)
                print(f"  Got {len(result)} summaries")
            else:
                print(f"  [WARN] Unexpected response format, skipping batch")
                failed_batches += 1
        else:
            failed_batches += 1

        if i < len(chunks) - 1:
            throttle()

    if not quota_hit and failed_batches == len(chunks) and len(chunks) > 0:
        print("ERROR: All batches failed. Check API key and quota.", file=sys.stderr)
        sys.exit(1)

    # Merge summaries into article store
    for summary in all_summaries:
        aid = summary.get("id")
        if aid and aid in articles_by_id:
            articles_by_id[aid]["title"] = summary.get("title", articles_by_id[aid]["title"])
            articles_by_id[aid]["summary"] = summary.get("summary", "")
            articles_by_id[aid]["relevance_score"] = summary.get("relevance_score", 5)
            articles_by_id[aid]["tags"] = summary.get("tags", [])
            articles_by_id[aid]["cve_ids"] = summary.get("cve_ids", [])
            articles_by_id[aid]["affected_systems"] = summary.get("affected_systems", [])
            articles_by_id[aid]["threat_actor"] = summary.get("threat_actor")
            articles_by_id[aid]["urgency"] = summary.get("urgency", "informational")
            articles_by_id[aid]["source_quality"] = summary.get("source_quality", "reporting")

    enriched = list(articles_by_id.values())
    enriched.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)

    with open(curated_file, "w") as f:
        json.dump(enriched, f, indent=2)

    if quota_hit:
        set_stage_status(state, "curate", "partial")
        save_state(edition, state)
        remaining = len(chunks) - (i if 'i' in dir() else 0)
        print(f"\nPARTIAL: curate checkpointed, ~{remaining} batches remaining")
    else:
        set_stage_status(state, "curate", "complete")
        save_state(edition, state)
        print(f"\nSaved {len(enriched)} curated articles to {curated_file.name}")
        print(f"Batches: {len(chunks) - failed_batches} succeeded, {failed_batches} failed")

    print(f"Top 5 by relevance:")
    for a in enriched[:5]:
        print(f"  [{a.get('relevance_score', '?')}] {a.get('title', 'Untitled')}")


def _save_partial(articles_by_id: dict, curated_file: Path):
    enriched = list(articles_by_id.values())
    enriched.sort(key=lambda a: a.get("relevance_score", 0), reverse=True)
    with open(curated_file, "w") as f:
        json.dump(enriched, f, indent=2)


if __name__ == "__main__":
    main()

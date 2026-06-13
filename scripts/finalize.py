"""
Sunday finalizer.
Reads curated articles, clusters by story, fetches full text for journalism
sources, runs per-cluster editorial synthesis, enforces teaser caps and
grounding gate, generates the final edition JSON and HTML email.

Resumable: checkpoints per-cluster synthesis progress.
"""

import json
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from jinja2 import Template

from llm_client import ProjectError, QuotaExhausted, generate_json
from edition import CONTENT_DIR, RAW_DIR, get_edition, set_edition, date_range_label
from dedupe import dedupe_articles, cluster_id as compute_cluster_id
from state import (
    load_state, save_state, get_stage_status, set_stage_status,
    get_done_clusters, add_done_cluster,
)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
FULLTEXT_MAX_WORDS = int(os.environ.get("FULLTEXT_MAX_WORDS", "1000"))
FULLTEXT_CACHE_FILE = "fulltext-cache.json"

# Teaser word caps (CO §5)
TIER1_MAX_WORDS = int(os.environ.get("TIER1_MAX_WORDS", "60"))
TIER2_MAX_WORDS = int(os.environ.get("TIER2_MAX_WORDS", "40"))

# ---------- Prompts ----------

CLUSTER_SYNTHESIS_PROMPT = """You are the editor of "Cybersecurity Weekly", read by sysadmins, DevOps engineers, and security engineers. Write a SINGLE newsletter entry for the ONE story cluster below. Do not select stories, do not write an intro, do not assign tiers across stories — that happens elsewhere. Your only job is to synthesize this one cluster into one entry.

STORY CLUSTER (all sources covering the same event):
{cluster_json}

Synthesize the best details from ALL source versions. Write with authority and specificity — name vendors, CVEs, threat actors, affected systems. Do NOT hedge with "reportedly" or "according to" — state facts directly.

Write ONE entry with:
- id: use "{canonical_id}"
- title: clean, authoritative headline
- summary: {word_cap} words MAX. Lead with the key fact. Be specific. No hedging.
{tier_instructions}
- sources: array of {{"name": "...", "url": "..."}} from ALL source versions
- url: primary journalism source URL (not advisory)
- publishedDate: earliest from sources
- cve_ids: all CVE IDs from any source
- affected_systems: all affected products
- threat_actor: if attributed, else null

Respond ONLY with this JSON (no extra text):
{{"id":"...","title":"...","summary":"..."{impact_action_fields},"sources":[...],"url":"...","publishedDate":"...","cve_ids":[],"affected_systems":[],"threat_actor":null}}
"""

ASSEMBLY_PROMPT = """You are the editor-in-chief of "Cybersecurity Weekly" — read by sysadmins, DevOps engineers, and security engineers.

Here are this week's synthesized story entries:
{entries_json}

YOUR JOB:
1. ASSIGN each entry a tier:
   - tier 1 (BREAKING): Active exploitation, mass impact, critical CVEs, nation-state campaigns. 1-3/week.
   - tier 2 (FOCUS): Linux distro security, open-source supply-chain security, significant but contained. 2-4/week.
   - tier 3 (NOTABLE): Important but not urgent. The rest.
2. ORDER: tier 1 first, then 2, then 3. Within each tier, most important first.
3. SELECT 8-12 stories total (drop the weakest if more).
4. WRITE week_intro: 2-3 sentences from the editor's perspective on this week's theme.
5. WRITE subject_line: factual, specific, leads with the biggest story.

Respond ONLY with JSON:
{{"subject_line":"...","week_intro":"...","articles":[{{"id":"...","tier":1}},...]}}

The articles array should contain ONLY id and tier for each selected entry.
"""

VERIFY_PROMPT = """You are a deduplication checker. Review these newsletter entries and identify any pairs that cover the SAME real-world event (not just the same topic).

ENTRIES:
{entries_json}

If any two entries are about the same event, return merge pairs. Keep the entry with the higher tier (or the first one if tied). Union their sources arrays.

Respond with JSON:
{{"merge_pairs": [{{"keep_id": "...", "drop_id": "...", "reason": "..."}}]}}

If no duplicates found:
{{"merge_pairs": []}}
"""


# ---------- Full-text fetch ----------

def _load_fulltext_cache(edition: str) -> dict[str, str]:
    cache_path = RAW_DIR / f"{edition}-{FULLTEXT_CACHE_FILE}"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    return {}


def _save_fulltext_cache(edition: str, cache: dict[str, str]):
    cache_path = RAW_DIR / f"{edition}-{FULLTEXT_CACHE_FILE}"
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)


def _fetch_fulltext(url: str) -> str | None:
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        if not text:
            return None
        words = text.split()
        return " ".join(words[:FULLTEXT_MAX_WORDS])
    except Exception as e:
        print(f"    [fulltext] failed for {url[:80]}: {e}", flush=True)
        return None


def fetch_cluster_fulltext(
    cluster: list[dict],
    cache: dict[str, str],
    kinds: dict[str, str],
) -> dict[str, str]:
    texts = {}
    for a in cluster:
        aid = a["id"]
        if aid in cache:
            texts[aid] = cache[aid]
            continue
        source_kind = kinds.get(a.get("source", ""), a.get("source_kind", "journalism"))
        if source_kind != "journalism":
            continue
        url = a.get("url", "")
        if not url:
            continue
        text = _fetch_fulltext(url)
        if text:
            texts[aid] = text
            cache[aid] = text
    return texts


def _load_source_kinds() -> dict[str, str]:
    sources_file = Path(__file__).parent / "sources.json"
    if not sources_file.exists():
        return {}
    with open(sources_file) as f:
        return {s["name"]: s.get("kind", "journalism") for s in json.load(f)}


# ---------- Teaser cap enforcement ----------

def _word_count(text: str) -> int:
    return len(text.split())


def _truncate_at_sentence(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated = " ".join(words[:max_words])
    last_period = truncated.rfind(".")
    last_excl = truncated.rfind("!")
    last_q = truncated.rfind("?")
    boundary = max(last_period, last_excl, last_q)
    if boundary > len(truncated) // 2:
        return truncated[:boundary + 1]
    return truncated + "..."


def enforce_teaser_caps(article: dict) -> bool:
    tier = article.get("tier", 3)
    summary = article.get("summary", "")
    cap = TIER1_MAX_WORDS if tier == 1 else TIER2_MAX_WORDS if tier == 2 else 30
    wc = _word_count(summary)
    if wc <= cap:
        return False
    article["summary"] = _truncate_at_sentence(summary, cap)
    return True


# ---------- Grounding gate ----------

def _strip_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"}
    clean = {k: v for k, v in params.items() if k.lower() not in tracking}
    cleaned = parsed._replace(query=urlencode(clean, doseq=True))
    return urlunparse(cleaned)


def grounding_gate(articles: list[dict], scraped_urls: set[str], scraped_cves: set[str]) -> list[dict]:
    clean_scraped = {_strip_tracking_params(u) for u in scraped_urls}
    passed = []
    stripped = 0
    for a in articles:
        url = a.get("url", "")
        clean_url = _strip_tracking_params(url)
        if clean_url and clean_url not in clean_scraped:
            all_source_urls = {_strip_tracking_params(s.get("url", "")) for s in a.get("sources", [])}
            if not (all_source_urls & clean_scraped):
                print(f"  [grounding] stripped foreign URL: {url[:80]}", flush=True)
                stripped += 1
                continue
        bad_cves = [c for c in a.get("cve_ids", []) if c.upper() not in scraped_cves]
        if bad_cves:
            print(f"  [grounding] stripped hallucinated CVEs from {a.get('id','?')}: {bad_cves}", flush=True)
            a["cve_ids"] = [c for c in a["cve_ids"] if c.upper() in scraped_cves]
        passed.append(a)

    total = len(articles)
    if total > 0 and stripped / total > 0.5:
        print(f"ERROR: grounding gate stripped {stripped}/{total} entries (>50%)", file=sys.stderr)
        sys.exit(1)
    if stripped:
        print(f"  [grounding] {stripped} entries stripped, {len(passed)} passed")
    return passed


# ---------- Email generation ----------

def generate_email_html(content: dict) -> str:
    template_path = TEMPLATES_DIR / "email.html"
    with open(template_path) as f:
        template = Template(f.read())

    site_url = os.environ.get("SITE_URL", "https://vishakadatta.github.io/cybersecurity-weekly/")
    unsubscribe_url = os.environ.get("UNSUBSCRIBE_URL", "{{ params.unsubscribe }}")

    return template.render(
        subject_line=content["subjectLine"],
        week_intro=content.get("weekIntro", ""),
        edition_label=content.get("editionLabel", content["edition"]),
        year=content["year"],
        articles=content["articles"],
        site_url=site_url,
        unsubscribe_url=unsubscribe_url,
    )


# ---------- Main ----------

def main():
    year, edition = get_edition()
    print(f"Edition: {edition} ({date_range_label(edition)})")

    # --- Checkpoint: check if already complete ---
    state = load_state(edition)
    if get_stage_status(state, "finalize") == "complete":
        print(f"Finalize stage already complete for {edition}, skipping.")
        return

    # Gate: curate must be complete
    if get_stage_status(state, "curate") != "complete":
        print(f"WARNING: curate stage is '{get_stage_status(state, 'curate')}', not complete.")
        print("Proceeding with whatever curated data is available...")

    curated_file = RAW_DIR / f"{edition}-curated.json"
    if not curated_file.exists():
        print(f"ERROR: No curated file found at {curated_file}", file=sys.stderr)
        sys.exit(1)

    with open(curated_file) as f:
        articles = json.load(f)

    print(f"Loaded {len(articles)} curated articles")

    # Build scraped URL/CVE sets for grounding gate
    scraped_urls: set[str] = set()
    scraped_cves: set[str] = set()
    for a in articles:
        if a.get("url"):
            scraped_urls.add(a["url"])
        for cve in a.get("cve_ids_scraped", []) + a.get("cve_ids", []):
            scraped_cves.add(cve.upper())

    # Cluster articles by story
    print("Clustering by story for cross-source synthesis...")
    canonicals, clusters = dedupe_articles(articles, threshold=0.72)
    print(f"  {len(articles)} articles → {len(canonicals)} story clusters")

    # Sort clusters by best relevance and take top 35
    scored_clusters = []
    for canonical, cluster in zip(canonicals, clusters):
        best_score = max(a.get("relevance_score", 0) for a in cluster)
        cid = compute_cluster_id(cluster)
        scored_clusters.append((best_score, canonical, cluster, cid))
    scored_clusters.sort(key=lambda x: -x[0])
    top_clusters = scored_clusters[:35]

    # Load source kinds for full-text fetch
    kinds = _load_source_kinds()

    # Full-text fetch for journalism members
    print(f"Fetching full text for journalism sources...")
    ft_cache = _load_fulltext_cache(edition)
    ft_fetched = 0
    for _, _, cluster, _ in top_clusters:
        new_texts = fetch_cluster_fulltext(cluster, ft_cache, kinds)
        ft_fetched += len(new_texts)
    _save_fulltext_cache(edition, ft_cache)
    print(f"  {ft_fetched} articles enriched with full text ({len(ft_cache)} cached total)")

    # Per-cluster synthesis with checkpoint
    done_clusters = get_done_clusters(state)
    synthesis_results: dict[str, dict] = {}

    # Load any previously synthesized entries from partial runs
    partial_file = RAW_DIR / f"{edition}-synthesis-partial.json"
    if partial_file.exists():
        with open(partial_file) as f:
            synthesis_results = json.load(f)

    quota_hit = False
    print(f"Running per-cluster editorial synthesis ({len(top_clusters)} clusters, {len(done_clusters)} already done)...")

    for i, (score, canonical, cluster, cid) in enumerate(top_clusters):
        if cid in done_clusters and cid in synthesis_results:
            continue

        # Build cluster context with full text
        sources_for_prompt = []
        for a in cluster:
            entry = {
                "source": a.get("source", ""),
                "source_kind": kinds.get(a.get("source", ""), a.get("source_kind", "journalism")),
                "title": a.get("title", ""),
                "summary": a.get("summary", a.get("summary_raw", ""))[:400],
                "url": a.get("url", ""),
                "relevance_score": a.get("relevance_score", 5),
                "publishedDate": a.get("publishedDate", ""),
            }
            if a["id"] in ft_cache:
                entry["full_text"] = ft_cache[a["id"]][:2000]
            sources_for_prompt.append(entry)

        cve_ids = list({c for a in cluster for c in a.get("cve_ids", []) + a.get("cve_ids_scraped", [])})
        affected = list({s for a in cluster for s in a.get("affected_systems", [])})
        actors = list({a["threat_actor"] for a in cluster if a.get("threat_actor")})

        cluster_data = {
            "canonical_id": canonical["id"],
            "sources": sources_for_prompt,
            "cve_ids": cve_ids,
            "affected_systems": affected,
            "threat_actors": actors,
        }

        # Determine tier hint for word cap
        tier_instructions = (
            '- impact: 1-2 sentences on what this means for security teams\n'
            '- action: 1 sentence on what teams should do'
        )
        impact_action = ',"impact":"...","action":"..."'
        word_cap = TIER1_MAX_WORDS

        prompt = CLUSTER_SYNTHESIS_PROMPT.format(
            cluster_json=json.dumps(cluster_data, indent=2),
            canonical_id=canonical["id"],
            word_cap=word_cap,
            tier_instructions=tier_instructions,
            impact_action_fields=impact_action,
        )

        try:
            result = generate_json(prompt, task="editorial", temperature=0.5)
        except QuotaExhausted as e:
            print(f"\n  Quota exhausted at cluster {i+1}/{len(top_clusters)} ({e})")
            quota_hit = True
            break
        except ProjectError as e:
            print(f"\nABORTING: Unrecoverable error — {e}", file=sys.stderr)
            sys.exit(1)

        if result:
            synthesis_results[cid] = result
            add_done_cluster(state, cid)
            print(f"  [{i+1}/{len(top_clusters)}] {result.get('title', '?')[:60]}")
        else:
            print(f"  [{i+1}/{len(top_clusters)}] synthesis failed, skipping")

    # Save partial synthesis results
    with open(partial_file, "w") as f:
        json.dump(synthesis_results, f, indent=2)

    if quota_hit:
        set_stage_status(state, "finalize", "partial")
        save_state(edition, state)
        remaining = len(top_clusters) - len(get_done_clusters(state))
        print(f"PARTIAL: finalize checkpointed, {remaining} clusters remaining")
        return

    # --- Assembly call: tier assignment, ordering, week_intro, subject ---
    entries_for_assembly = list(synthesis_results.values())
    print(f"\nAssembling {len(entries_for_assembly)} entries...")

    assembly_prompt = ASSEMBLY_PROMPT.format(
        entries_json=json.dumps(entries_for_assembly, indent=2)
    )

    try:
        assembly = generate_json(assembly_prompt, task="editorial", temperature=0.4)
    except (QuotaExhausted, ProjectError) as e:
        print(f"Assembly failed ({e}), checkpointing...")
        set_stage_status(state, "finalize", "partial")
        save_state(edition, state)
        return

    if not assembly:
        print("ERROR: Assembly LLM call failed", file=sys.stderr)
        sys.exit(1)

    # Merge tier assignments back into synthesis results
    tier_map = {a["id"]: a["tier"] for a in assembly.get("articles", [])}
    selected_ids = [a["id"] for a in assembly.get("articles", [])]

    final_articles = []
    for aid in selected_ids:
        for cid, entry in synthesis_results.items():
            if entry.get("id") == aid:
                entry["tier"] = tier_map.get(aid, 3)
                final_articles.append(entry)
                break

    # --- Enforce teaser caps ---
    retry_needed = []
    for a in final_articles:
        if enforce_teaser_caps(a):
            retry_needed.append(a)

    if retry_needed:
        print(f"  [caps] truncated {len(retry_needed)} over-long summaries")

    # --- L3 merge-verify ---
    print("Running L3 merge-verify...")
    verify_entries = [{"id": a["id"], "title": a["title"], "summary": a["summary"][:100]} for a in final_articles]
    try:
        verify_result = generate_json(
            VERIFY_PROMPT.format(entries_json=json.dumps(verify_entries, indent=2)),
            task="verify",
            temperature=0.2,
        )
    except (QuotaExhausted, ProjectError):
        verify_result = None

    if verify_result and verify_result.get("merge_pairs"):
        for pair in verify_result["merge_pairs"]:
            keep_id = pair.get("keep_id")
            drop_id = pair.get("drop_id")
            if not keep_id or not drop_id:
                continue
            keep_art = next((a for a in final_articles if a["id"] == keep_id), None)
            drop_art = next((a for a in final_articles if a["id"] == drop_id), None)
            if keep_art and drop_art:
                # Union sources
                keep_sources = {s["url"] for s in keep_art.get("sources", [])}
                for s in drop_art.get("sources", []):
                    if s["url"] not in keep_sources:
                        keep_art.setdefault("sources", []).append(s)
                # Keep higher tier
                keep_art["tier"] = min(keep_art.get("tier", 3), drop_art.get("tier", 3))
                final_articles = [a for a in final_articles if a["id"] != drop_id]
                print(f"  [L3] merged {drop_id} into {keep_id}: {pair.get('reason', '')}")

    # --- Grounding gate ---
    print("Running grounding gate...")
    final_articles = grounding_gate(final_articles, scraped_urls, scraped_cves)

    # --- Hard dedupe on ID (safety net) ---
    seen_ids: set[str] = set()
    deduped = []
    for a in final_articles:
        aid = a.get("id", "")
        if aid and aid in seen_ids:
            print(f"  [dedup] dropped repeated id={aid}")
            continue
        seen_ids.add(aid)
        deduped.append(a)
    final_articles = deduped

    # --- Build final content ---
    content = {
        "edition": edition,
        "year": year,
        "editionLabel": date_range_label(edition),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "subjectLine": assembly.get("subject_line", "Cybersecurity Weekly"),
        "weekIntro": assembly.get("week_intro", ""),
        "articles": final_articles,
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

    # Mark complete
    set_stage_status(state, "finalize", "complete")
    save_state(edition, state)

    # Cleanup partial file
    partial_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

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

from llm_client import ProjectError, QuotaExhausted, generate_json, throttle
from edition import RAW_DIR, get_edition

# Articles scoring below this are dropped. Override via env var.
MIN_RELEVANCE = float(os.environ.get("DISCOVERY_MIN_RELEVANCE", "5"))
BATCH_SIZE = int(os.environ.get("DISCOVERY_BATCH_SIZE", "15"))

DISCOVERY_PROMPT = """You are a senior cybersecurity analyst curating a weekly newsletter for sysadmins, DevOps engineers, and security engineers. Its focus is Linux distribution security and open-source / supply-chain security.

I will give you a batch of headlines and short summaries scraped from news feeds. Score each on a 1-10 scale for how much it belongs in THIS newsletter. Two things drive the score, and you must weigh both:

  SEVERITY  - how serious the security event is (exploitation, criticality, scope).
  FOCUS-FIT - how directly it touches our beat:
              * Linux distro security: kernel, glibc, OpenSSL, sudo, systemd, and similar core-component CVEs; distro security advisories (USN/DSA/RHSA).
              * Open-source & supply-chain security: malicious or backdoored npm/PyPI/crates/Go packages; compromised maintainer accounts or releases; build-system / CI / GitHub Actions compromise.

Scoring anchors:

  10  Both high-severity AND in-focus. Actively-exploited Linux kernel or core-library CVE, an xz-style backdoor, a compromise of a widely-used open-source package, a poisoned popular CI action.

  7-9 Either a strong in-focus story that is not yet critical (a notable distro advisory, a newly disclosed OSS vulnerability, supply-chain research), OR a broadly important general security story that is OUT of focus (a major corporate breach, a Windows-only zero-day, a large ransomware campaign). General-but-important news caps at 8 - it never reaches 10, because it is not our beat.

  4-6  Moderate relevance: routine vulnerability disclosures, smaller incidents, security tooling, policy/regulation with some practitioner impact.

  1-3  Marginal or off-topic: product marketing, opinion with no concrete security event, consumer-only stories, vendor PR.

For EACH article return: the id, an integer score 1-10, and a short reason (one sentence) stating the severity and the focus-fit you judged. The reason is mandatory - it is your justification, not optional commentary.

Return ONLY a JSON array, no prose, no markdown fences:
[{"id": "<id>", "score": <int>, "reason": "<one sentence>"}]

Examples:

Input:
  id=a1  "USN-7321-1: Linux kernel vulnerabilities" - Several flaws in the Linux kernel could allow local privilege escalation; updates available for Ubuntu 24.04.
  id=b2  "Retailer discloses breach affecting 4M customers" - Names and emails exposed via a misconfigured cloud bucket.
  id=c3  "New JetBrains IDE theme released" - Dark mode refresh and UI tweaks for the latest version.

Output:
[{"id": "a1", "score": 10, "reason": "High severity local privilege escalation in the Linux kernel with a live distro advisory - squarely in focus."},
 {"id": "b2", "score": 7, "reason": "Serious breach and broadly important, but a generic cloud-misconfig incident outside our Linux/OSS focus, so capped below 10."},
 {"id": "c3", "score": 2, "reason": "Low severity product UI news with no security event and no focus relevance."}]

Now score this batch:
"""


def chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def discover(articles: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Returns (kept, dropped). Kept articles get `discovery_score`
    and `discovery_reason` fields merged in.
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
        result = generate_json(prompt, task="discovery", temperature=0.2)
        if not result:
            print(f"  [discover] batch failed, keeping all {len(batch)} articles by default", flush=True)
            for a in batch:
                decisions[a["id"]] = {"score": MIN_RELEVANCE, "reason": "discovery-failed-keep"}
            continue
        if isinstance(result, dict) and "articles" in result:
            result = result["articles"]
        if not isinstance(result, list):
            print(f"  [discover] unexpected payload shape, keeping batch", flush=True)
            for a in batch:
                decisions[a["id"]] = {"score": MIN_RELEVANCE, "reason": "discovery-bad-shape-keep"}
            continue

        for entry in result:
            aid = entry.get("id")
            if aid in by_id:
                decisions[aid] = {
                    "score": float(entry.get("score", MIN_RELEVANCE)),
                    "reason": str(entry.get("reason", ""))[:200],
                }

        throttle(extra_delay=2)

    kept, dropped = [], []
    for a in articles:
        d = decisions.get(a["id"], {"score": MIN_RELEVANCE, "reason": "no-decision-keep"})
        a["discovery_score"] = d["score"]
        a["discovery_reason"] = d["reason"]
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

"""
Multi-layer embedding + CVE-ID dedupe.

L2a: exact CVE-ID join — articles sharing any CVE merge into one cluster.
L2b: cosine-similarity clustering on title + first 500 chars of summary_raw.

Canonical selection: highest-weight journalism member wins; if cluster is
advisory-only, highest-weight advisory wins.  Tiebreak: earliest published.

Cluster ID = SHA-256 of sorted member article IDs (stable across re-runs).
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

DEFAULT_THRESHOLD = 0.78
SOURCES_FILE = Path(__file__).parent / "sources.json"

_model = None


def _get_model():
    global _model
    if _model is not None:
        return _model
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def _load_source_weights() -> dict[str, float]:
    weights: dict[str, float] = {}
    if not SOURCES_FILE.exists():
        return weights
    with open(SOURCES_FILE) as f:
        for src in json.load(f):
            weights[src["name"]] = float(src.get("weight", 1.0))
    return weights


def _load_source_kinds() -> dict[str, str]:
    kinds: dict[str, str] = {}
    if not SOURCES_FILE.exists():
        return kinds
    with open(SOURCES_FILE) as f:
        for src in json.load(f):
            kinds[src["name"]] = src.get("kind", "journalism")
    return kinds


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def clusters(self) -> list[list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            groups.setdefault(self.find(i), []).append(i)
        return list(groups.values())


def cluster_id(articles: list[dict]) -> str:
    member_ids = sorted(a["id"] for a in articles)
    raw = ",".join(member_ids).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _canonical_index(
    cluster: list[int],
    articles: list[dict],
    weights: dict[str, float],
    kinds: dict[str, str],
) -> int:
    def sort_key(idx: int):
        a = articles[idx]
        source = a.get("source", "")
        kind = kinds.get(source, a.get("source_kind", "journalism"))
        w = weights.get(source, 1.0)
        # journalism=0 sorts before advisory=1 (we want journalism first)
        kind_rank = 0 if kind == "journalism" else 1
        pub = a.get("publishedDate") or ""
        return (kind_rank, -w, pub)
    return sorted(cluster, key=sort_key)[0]


def dedupe_articles(
    articles: list[dict],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[list[dict], list[list[dict]]]:
    """
    Returns (canonical_articles, clusters_of_members).
    Each canonical gets `dupe_count`, `dupe_sources`, and `cluster_id`.
    """
    if not articles:
        return [], []

    n = len(articles)
    uf = _UnionFind(n)

    # --- L2a: CVE-ID exact-match join ---
    cve_to_indices: dict[str, list[int]] = {}
    for i, a in enumerate(articles):
        for cve in a.get("cve_ids_scraped", []) + a.get("cve_ids", []):
            cve_upper = cve.upper()
            cve_to_indices.setdefault(cve_upper, []).append(i)
    for indices in cve_to_indices.values():
        for j in range(1, len(indices)):
            uf.union(indices[0], indices[j])

    # --- L2b: embedding cosine similarity ---
    texts = []
    for a in articles:
        title = a.get("title", "")
        summary = (a.get("summary_raw") or a.get("summary") or "")[:500]
        texts.append(f"{title} {summary}" if summary else title)

    model = _get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    sims = embeddings @ embeddings.T

    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= threshold:
                uf.union(i, j)

    # --- Build output ---
    clusters = uf.clusters()
    weights = _load_source_weights()
    kinds = _load_source_kinds()

    canonicals = []
    cluster_groups = []
    for cluster_indices in clusters:
        members = [articles[i] for i in cluster_indices]
        cid = cluster_id(members)

        if len(cluster_indices) == 1:
            a = dict(articles[cluster_indices[0]])
            a["cluster_id"] = cid
            canonicals.append(a)
            cluster_groups.append(members)
            continue

        canonical_idx = _canonical_index(cluster_indices, articles, weights, kinds)
        canonical = dict(articles[canonical_idx])
        canonical["dupe_count"] = len(members)
        canonical["dupe_sources"] = sorted({a.get("source", "") for a in members})
        canonical["cluster_id"] = cid
        canonicals.append(canonical)
        cluster_groups.append(members)

    return canonicals, cluster_groups


def main():
    if len(sys.argv) < 2:
        print("Usage: python dedupe.py <input.json> [threshold]", file=sys.stderr)
        sys.exit(1)
    in_path = Path(sys.argv[1])
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_THRESHOLD
    with open(in_path) as f:
        articles = json.load(f)
    canonicals, clusters = dedupe_articles(articles, threshold=threshold)
    print(f"Input: {len(articles)} articles -> {len(canonicals)} canonical (suppressed {len(articles) - len(canonicals)})")
    multi = [c for c in clusters if len(c) > 1]
    print(f"Multi-source clusters: {len(multi)}")
    for c in multi[:10]:
        titles = [a.get("title", "")[:80] for a in c]
        print(f"  - {len(c)}x: {titles[0]}")
        for t in titles[1:]:
            print(f"      = {t}")


if __name__ == "__main__":
    main()

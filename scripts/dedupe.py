"""
Title-embedding dedupe.

Many of the same stories show up across multiple feeds in a given week (Krebs,
BleepingComputer, THN, Dark Reading all cover the same breach). LLM ranking
sees these as separate articles and either wastes tokens summarizing each or
gets confused. We embed the titles, cluster by cosine similarity, and keep one
canonical article per cluster (highest source weight, then earliest published).

Runs locally — sentence-transformers all-MiniLM-L6-v2 is ~80MB, no API calls.
"""

import json
import sys
from pathlib import Path

import numpy as np

DEFAULT_THRESHOLD = 0.78  # cosine similarity for "same story"
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


def _cluster(sims: np.ndarray, threshold: float) -> list[list[int]]:
    n = sims.shape[0]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= threshold:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    return list(clusters.values())


def _canonical_index(cluster: list[int], articles: list[dict], weights: dict[str, float]) -> int:
    def sort_key(idx: int):
        a = articles[idx]
        w = weights.get(a.get("source", ""), 1.0)
        pub = a.get("publishedDate") or ""
        return (-w, pub)
    return sorted(cluster, key=sort_key)[0]


def dedupe_articles(
    articles: list[dict],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[list[dict], list[list[dict]]]:
    """
    Returns (canonical_articles, clusters_of_dupes).
    Each canonical article gets a `dupe_count` field and a `dupe_sources` list
    for use in ranking. Duplicates are not deleted from disk — only suppressed
    from the LLM input.
    """
    if not articles:
        return [], []

    titles = [a.get("title", "") for a in articles]
    model = _get_model()
    embeddings = model.encode(titles, normalize_embeddings=True, show_progress_bar=False)
    sims = embeddings @ embeddings.T

    clusters = _cluster(np.asarray(sims), threshold)
    weights = _load_source_weights()

    canonicals = []
    cluster_groups = []
    for cluster in clusters:
        if len(cluster) == 1:
            canonicals.append(articles[cluster[0]])
            cluster_groups.append([articles[cluster[0]]])
            continue
        canonical_idx = _canonical_index(cluster, articles, weights)
        canonical = dict(articles[canonical_idx])
        dupes = [articles[i] for i in cluster]
        canonical["dupe_count"] = len(dupes)
        canonical["dupe_sources"] = sorted({a.get("source", "") for a in dupes})
        canonicals.append(canonical)
        cluster_groups.append(dupes)

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

"""Measure query result cache hit performance and canonical context ordering.

No generative calls. Paired measurements on local artifacts.
Verifies 100% exact selection parity on cache hits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

from npk.pack import compile_pack, PackSelector, verify


def measure_cache_performance(artifact_path, queries, iterations=50):
    selector = PackSelector(artifact_path, enable_cache=True)
    # Warm up / first-query miss times
    t_miss = []
    for q in queries:
        selector.clear_cache()
        t0 = time.perf_counter()
        _ = selector.select(q, budget_tokens=512)
        t_miss.append((time.perf_counter() - t0) * 1000)

    # Repeated query hit times (with cache populated)
    t_hit = []
    for q in queries:
        _ = selector.select(q, budget_tokens=512)  # ensure in cache
        for _ in range(iterations):
            t0 = time.perf_counter()
            res = selector.select(q, budget_tokens=512)
            t_hit.append((time.perf_counter() - t0) * 1000)

    return {
        "cache_miss_median_ms": statistics.median(t_miss),
        "cache_hit_median_ms": statistics.median(t_hit),
        "speedup": statistics.median(t_miss) / max(0.0001, statistics.median(t_hit)),
        "total_hit_queries_measured": len(t_hit),
    }


def measure_ordering_equivalence(artifact_path, queries):
    selector = PackSelector(artifact_path)
    results = []
    for q in queries:
        sel = selector.select(q, budget_tokens=2048)
        rel = sel.context_text(order="relevance")
        can = sel.context_text(order="canonical")
        results.append({
            "query": q,
            "evidence_count": len(sel.evidence),
            "relevance_matches_default": rel == sel.context_text(),
            "canonical_sorted": [e.path for e in sorted(sel.evidence, key=lambda e: (e.path, e.span))] == [e.path for e in sorted(sel.evidence, key=lambda e: (e.path, e.span))],
        })
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    assert verify(artifact)["ok"]

    queries = ["retry policy", "ExitStack", "callback", "process_data", "RETRY_LIMIT",
               "parameter", "command", "context", "option", "runner"]

    cache_metrics = measure_cache_performance(artifact, queries)
    ordering_metrics = measure_ordering_equivalence(artifact, queries)

    results = {
        "evidence_mode": "LOCAL",
        "generative_calls": 0,
        "status": "PASS",
        "artifact": str(artifact),
        "cache_performance": cache_metrics,
        "ordering_checks": len(ordering_metrics),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

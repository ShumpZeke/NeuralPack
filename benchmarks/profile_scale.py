"""Scale-dependent optimizer overhead, measured per stage.

The audited profiler reported "sub-millisecond planning overhead" from a run on a
**710-token** context and did not record the context size next to the number. At
100K tokens the real figure is roughly 140x larger.

This profiler always reports the context size alongside the timing, sweeps
several magnitudes, and breaks the total into stages so the scaling behaviour of
each is visible. 128 ms against a multi-second closed-model call is a perfectly
acceptable overhead -- the problem was never the number, it was reporting a
700-token measurement as if it generalised.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from benchmarks.tasks_hard import real_corpus_blocks
from npk.context.analyzer import ContextAnalyzer, estimate_tokens
from npk.context.bm25 import BM25Scorer
from npk.context.embedding import get_backend
from npk.context.graph_slicer import ProgramGraphSlicer
from npk.context.info_gain import InformationGainSelector
from npk.context.retrieval import CodeContextRetriever
from npk.planner import ContextExecutionPlanner

QUERY = "What is the configured connection pool size for the billing service?"
SIZES = (2_000, 25_000, 50_000, 100_000)


def _time(fn, repeats: int = 3) -> float:
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def profile_size(target_tokens: int, repeats: int = 3, with_embeddings: bool = True) -> Dict[str, Any]:
    blocks_src = real_corpus_blocks(target_tokens, seed=7)
    context = "\n\n".join(blocks_src)
    actual = estimate_tokens(context)
    messages = [
        {"role": "system", "content": "You are a precise technical AI."},
        {"role": "user", "content": f"{context}\n\nQUESTION: {QUERY}"},
    ]

    retriever = CodeContextRetriever()
    blocks = retriever.parse_blocks(context)
    slicer = ProgramGraphSlicer()
    edges, _ = slicer.build_dependency_graph(blocks)
    texts = [b["text"] for b in blocks]

    stages: Dict[str, float] = {}
    stages["parse_blocks"] = _time(lambda: retriever.parse_blocks(context), repeats)
    stages["analyze"] = _time(lambda: ContextAnalyzer().analyze_messages(messages), repeats)
    stages["build_graph"] = _time(lambda: slicer.build_dependency_graph(blocks), repeats)

    def _bm25():
        scorer = BM25Scorer(texts)
        for i in range(len(texts)):
            scorer.score(QUERY, i)
    stages["bm25_score_all"] = _time(_bm25, repeats)

    if with_embeddings and get_backend().available():
        # Uncached: clear between runs so this is honest cold-path cost.
        def _embed():
            from npk.context.embedding import LocalEmbeddingBackend
            LocalEmbeddingBackend._cache.clear()
            get_backend().score_blocks(texts, QUERY)
        stages["embed_score_all_cold"] = _time(_embed, max(1, repeats - 1))
        stages["embed_score_all_cached"] = _time(
            lambda: get_backend().score_blocks(texts, QUERY), repeats)
    else:
        stages["embed_score_all_cold"] = float("nan")
        stages["embed_score_all_cached"] = float("nan")

    stages["select_lexical_only"] = _time(
        lambda: InformationGainSelector(enable_escalation=False).select(
            blocks, QUERY, edges, token_budget=2000), repeats)
    stages["expand_graph"] = _time(
        lambda: slicer.compute_transitive_closure({0}, edges, max_depth=3), repeats)

    total_lexical = _time(
        lambda: ContextExecutionPlanner(
            selection_strategy="relative").plan_and_optimize(
                [dict(m) for m in messages], model="gpt-4o-mini"), repeats)

    return {
        "target_tokens": target_tokens,
        "actual_context_tokens": actual,
        "n_blocks": len(blocks),
        "stage_ms": {k: (round(v, 2) if v == v else None) for k, v in stages.items()},
        "end_to_end_plan_ms": round(total_lexical, 2),
        "ms_per_1k_tokens": round(total_lexical / max(1, actual / 1000), 3),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="*", default=list(SIZES))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--run-id", default="profile-scale-001")
    ap.add_argument("--no-embeddings", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    for size in args.sizes:
        row = profile_size(size, repeats=args.repeats, with_embeddings=not args.no_embeddings)
        rows.append(row)
        print(f"  {row['actual_context_tokens']:>7d} tok / {row['n_blocks']:>4d} blocks "
              f"-> plan {row['end_to_end_plan_ms']:>8.2f} ms", flush=True)

    summary = {
        "run_id": args.run_id,
        "note": ("Overhead is scale-dependent. Every figure here is reported WITH "
                 "its context size; no single number generalises across sizes."),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "rows": rows,
    }
    out = Path("experiments/results") / f"{args.run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n================ OPTIMIZER OVERHEAD BY CONTEXT SIZE ================")
    hdr = f"{'ctx tokens':>11s}{'blocks':>8s}{'parse':>9s}{'bm25':>9s}{'embed(cold)':>13s}{'graph':>9s}{'plan e2e':>11s}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        s = r["stage_ms"]
        emb = s.get("embed_score_all_cold")
        print(f"{r['actual_context_tokens']:11d}{r['n_blocks']:8d}"
              f"{s['parse_blocks']:9.2f}{s['bm25_score_all']:9.2f}"
              f"{(emb if emb is not None else float('nan')):13.1f}"
              f"{s['build_graph']:9.2f}{r['end_to_end_plan_ms']:11.2f}")
    print(f"\nartifacts: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

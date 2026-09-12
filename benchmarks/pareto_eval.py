"""Matched-budget cost/quality evaluation of seed systems.

The audited comparisons pitted "standard RAG at 175 tokens" against "NeuralPack
at 783 tokens" and reported the accuracy difference as a win. That is not a
comparison, it is two different operating points.

Here every system sees the SAME budget, and each is swept across several budgets
to produce a cost/quality curve. The reported metric is **evidence recall**
(did the required text survive into the selected context?), which is explicitly
NOT task accuracy -- answering requires a real model and is measured separately
by the live harness.

Per-task context accounting is recorded for every row; cumulative totals are
never presented as context sizes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from benchmarks.seed_systems import SeedSystem, all_systems
from benchmarks.tasks_hard import HardTask, build_task_suite, suite_report
from npk.context.analyzer import estimate_tokens
from npk.context.retrieval import CodeContextRetriever

DEFAULT_BUDGETS = (250, 500, 1000, 2000, 4000)


@dataclass
class Row:
    system: str
    task_id: str
    family: str
    split: str
    hops: int
    budget: int
    corpus_tokens: int          # available context for THIS task
    selected_tokens: int
    evidence_recall: float      # fraction of required gold strings retained
    full_recall: bool           # every gold string retained
    forbidden_leaked: bool
    seed_failed: bool
    latency_ms: float


def evaluate_task(system: SeedSystem, task: HardTask, budget: int,
                  retriever: CodeContextRetriever) -> Row:
    blocks = retriever.parse_blocks(task.context)
    t0 = time.perf_counter()
    try:
        idx = system.select(blocks, task.query, budget)
    except Exception:
        idx = []
    latency = (time.perf_counter() - t0) * 1000.0

    selected_text = "\n\n".join(blocks[i]["text"] for i in idx)
    hits = sum(1 for g in task.gold if g in selected_text)
    recall = hits / len(task.gold) if task.gold else 1.0
    leaked = any(f in selected_text for f in task.forbidden)

    return Row(
        system=system.name, task_id=task.id, family=task.family, split=task.split,
        hops=task.hops, budget=budget,
        corpus_tokens=task.context_tokens,
        selected_tokens=estimate_tokens(selected_text),
        evidence_recall=recall, full_recall=(hits == len(task.gold)),
        forbidden_leaked=leaked, seed_failed=(not idx),
        latency_ms=latency,
    )


def run(
    tasks: Sequence[HardTask],
    systems: Sequence[SeedSystem],
    budgets: Sequence[int] = DEFAULT_BUDGETS,
    run_id: str = "pareto-001",
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    retriever = CodeContextRetriever()
    rows: List[Row] = []

    usable = []
    skipped = []
    for s in systems:
        if s.requires_model and not s.available():
            skipped.append(s.name)
        else:
            usable.append(s)

    for s in usable:
        for budget in budgets:
            for t in tasks:
                rows.append(evaluate_task(s, t, budget, retriever))
        print(f"  done: {s.name}", flush=True)

    summary = summarize(rows)
    summary.update({
        "run_id": run_id,
        "metric_note": (
            "evidence_recall measures whether required text survived into the "
            "selected context. It is NOT task accuracy."
        ),
        "skipped_systems_missing_models": skipped,
        "suite": suite_report(tasks),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
    })

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        with (out_dir / "rows.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(asdict(r)) + "\n")
    return summary


def summarize(rows: Sequence[Row]) -> Dict[str, Any]:
    by_sb: Dict[str, Dict[int, List[Row]]] = {}
    for r in rows:
        by_sb.setdefault(r.system, {}).setdefault(r.budget, []).append(r)

    curves: Dict[str, List[Dict[str, Any]]] = {}
    for system, budmap in by_sb.items():
        pts = []
        for budget in sorted(budmap):
            group = budmap[budget]
            pts.append({
                "budget": budget,
                "mean_selected_tokens": round(statistics.mean(r.selected_tokens for r in group), 1),
                "full_recall_pct": round(100.0 * sum(r.full_recall for r in group) / len(group), 1),
                "mean_evidence_recall_pct": round(100.0 * statistics.mean(r.evidence_recall for r in group), 1),
                "forbidden_leak_pct": round(100.0 * sum(r.forbidden_leaked for r in group) / len(group), 1),
                "seed_failure_pct": round(100.0 * sum(r.seed_failed for r in group) / len(group), 1),
                "median_latency_ms": round(statistics.median(r.latency_ms for r in group), 2),
            })
        curves[system] = pts

    by_family: Dict[str, Dict[str, float]] = {}
    for r in rows:
        key = r.family
        entry = by_family.setdefault(key, {})
        entry.setdefault(r.system, 0.0)
    for family in by_family:
        for system in by_sb:
            group = [r for r in rows if r.family == family and r.system == system]
            if group:
                by_family[family][system] = round(
                    100.0 * sum(r.full_recall for r in group) / len(group), 1)

    return {"curves": curves, "full_recall_by_family_pct": by_family, "n_rows": len(rows)}


def print_report(summary: Dict[str, Any]) -> None:
    print("\n================ MATCHED-BUDGET EVIDENCE RECALL ================")
    print("metric: % of tasks where ALL required evidence survived selection")
    print("(evidence recall, NOT task accuracy)\n")

    budgets = sorted({p["budget"] for pts in summary["curves"].values() for p in pts})
    header = f"{'system':30s}" + "".join(f"{b:>8d}" for b in budgets)
    print(header)
    print("-" * len(header))
    for system, pts in sorted(summary["curves"].items(),
                              key=lambda kv: -statistics.mean(p["full_recall_pct"] for p in kv[1])):
        bymap = {p["budget"]: p["full_recall_pct"] for p in pts}
        print(f"{system:30s}" + "".join(f"{bymap.get(b, float('nan')):8.1f}" for b in budgets))

    if summary.get("skipped_systems_missing_models"):
        print(f"\nskipped (model unavailable): {summary['skipped_systems_missing_models']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=3)
    ap.add_argument("--filler-tokens", type=int, default=4000)
    ap.add_argument("--corpus", choices=("synthetic", "real"), default="synthetic")
    ap.add_argument("--split", choices=("dev", "sealed", "all"), default="dev")
    ap.add_argument("--budgets", type=int, nargs="*", default=list(DEFAULT_BUDGETS))
    ap.add_argument("--run-id", default="pareto-dev-001")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    tasks = build_task_suite(per_family=args.per_family, filler_tokens=args.filler_tokens,
                             corpus=args.corpus)
    if args.split != "all":
        tasks = [t for t in tasks if t.split == args.split]

    systems = all_systems(include_models=not args.no_models)
    print(f"tasks={len(tasks)} split={args.split} corpus={args.corpus} "
          f"systems={len(systems)} budgets={args.budgets}")

    out = Path(args.out) if args.out else Path("experiments/runs") / args.run_id
    summary = run(tasks, systems, budgets=args.budgets, run_id=args.run_id, out_dir=out)
    print_report(summary)
    print(f"\nper-task context tokens: {summary['suite']['context_tokens_per_task']}")
    print(f"artifacts: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

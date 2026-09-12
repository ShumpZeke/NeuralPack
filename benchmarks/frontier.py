"""Cost/quality frontier: how many tokens does each system need for full recall?

Budget-matched accuracy tables saturate -- once the budget is generous every
competent retriever finds the evidence. The question that actually separates
systems for a **closed-model** optimizer, where every input token is billed, is
the inverse:

    what is the smallest context that still contains all required evidence?

This sweeps budgets finely and reports, per system:

* ``min_tokens_full_recall`` -- fewest tokens actually spent at which the system
  achieved 100% full-recall across the task set;
* the recall achieved at each budget;
* optimizer latency.

Reported per task, never as cumulative totals.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Dict, List, Optional, Sequence

from benchmarks.pareto_eval import Row, evaluate_task
from benchmarks.seed_systems import SeedSystem, all_systems
from benchmarks.tasks_hard import HardTask, build_task_suite, suite_report
from npk.context.retrieval import CodeContextRetriever

FINE_BUDGETS = (60, 100, 150, 220, 320, 450, 650, 900, 1300, 1800, 2600, 3600, 5000)


def frontier(
    tasks: Sequence[HardTask],
    systems: Sequence[SeedSystem],
    budgets: Sequence[int] = FINE_BUDGETS,
    recall_target: float = 100.0,
) -> Dict[str, Any]:
    retriever = CodeContextRetriever()
    results: Dict[str, Any] = {}
    skipped: List[str] = []

    for system in systems:
        if system.requires_model and not system.available():
            skipped.append(system.name)
            continue

        points = []
        best: Optional[Dict[str, Any]] = None
        for budget in budgets:
            rows = [evaluate_task(system, t, budget, retriever) for t in tasks]
            recall = 100.0 * sum(r.full_recall for r in rows) / len(rows)
            used = statistics.mean(r.selected_tokens for r in rows)
            latency = statistics.median(r.latency_ms for r in rows)
            point = {
                "budget": budget,
                "mean_tokens_used": round(used, 1),
                "full_recall_pct": round(recall, 1),
                "median_latency_ms": round(latency, 2),
            }
            points.append(point)
            if best is None and recall >= recall_target:
                best = point
        results[system.name] = {
            "points": points,
            "frontier_point_full_recall": best,
            "min_tokens_full_recall": best["mean_tokens_used"] if best else None,
        }
        print(f"  done: {system.name}", flush=True)

    return {"systems": results, "skipped_systems_missing_models": skipped,
            "recall_target_pct": recall_target}


def print_frontier(summary: Dict[str, Any]) -> None:
    print("\n=========== COST/QUALITY FRONTIER (closed-model token cost) ===========")
    print("fewest tokens at which a system reached 100% evidence recall")
    print("lower is better; None = never reached the target within the sweep\n")
    print(f"{'system':32s}{'tokens@100% recall':>22s}{'latency ms':>13s}")
    print("-" * 67)

    rows = []
    for name, data in summary["systems"].items():
        pt = data["frontier_point_full_recall"]
        rows.append((data["min_tokens_full_recall"], name, pt))
    rows.sort(key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0))

    for tokens, name, pt in rows:
        if tokens is None:
            print(f"{name:32s}{'never':>22s}{'-':>13s}")
        else:
            print(f"{name:32s}{tokens:22.0f}{pt['median_latency_ms']:13.1f}")

    if summary.get("skipped_systems_missing_models"):
        print(f"\nskipped (model unavailable): {summary['skipped_systems_missing_models']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=2)
    ap.add_argument("--filler-tokens", type=int, default=25000)
    ap.add_argument("--corpus", choices=("synthetic", "real"), default="real")
    ap.add_argument("--split", choices=("dev", "sealed", "all"), default="dev")
    ap.add_argument("--run-id", default="frontier-dev-001")
    ap.add_argument("--no-models", action="store_true")
    args = ap.parse_args(argv)

    tasks = build_task_suite(per_family=args.per_family,
                             filler_tokens=args.filler_tokens, corpus=args.corpus)
    if args.split != "all":
        tasks = [t for t in tasks if t.split == args.split]

    systems = all_systems(include_models=not args.no_models)
    print(f"tasks={len(tasks)} split={args.split} corpus={args.corpus} systems={len(systems)}")

    summary = frontier(tasks, systems)
    summary["suite"] = suite_report(tasks)
    summary["run_id"] = args.run_id

    out = Path("experiments/runs") / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "frontier.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print_frontier(summary)
    print(f"\nper-task context tokens: {summary['suite']['context_tokens_per_task']}")
    print(f"artifacts: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

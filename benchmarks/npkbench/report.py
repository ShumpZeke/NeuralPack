"""Summaries and paired comparisons for NPK-Bench runs.

    python -m benchmarks.npkbench.report RUN_DIR
    python -m benchmarks.npkbench.report --compare RUN_A:ARM_A RUN_B:ARM_B
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
from typing import Any, Dict, List, Tuple

from .metrics import bootstrap_diff

METRICS = ("hunk_recall", "file_recall", "all_found", "line_recall")


def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _mean(values: List[float]) -> float:
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return sum(values) / len(values) if values else math.nan


def _pct(values: List[float], q: float) -> float:
    values = sorted(values)
    if not values:
        return math.nan
    return values[min(len(values) - 1, int(q * len(values)))]


def summarize(run: Path) -> Dict[str, Any]:
    rows = _read(run / "rows.jsonl")
    ranks = _read(run / "ranks.jsonl")
    builds = _read(run / "builds.jsonl")
    errors = _read(run / "errors.jsonl")
    out: Dict[str, Any] = {"arms": {}, "errors": len(errors), "tasks": len({r["instance_id"] for r in rows})}
    for arm in sorted({r["arm"] for r in rows}):
        arm_rows = [r for r in rows if r["arm"] == arm]
        per_budget = {}
        for budget in sorted({r["budget"] for r in arm_rows}):
            sel = [r for r in arm_rows if r["budget"] == budget]
            entry = {m: round(_mean([r[m] for r in sel]), 4) for m in METRICS}
            # Repository-macro average: django/sympy dominate the task count.
            repos = sorted({r["repo"] for r in sel})
            entry["hunk_recall_repo_macro"] = round(_mean(
                [_mean([r["hunk_recall"] for r in sel if r["repo"] == repo]) for repo in repos]), 4)
            entry["tokens_mean"] = round(_mean([r["tokens"] for r in sel]), 1)
            entry["latency_ms_p50"] = round(_pct([r["latency_ms"] for r in sel], 0.5), 2)
            entry["latency_ms_p95"] = round(_pct([r["latency_ms"] for r in sel], 0.95), 2)
            entry["fallback"] = sum(r["status"] != "selected" for r in sel)
            entry["n"] = len(sel)
            per_budget[str(budget)] = entry
        arm_ranks = [r for r in ranks if r["arm"] == arm]
        rank_summary = {}
        if arm_ranks:
            found = [r["tokens_to_all"] for r in arm_ranks if r["tokens_to_all"] is not None]
            first = [r["tokens_to_first"] for r in arm_ranks if r["tokens_to_first"] is not None]
            rank_summary = {
                "n": len(arm_ranks),
                "all_found_in_pool": len(found),
                "tokens_to_all_median": _pct(found, 0.5) if found else None,
                # Unfound tasks count as infinite cost; report the task-level median.
                "tokens_to_all_median_all_tasks": (_pct(found + [math.inf] * (len(arm_ranks) - len(found)), 0.5)
                                                   if arm_ranks else None),
                "tokens_to_first_median": _pct(first, 0.5) if first else None,
            }
        out["arms"][arm] = {"budgets": per_budget, "ranking": rank_summary}
    if builds:
        by_fp: Dict[str, List[Dict[str, Any]]] = {}
        for b in builds:
            by_fp.setdefault(b["fingerprint"], []).append(b)
        out["builds"] = {
            fp: {"packs": len(items),
                 "compile_s_mean": round(_mean([b["compile_s"] for b in items]), 2),
                 "compile_s_total": round(sum(b["compile_s"] for b in items), 1),
                 "pack_mb_mean": round(_mean([b["pack_bytes"] / 1e6 for b in items]), 2),
                 "tasks_with_blockers": sum(bool(b["blockers_removed"]) for b in items)}
            for fp, items in by_fp.items()}
    return out


def render(summary: Dict[str, Any]) -> str:
    lines = [f"tasks={summary['tasks']} errors={summary['errors']}"]
    for arm, info in summary["arms"].items():
        lines.append(f"\n== {arm}")
        lines.append(f"{'budget':>7} {'hunk':>6} {'h_repo':>6} {'file':>6} {'all':>6} {'line':>6} {'tok':>7} {'p50ms':>7} {'fb':>3}")
        for budget, e in info["budgets"].items():
            lines.append(f"{budget:>7} {e['hunk_recall']:6.3f} {e['hunk_recall_repo_macro']:6.3f} "
                         f"{e['file_recall']:6.3f} {e['all_found']:6.3f} {e['line_recall']:6.3f} "
                         f"{e['tokens_mean']:7.0f} {e['latency_ms_p50']:7.1f} {e['fallback']:>3}")
        if info["ranking"]:
            lines.append(f"  ranking: {info['ranking']}")
    if "builds" in summary:
        lines.append(f"\nbuilds: {summary['builds']}")
    return "\n".join(lines)


def paired(run_a: Path, arm_a: str, run_b: Path, arm_b: str, metric: str = "hunk_recall") -> Dict[str, Any]:
    rows_a = {(r["instance_id"], r["budget"]): r for r in _read(run_a / "rows.jsonl") if r["arm"] == arm_a}
    rows_b = {(r["instance_id"], r["budget"]): r for r in _read(run_b / "rows.jsonl") if r["arm"] == arm_b}
    out = {}
    for budget in sorted({k[1] for k in rows_a} & {k[1] for k in rows_b}):
        keys = sorted(k for k in rows_a if k[1] == budget and k in rows_b)
        a = [rows_a[k][metric] for k in keys]
        b = [rows_b[k][metric] for k in keys]
        mean, lo, hi = bootstrap_diff(a, b)
        wins = sum(y > x for x, y in zip(a, b))
        losses = sum(y < x for x, y in zip(a, b))
        out[str(budget)] = {"n": len(keys), "a": round(_mean(a), 4), "b": round(_mean(b), 4),
                            "diff": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                            "wins": wins, "losses": losses}
    return out


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--compare", nargs=2, metavar=("RUN_A:ARM", "RUN_B:ARM"))
    parser.add_argument("--metric", default="hunk_recall")
    args = parser.parse_args(argv)
    if args.compare:
        (ra, aa), (rb, ab) = (x.rsplit(":", 1) for x in args.compare)
        print(json.dumps(paired(Path(ra), aa, Path(rb), ab, args.metric), indent=1))
    else:
        summary = summarize(args.run)
        print(render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

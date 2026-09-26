"""Run NPK-Bench arms over a split and write rows plus a summary.

    python -m benchmarks.npkbench.run --split dev-fast --arms npk_default,oracle_blocks \
        --out experiments/npkbench/runs/<run-id>

Makes zero generative model calls. Packs are cached by compiler fingerprint.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
import traceback
from typing import Any, Dict, List, Sequence

from . import arms as arms_mod
from . import data, metrics, packs, report

DEFAULT_BUDGETS = (1024, 2048, 4096, 8192, 16384)


def _load_experimental_arms(specs: Sequence[str]) -> None:
    import importlib
    for spec in specs:
        importlib.import_module(spec)


def _job(args) -> Dict[str, Any]:
    import warnings
    # Repository source can contain invalid escapes; ast.parse warns per file.
    warnings.simplefilter("ignore", SyntaxWarning)
    task, arm_names, budgets, extra_modules, extra_targets, ephemeral = args
    _load_experimental_arms(extra_modules)
    out: Dict[str, Any] = {"instance_id": task.instance_id, "rows": [], "ranks": [], "builds": [], "errors": []}
    created: List[Any] = []
    # Selection never sees gold, so one selection is scored against every
    # target: rows for an extra target carry the arm name "<arm>@<target>".
    scored = [("", task)] + [(f"@{name}", t) for name, t in extra_targets]
    for name in arm_names:
        arm = arms_mod.get(name)
        try:
            pack = packs.pack_path(task, arm.compile_options)
            existed = pack.exists()
            meta = packs.ensure_pack(task, arm.compile_options)
            if not existed:
                created.append(pack)
            if meta not in out["builds"]:
                out["builds"].append(meta)
            results = arm.run(pack, task, budgets)
            for suffix, target in scored:
                for budget, res in results.items():
                    row = {"instance_id": task.instance_id, "repo": task.repo, "arm": name + suffix,
                           "budget": budget, "tokens": res.tokens, "latency_ms": round(res.latency_ms, 3),
                           "status": res.status, "n_blocks": res.n_blocks}
                    row.update(metrics.score(target, res.spans))
                    row["spans"] = [list(x) for x in res.spans]
                    if res.extra:
                        row["extra"] = res.extra
                    out["rows"].append(row)
                    map_spans = (res.extra or {}).get("map_spans")
                    if map_spans is not None:
                        # "Locatable" view: full text OR a map entry naming the span.
                        loc = dict(row, arm=f"{name}~loc{suffix}")
                        loc.update(metrics.score(target, list(res.spans) + [tuple(x) for x in map_spans]))
                        loc.pop("extra", None)
                        out["rows"].append(loc)
            ranking = arm.ranking(pack, task)
            if ranking is not None:
                for suffix, target in scored:
                    rank = {"instance_id": task.instance_id, "repo": task.repo, "arm": name + suffix,
                            "candidates": len(ranking)}
                    rank.update(metrics.tokens_to_find(target, ranking))
                    out["ranks"].append(rank)
        except Exception as exc:  # recorded per task; never silently dropped
            out["errors"].append({"instance_id": task.instance_id, "arm": name,
                                  "error": f"{type(exc).__name__}: {exc}",
                                  "traceback": traceback.format_exc(limit=6)})
    if ephemeral:
        for pack in created:
            pack.unlink(missing_ok=True)
            pack.with_suffix(".json").unlink(missing_ok=True)
    return out


def environment() -> Dict[str, Any]:
    root = packs.ROOT
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout.strip()
    return {
        # Untracked files (e.g. other runs' outputs) do not change what ran.
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(), "cpus": os.cpu_count(), "bench_version": data.BENCH_VERSION,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev-fast")
    parser.add_argument("--arms", default="npk_default")
    parser.add_argument("--budgets", default=",".join(map(str, DEFAULT_BUDGETS)))
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    parser.add_argument("--limit", type=int, default=0, help="first N tasks only (smoke tests)")
    parser.add_argument("--repos", default="", help="comma-separated repo filter")
    parser.add_argument("--load", default="", help="comma-separated modules that register arms")
    parser.add_argument("--targets", default="", help="extra gold targets scored on the same selections, e.g. tests")
    parser.add_argument("--ephemeral-packs", action="store_true",
                        help="delete packs this run builds once their task is scored (large held-out runs)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    arm_names = [a for a in args.arms.split(",") if a]
    extra = [m for m in args.load.split(",") if m]
    _load_experimental_arms(extra)
    for name in arm_names:
        arms_mod.get(name)
    budgets = tuple(int(b) for b in args.budgets.split(","))
    tasks = data.split(args.split)
    if args.repos:
        wanted = set(args.repos.split(","))
        tasks = [t for t in tasks if t.repo in wanted]
    if args.limit:
        tasks = tasks[:args.limit]
    # Longest jobs first for load balance.
    weight = {"django/django": 3, "sympy/sympy": 3}
    tasks.sort(key=lambda t: (-weight.get(t.repo, 1), t.instance_id))

    # Load every product module before forking. Workers are recycled, and a
    # lazily imported module would otherwise be read from disk mid-run; an
    # edit during a run could then mix two compilers under one fingerprint.
    import npk.pack, npk.pack.compile, npk.pack.select, npk.pack.format  # noqa: F401
    import npk.pack.integrity, npk.pack.conflict, npk.pack.source_policy  # noqa: F401

    # A run is written to "<out>.partial" and renamed to "<out>" only when it is
    # complete, so an unfinished run never looks like a result (the .partial
    # directories are git-ignored). A finished run is never overwritten.
    final_out = args.out
    if (final_out / "summary.json").exists():
        raise SystemExit(f"{final_out} already holds a finished run; choose another --out")
    args.out = final_out.with_name(final_out.name + ".partial")
    if args.out.exists():
        import shutil
        shutil.rmtree(args.out)  # an interrupted attempt of this same run
    args.out.mkdir(parents=True)
    started = time.time()
    config = {"split": args.split, "arms": arm_names, "budgets": list(budgets), "tasks": len(tasks),
              "targets": ["fix", *[x for x in args.targets.split(",") if x]],
              "ephemeral_packs": args.ephemeral_packs,
              "load": extra, "environment": environment(), "started_unix": started,
              "compiler_fingerprints": {n: packs.compiler_fingerprint(arms_mod.get(n).compile_options)
                                        for n in arm_names}}
    (args.out / "config.json").write_text(json.dumps(config, indent=1))
    files = {k: (args.out / f"{k}.jsonl").open("w") for k in ("rows", "ranks", "builds", "errors")}
    done = 0
    try:
        target_names = [x for x in args.targets.split(",") if x]
        target_maps = {name: {t.instance_id: t for t in data.split(f"{args.split}:{name}")}
                       for name in target_names}
        jobs = [(t, arm_names, budgets, extra,
                 [(name, target_maps[name][t.instance_id]) for name in target_names
                  if t.instance_id in target_maps[name]],
                 args.ephemeral_packs) for t in tasks]
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(args.workers, maxtasksperchild=8) as pool:
            for result in pool.imap_unordered(_job, jobs):
                for key in ("rows", "ranks", "builds", "errors"):
                    for item in result[key]:
                        files[key].write(json.dumps(item, sort_keys=True) + "\n")
                    files[key].flush()
                done += 1
                if done % 10 == 0 or done == len(tasks):
                    print(f"[{time.time() - started:7.1f}s] {done}/{len(tasks)} tasks", flush=True)
    finally:
        for f in files.values():
            f.close()
    # Rows carry every selected span (for offline re-scoring); compress them
    # so dozens of runs stay cheap to keep in version control.
    import gzip
    rows_path = args.out / "rows.jsonl"
    (args.out / "rows.jsonl.gz").write_bytes(gzip.compress(rows_path.read_bytes(), mtime=0))
    rows_path.unlink()
    summary = report.summarize(args.out)
    summary["elapsed_s"] = round(time.time() - started, 1)
    final = {n: packs.compiler_fingerprint(arms_mod.get(n).compile_options) for n in arm_names}
    summary["fingerprints_stable"] = final == config["compiler_fingerprints"]
    if not summary["fingerprints_stable"]:
        print("WARNING: compiler sources changed during the run; results are not attributable")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    if final_out.exists():  # leftovers of a failed attempt (no summary): keep them aside
        final_out.rename(final_out.with_name(f"{final_out.name}.partial-aborted-{int(time.time())}"))
    args.out.rename(final_out)
    print(report.render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

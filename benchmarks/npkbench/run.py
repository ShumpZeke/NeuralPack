"""Run NPK-Bench arms over a split and write rows plus a summary.

    python -m benchmarks.npkbench.run --split dev-fast --arms npk_default,oracle_blocks \
        --out experiments/npkbench/runs/<run-id>

Makes zero generative model calls. Packs are cached by compiler fingerprint.
"""
from __future__ import annotations

import argparse
import hashlib
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
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import arms as arms_mod
from . import data, metrics, packs, report

DEFAULT_BUDGETS = (1024, 2048, 4096, 8192, 16384)
RESULT_KEYS = ("rows", "ranks", "builds", "errors")
JOURNAL = "journal.jsonl"
# What may differ between two attempts of one run without making their rows incomparable: the
# clock, the resume log, and the commit (the source digest decides whether the code changed).
_VOLATILE = ("started_unix", "resumes")
_VOLATILE_ENV = ("git_commit", "git_dirty")


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


def source_digest(root: Path, extra_modules: Sequence[str]) -> str:
    """Digest of the code that produces a run's rows: the product, the harness and the loaded arms."""
    import importlib.util
    root = root.resolve()
    files = {p.resolve() for p in (root / "npk").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    files |= {p.resolve() for p in (root / "benchmarks" / "npkbench").glob("*.py")}
    for spec in extra_modules:
        found = importlib.util.find_spec(spec)
        if found is not None and found.origin and Path(found.origin).is_file():
            files.add(Path(found.origin).resolve())
    for module in list(sys.modules.values()):  # whatever else the loaded arm modules pulled in
        origin = getattr(module, "__file__", None)
        if origin and origin.endswith(".py") and (root / "benchmarks") in Path(origin).resolve().parents:
            files.add(Path(origin).resolve())
    digest = hashlib.sha256()
    names = {path: path.relative_to(root).as_posix() if root in path.parents else path.name for path in files}
    for path in sorted(files, key=lambda p: (names[p], str(p))):
        digest.update(names[path].encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def config_mismatch(old: Dict[str, Any], new: Dict[str, Any]) -> Optional[str]:
    """The first setting that differs between two run configs, or None when they match."""
    def strip(config: Dict[str, Any]) -> Dict[str, Any]:
        config = json.loads(json.dumps(config))
        for key in _VOLATILE:
            config.pop(key, None)
        for key in _VOLATILE_ENV:
            config.get("environment", {}).pop(key, None)
        return config
    a, b = strip(old), strip(new)
    for key in sorted(set(a) | set(b)):
        if key == "environment" and isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
            for sub in sorted(set(a[key]) | set(b[key])):
                if a[key].get(sub) != b[key].get(sub):
                    return f"environment.{sub}"
        elif a.get(key) != b.get(key):
            return key
    return None


def read_journal(path: Path, wanted: Set[str]) -> Dict[str, Dict[str, Any]]:
    """The entries of the tasks an interrupted attempt finished (instance id -> entry).

    A killed process can leave a torn last line, even padding that is not UTF-8, so reading stops
    at the first line that is not a whole entry; the tasks after it are simply run again.
    """
    done: Dict[str, Dict[str, Any]] = {}
    if not path.is_file():
        return done
    with path.open("rb") as fh:
        for raw in fh:
            try:
                entry = json.loads(raw)
                iid, result = entry["instance_id"], entry["result"]
                whole = (isinstance(result, dict) and result.get("instance_id") == iid
                         and all(isinstance(result.get(key), list) for key in RESULT_KEYS))
            except (ValueError, KeyError, TypeError):
                break
            if not whole:
                break
            # A task that recorded an error is run again: the cause may have been transient.
            if iid in wanted and iid not in done and not result["errors"]:
                done[iid] = entry
    return done


def journal_line(entry: Dict[str, Any]) -> bytes:
    return (json.dumps(entry, sort_keys=True) + "\n").encode()


def rewrite_journal(path: Path, entries: Sequence[Dict[str, Any]]) -> None:
    """Replace the journal by exactly these entries (drops a torn tail) and make it durable."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as fh:
        for entry in entries:
            fh.write(journal_line(entry))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def resume_state(partial: Path, config: Dict[str, Any],
                 task_ids: Set[str]) -> Tuple[Dict[str, Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """(finished tasks, the interrupted attempt's config, reason it cannot resume) of a "<out>.partial".

    The attempt resumes only when everything that determines its rows is unchanged: the split,
    task list, arms, budgets, targets, loaded modules, interpreter and the digest of the code.
    """
    try:
        old = json.loads((partial / "config.json").read_text())
    except (OSError, ValueError):
        return {}, None, "no readable config.json"
    if not (partial / JOURNAL).is_file():
        return {}, None, "no journal (written by an earlier harness)"
    differs = config_mismatch(old, config)
    if differs is not None:
        return {}, None, f"{differs} differs from the interrupted attempt"
    return read_journal(partial / JOURNAL, task_ids), old, ""


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
    parser.add_argument("--fresh", action="store_true",
                        help="discard an interrupted attempt of this run instead of resuming it")
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
    import npk.pack  # noqa: F401
    import npk.pack.compile  # noqa: F401
    import npk.pack.select  # noqa: F401
    import npk.pack.format  # noqa: F401
    import npk.pack.integrity  # noqa: F401
    import npk.pack.conflict  # noqa: F401
    import npk.pack.source_policy  # noqa: F401

    # A run is written to "<out>.partial" and renamed to "<out>" only when it is
    # complete, so an unfinished run never looks like a result (the .partial
    # directories are git-ignored). A finished run is never overwritten. Every finished task is
    # also appended to "<out>.partial/journal.jsonl" (one fsynced line); an interrupted attempt
    # resumes from it when nothing that determines its rows has changed, else it is discarded.
    final_out = args.out
    if (final_out / "summary.json").exists():
        raise SystemExit(f"{final_out} already holds a finished run; choose another --out")
    args.out = final_out.with_name(final_out.name + ".partial")
    started = time.time()
    config = {"split": args.split, "arms": arm_names, "budgets": list(budgets), "tasks": len(tasks),
              "task_ids_sha256": hashlib.sha256("\n".join(sorted(t.instance_id for t in tasks)).encode()).hexdigest(),
              "repos": args.repos, "limit": args.limit,
              "targets": ["fix", *[x for x in args.targets.split(",") if x]],
              "ephemeral_packs": args.ephemeral_packs,
              "load": extra, "environment": environment(), "started_unix": started,
              "source_digest": source_digest(packs.ROOT, extra),
              "compiler_fingerprints": {n: packs.compiler_fingerprint(arms_mod.get(n).compile_options)
                                        for n in arm_names}}
    finished: Dict[str, Dict[str, Any]] = {}
    active_before = 0.0  # seconds earlier attempts of this run were working
    if args.out.exists():
        import shutil
        interrupted, why = None, "--fresh"
        if not args.fresh:
            finished, interrupted, why = resume_state(args.out, config, {t.instance_id for t in tasks})
        if interrupted is None:
            print(f"discarding the interrupted attempt of {final_out.name}: {why}", flush=True)
            shutil.rmtree(args.out)
            finished = {}
        else:
            active_before = max((e.get("t", 0.0) for e in finished.values()), default=0.0)
            interrupted["resumes"] = [*interrupted.get("resumes", []), {
                "started_unix": started, "tasks_done": len(finished), "active_s_before": active_before,
                "environment": {k: config["environment"].get(k) for k in _VOLATILE_ENV}}]
            config = interrupted  # the first attempt's settings, plus this resume
            print(f"resuming {final_out.name}: {len(finished)}/{len(tasks)} tasks already done "
                  f"({len(config['resumes'])} interruption(s))", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "config.json").write_text(json.dumps(config, indent=1))
    journal_path = args.out / JOURNAL
    rewrite_journal(journal_path, list(finished.values()))
    files = {k: (args.out / f"{k}.jsonl").open("w") for k in RESULT_KEYS}
    for entry in finished.values():  # the result files are rebuilt from the journal
        for key in RESULT_KEYS:
            for item in entry["result"][key]:
                files[key].write(json.dumps(item, sort_keys=True) + "\n")
    for f in files.values():
        f.flush()
    journal = journal_path.open("ab")
    done = len(finished)
    try:
        target_names = [x for x in args.targets.split(",") if x]
        target_maps = {name: {t.instance_id: t for t in data.split(f"{args.split}:{name}")}
                       for name in target_names}
        jobs = [(t, arm_names, budgets, extra,
                 [(name, target_maps[name][t.instance_id]) for name in target_names
                  if t.instance_id in target_maps[name]],
                 args.ephemeral_packs) for t in tasks if t.instance_id not in finished]
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(args.workers if jobs else 1, maxtasksperchild=8) as pool:
            for result in pool.imap_unordered(_job, jobs):
                entry = {"instance_id": result["instance_id"],
                         "t": round(active_before + time.time() - started, 1), "result": result}
                journal.write(journal_line(entry))
                journal.flush()
                os.fsync(journal.fileno())
                for key in RESULT_KEYS:
                    for item in result[key]:
                        files[key].write(json.dumps(item, sort_keys=True) + "\n")
                    files[key].flush()
                done += 1
                if done % 10 == 0 or done == len(tasks):
                    print(f"[{time.time() - started:7.1f}s] {done}/{len(tasks)} tasks", flush=True)
    finally:
        journal.close()
        for f in files.values():
            f.close()
    journal_path.unlink()  # the result files hold the same rows
    # Rows carry every selected span (for offline re-scoring); compress them
    # so dozens of runs stay cheap to keep in version control.
    import gzip
    rows_path = args.out / "rows.jsonl"
    (args.out / "rows.jsonl.gz").write_bytes(gzip.compress(rows_path.read_bytes(), mtime=0))
    rows_path.unlink()
    summary = report.summarize(args.out)
    summary["elapsed_s"] = round(active_before + time.time() - started, 1)
    if config.get("resumes"):
        summary["resumes"] = len(config["resumes"])
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

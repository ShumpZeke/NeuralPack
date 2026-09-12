"""Frozen, paired LOCAL update experiment; no target or embedding model calls.

Prepare before editing product code. Run immutable champion and candidate copies
in separate processes, then independently compare logical tables, full verification,
and query payloads with a clean rebuild. OS caches/host activity are uncontrolled.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import importlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from unittest.mock import patch


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def hashes(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in sorted((root / "npk").rglob("*.py"))}


def snapshot(repo, target):
    shutil.copytree(repo / "npk", target / "npk",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return hashes(target)


def prepare(repo, root, champion_root=None):
    if root.exists():
        raise ValueError("new experiment directory required")
    root.mkdir(parents=True)
    champion = snapshot(champion_root or repo, root / "champion")
    origin = repo / "experiments/runs/packs/cycle19-manuals-v1"
    acquisition = json.loads((origin / "acquisition.json").read_text())
    sources = root / "sources"
    for item in acquisition["source_manifest"]:
        body = (origin / "source" / item["path"]).read_bytes()
        assert sha(body) == item["sha256"]
        target = sources / "public" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    synthetic = sources / "synthetic"
    synthetic.mkdir()
    for i in range(1000):
        body = f"# partition {i}\n" + "\n".join(
            f"def operation_{j}(value):\n    # partition_{i} shared retry policy\n"
            f"    return value + {i + j}\n" for j in range(12))
        (synthetic / f"part_{i:04d}.py").write_text(body, encoding="utf-8")
    plan = {
        "evidence_mode": "LOCAL", "generative_calls": 0,
        "hypothesis": "One FTS content scan per update removes repeated per-file scans without changing replacement order or query evidence.",
        "promotion_gate": "All payloads and logical rows match champion and clean rebuild; full integrity passes; bounded SQL parameters; material multi-file improvement without a material one-file regression.",
        "champion_hashes": champion,
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "champion_origin": str(champion_root or repo),
        "acquisition_sha256": sha((origin / "acquisition.json").read_bytes()),
        "source_hashes": {p.relative_to(sources).as_posix(): sha(p.read_bytes())
                          for p in sorted(sources.rglob("*")) if p.is_file()},
        "cases": ["noop", "one", "ten_percent", "all", "delete_all"],
        "corpora": ["public", "synthetic"], "trials": 3, "seed": 30091,
        "queries": ["retry policy", "ExitStack", "operation_11", "partition_500", "callback"],
        "budgets": [512, 2048],
        "limitations": ["Warm/uncontrolled host; no target answers or cold-cache claims.",
                        "Synthetic scaling is not natural repository quality.",
                        "Independent clean compilation is outside update timing."],
    }
    write(root / "plan.json", plan)
    (root / "plan.sha256").write_text(sha((root / "plan.json").read_bytes()))
    print({"prepared": str(root), "plan_sha256": sha((root / "plan.json").read_bytes())}, flush=True)


def logical_digest(con):
    statements = {
        "files": "SELECT path,sha256,size,language FROM files ORDER BY path",
        "blocks": "SELECT f.path,b.ordinal,b.kind,b.name,b.start_line,b.end_line,b.tokens,b.sha256,b.text FROM blocks b JOIN files f ON f.id=b.file_id ORDER BY f.path,b.ordinal",
        "symbols": "SELECT f.path,b.ordinal,s.name,s.kind,s.is_def FROM symbols s JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id ORDER BY f.path,b.ordinal,s.name,s.kind,s.is_def",
        "relations": "SELECT f.path,b.ordinal,r.kind,r.name FROM relations r JOIN blocks b ON b.id=r.block_id JOIN files f ON f.id=b.file_id ORDER BY f.path,b.ordinal,r.kind,r.name",
        "lexical": "SELECT f.path,b.ordinal,l.rowid FROM lexical l JOIN blocks b ON b.id=l.rowid JOIN files f ON f.id=b.file_id ORDER BY f.path,b.ordinal,l.rowid",
        "assignments": "SELECT f.path,b.ordinal,a.symbol,a.value_hash FROM assignments a JOIN blocks b ON b.id=a.block_id JOIN files f ON f.id=b.file_id ORDER BY f.path,b.ordinal,a.symbol,a.value_hash",
    }
    result = {}
    for name, sql in statements.items():
        digest = hashlib.sha256()
        for row in con.execute(sql):
            digest.update(json.dumps(tuple(row), ensure_ascii=True).encode() + b"\n")
        result[name] = digest.hexdigest()
    orphan = con.execute("SELECT count(*) FROM lexical l LEFT JOIN blocks b ON b.id=l.rowid WHERE b.id IS NULL").fetchone()[0]
    missing = con.execute("SELECT count(*) FROM blocks WHERE id NOT IN (SELECT rowid FROM lexical)").fetchone()[0]
    assert orphan == missing == 0
    assert con.execute("SELECT count(*) FROM lexical").fetchone()[0] == con.execute("SELECT count(*) FROM blocks").fetchone()[0]
    return result


def worker(root, arm, corpus, trial):
    sys.path.insert(0, str(root / arm))
    from npk.pack import compile_pack, update_pack, verify, PackSelector
    from npk.pack.format import open_pack
    module = importlib.import_module("npk.pack.compile")
    plan = json.loads((root / "plan.json").read_text())
    destination = root / "workers" / f"{arm}-{corpus}-{trial}"
    destination.mkdir(parents=True)
    source = destination / "source"
    shutil.copytree(root / "sources" / corpus, source)
    base = destination / "base.npk"
    start = time.perf_counter_ns()
    compile_pack(source, base)
    compile_ms = (time.perf_counter_ns() - start) / 1e6
    assert verify(base)["ok"]
    names = sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file())
    def evidence(path):
        with open_pack(path) as con:
            logical = logical_digest(con)
        selector = PackSelector(path)
        selections = []
        for question in plan["queries"]:
            for budget in plan["budgets"]:
                selected = selector.select(question, budget_tokens=budget)
                assert selected.total_tokens <= budget and selected.query == question
                selections.append({"question": question, "budget": budget,
                                   "text_sha256": sha(selected.context_text().encode()),
                                   "spans": [b.span for b in selected.evidence],
                                   "tokens": selected.total_tokens,
                                   "seed_failed": selected.seed_failed})
        return {"logical": logical, "selections": selections}
    rows = []
    cases = list(plan["cases"])
    random.Random(plan["seed"] + trial).shuffle(cases)
    for case in cases:
        count = {"noop": 0, "one": 1, "ten_percent": max(1, len(names)//10),
                 "all": len(names), "delete_all": len(names)}[case]
        original = {name: (source / name).read_bytes() for name in names[:count]}
        for name, body in original.items():
            if case == "delete_all":
                (source / name).unlink()
            else:
                (source / name).write_bytes(body + b"\n# changed_partition marker\n")
        pack = destination / f"{case}.npk"
        shutil.copyfile(base, pack)
        stage = {}
        def wrapper(label, operation):
            def call(*a, **kw):
                start = time.perf_counter_ns()
                try:
                    return operation(*a, **kw)
                finally:
                    stage[label] = stage.get(label, 0) + (time.perf_counter_ns()-start)/1e6
            return call
        with ExitStack() as stack:
            for function in ("scan_source", "check_cached_base", "_write_file_blocks", "_drop_file", "_drop_lexical", "_available_tokens", "_seal"):
                if hasattr(module, function):
                    stack.enter_context(patch.object(module, function, wrapper(function, getattr(module, function))))
            start = time.perf_counter_ns()
            stats = update_pack(pack, source)
            update_ms = (time.perf_counter_ns() - start)/1e6
        assert verify(pack)["ok"]
        result = evidence(pack)
        if arm == "candidate":
            fresh = destination / f"{case}-fresh.npk"
            compile_pack(source, fresh)
            assert verify(fresh)["ok"] and evidence(fresh) == result
        if case == "noop":
            assert pack.read_bytes() == base.read_bytes()
        rows.append({"arm": arm, "corpus": corpus, "trial": trial, "case": case,
                     "changed_files": count, "update_ms": update_ms, "stage_ms": stage,
                     "stats": stats.as_dict(), "evidence": result, "pack_bytes": pack.stat().st_size})
        for name, body in original.items():
            (source / name).write_bytes(body)
        print({"arm": arm, "corpus": corpus, "trial": trial, "case": case,
               "update_ms": round(update_ms, 3)}, flush=True)
    write(destination / "result.json", {"rows": rows, "compile_ms": compile_ms,
                                        "python": sys.version, "sqlite": sqlite3.sqlite_version})


def run(repo, root):
    assert sha((root / "plan.json").read_bytes()) == (root / "plan.sha256").read_text()
    plan = json.loads((root / "plan.json").read_text())
    assert hashes(root / "champion") == plan["champion_hashes"]
    for name, expected in plan["source_hashes"].items():
        assert sha((root / "sources" / name).read_bytes()) == expected
    candidate = snapshot(repo, root / "candidate")
    write(root / "candidate.json", {"hashes": candidate, "runner_sha256": sha(Path(__file__).read_bytes())})
    jobs = [(corpus, trial) for corpus in plan["corpora"] for trial in range(plan["trials"])]
    rng = random.Random(plan["seed"])
    for corpus, trial in jobs:
        arms = ["champion", "candidate"]
        rng.shuffle(arms)
        for arm in arms:
            subprocess.run([sys.executable, "-u", str(Path(__file__).resolve()), "--root", str(root),
                            "--worker", arm, corpus, str(trial)], check=True)
    assert hashes(repo) == candidate
    rows = [row for p in sorted((root / "workers").glob("*/result.json"))
            for row in json.loads(p.read_text())["rows"]]
    groups = {(r["arm"], r["corpus"], r["trial"], r["case"]): r for r in rows}
    summary = []
    for corpus in plan["corpora"]:
        for case in plan["cases"]:
            before, after = [], []
            for trial in range(plan["trials"]):
                a, b = [groups[(arm, corpus, trial, case)] for arm in ("champion", "candidate")]
                assert a["evidence"] == b["evidence"], "cross-version evidence changed"
                before.append(a["update_ms"])
                after.append(b["update_ms"])
            summary.append({"corpus": corpus, "case": case,
                            "champion_median_ms": statistics.median(before),
                            "candidate_median_ms": statistics.median(after),
                            "ratio": statistics.median(before)/statistics.median(after)})
    write(root / "results.json", {"status": "COMPLETE", "plan_sha256": sha((root / "plan.json").read_bytes()),
                                  "candidate_hashes": candidate, "rows": rows, "summary": summary})
    print(summary, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--champion-root", type=Path)
    parser.add_argument("--worker", nargs=3)
    args = parser.parse_args()
    root = args.root.resolve()
    repo = Path(__file__).resolve().parents[1]
    if args.prepare:
        prepare(repo, root, args.champion_root.resolve() if args.champion_root else None)
    elif args.worker:
        arm, corpus, trial = args.worker
        worker(root, arm, corpus, int(trial))
    else:
        run(repo, root)


if __name__ == "__main__":
    main()

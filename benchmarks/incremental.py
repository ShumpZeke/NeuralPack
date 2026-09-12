"""Controlled source/index experiment including a simple persistent file-level baseline.

No inference speed claim follows from this benchmark. CPU benchmark should not overlap
GPU experiments because both use the same host resources.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import random
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from npk.compiler import compile_pack, update_pack
from npk.format import query_pack, verify_pack
from npk.optimizer import pareto_frontier


def clocked(fn):
    start = time.perf_counter_ns()
    result = fn()
    return result, (time.perf_counter_ns() - start) / 1e6


def build_fixture(root, files=96, blocks=48):
    """Synthetic mixed source with repeated boilerplate and unique searchable facts."""
    root.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        suffix = ".py" if i % 2 == 0 else ".md"
        contents = []
        if suffix == ".py":
            contents.append(f"# module_{i:04d} source provenance anchorunit{i:04d}\nimport json\n")
        else:
            contents.append(f"# Manual {i:04d} anchorunit{i:04d}\n")
        for j in range(blocks):
            if suffix == ".py":
                contents.append(f"\ndef operation_{j:04d}(value):\n    \"\"\"Validate input and preserve exact source provenance.\"\"\"\n"
                                f"    marker = 'unit{i:04d}section{j:04d}'\n    return {{'marker': marker, 'value': value, 'limit': {1000+j}}}\n")
            else:
                contents.append(f"\n## Section {j:04d}\nMarker unit{i:04d}section{j:04d} identifies this section.\n"
                                "The service must preserve tenant isolation, instruction priority, exact numerical limits, "
                                f"and source provenance. The configured limit is {1000+j}.\n")
        (root / f"unit_{i:04d}{suffix}").write_text("".join(contents), encoding="utf-8")
    # One large document makes line insertion a nontrivial chunk-boundary challenge.
    long_text = "# Long technical manual anchorlongmanual\n" + "".join(
        f"\nSection {j}: sentinel{j:06d}. Preserve grounding and instruction order. Limit {j+1000}.\n"
        for j in range(blocks * 100))
    (root / "long_manual.md").write_text(long_text, encoding="utf-8")
    (root / "dependencies.json").write_text('{"library": "1.0.0", "runtime": "python"}\n')
    (root / "conversation.md").write_text("# Agent history\nUser: preserve exact numbers.\nTool: limit=1001.\n")


def mutate(root, operation):
    path = root / "long_manual.md"
    original = path.read_bytes()
    if operation == "no_change":
        return 0
    if operation == "one_line_edit":
        revised = original.replace(b"Limit 1020.", b"Limit 1021.", 1)
        path.write_bytes(revised)
        return 1
    if operation == "insert_front":
        inserted = b"An inserted instruction must preserve the rest of this document.\n"
        path.write_bytes(inserted + original)
        return len(inserted)
    if operation == "append":
        added = b"\nAppend-only update: approved count is 19.\n"
        path.write_bytes(original + added)
        return len(added)
    if operation == "new_file":
        added = b"# New document\nThe revision identifier is 7001.\n"
        (root / "added.md").write_bytes(added)
        return len(added)
    if operation == "deleted_file":
        target = root / "unit_0000.py"
        size = target.stat().st_size
        target.unlink()
        return size
    if operation == "dependency_change":
        target = root / "dependencies.json"
        target.write_bytes(target.read_bytes().replace(b"1.0.0", b"2.0.0"))
        return 1
    if operation == "major_refactor":
        changed = 0
        for target in root.glob("*.py"):
            before = target.read_bytes()
            target.write_bytes(before.replace(b"operation_", b"procedure_"))
            changed += before.count(b"operation_")
        return changed
    raise ValueError(operation)


def file_index(source, db_path):
    """Strong simple control: reindex only changed files, with exact source hashing."""
    scanned = rebuilt = 0
    start = time.perf_counter_ns()
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT NOT NULL)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(path UNINDEXED, content)")
        existing = dict(db.execute("SELECT path, hash FROM files"))
        paths = set()
        for path in sorted(source.iterdir()):
            data = path.read_bytes()
            scanned += len(data)
            name = path.name
            paths.add(name)
            digest = hashlib.sha256(data).hexdigest()
            if existing.get(name) == digest:
                continue
            db.execute("DELETE FROM search WHERE path=?", (name,))
            db.execute("INSERT INTO search VALUES(?,?)", (name, data.decode("utf-8")))
            db.execute("INSERT OR REPLACE INTO files VALUES(?,?)", (name, digest))
            rebuilt += len(data)
        for name in existing.keys() - paths:
            db.execute("DELETE FROM search WHERE path=?", (name,))
            db.execute("DELETE FROM files WHERE path=?", (name,))
        db.commit()
    return {"wall_ms": (time.perf_counter_ns() - start) / 1e6, "source_bytes_scanned": scanned,
            "indexed_bytes_rebuilt": rebuilt, "file_size_bytes": db_path.stat().st_size}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="experiments/results/incremental")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--files", type=int, default=96)
    parser.add_argument("--blocks", type=int, default=48)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "raw.jsonl").exists():
        raise SystemExit("Refusing to overwrite existing raw measurements")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True).stdout.strip()
    (output / "config.json").write_text(json.dumps({**vars(args), "git_commit": commit,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seed": 1729, "workload": "synthetic mixed files, not real-repository generalization",
        "page_cache": "warm/uncontrolled", "neural_compute": "not measured"}, indent=2))
    candidates = [(kind, size) for kind in ("fixed", "cdc") for size in (1024, 4096, 16384)]
    operations = ("no_change", "one_line_edit", "insert_front", "append", "new_file", "deleted_file", "dependency_change", "major_refactor")
    randomizer = random.Random(1729)
    rows = []
    with tempfile.TemporaryDirectory(prefix="npk-incremental-", dir=output) as temp:
        workspace = Path(temp)
        base = workspace / "base"
        build_fixture(base, args.files, args.blocks)
        source_bytes = sum(path.stat().st_size for path in base.iterdir())
        for trial in range(args.trials):
            order = list(candidates)
            randomizer.shuffle(order)
            for kind, size in [*order, ("file_index", 0)]:
                candidate = f"{kind}-{size}" if size else kind
                store = workspace / f"base-{candidate}-{trial}.npk"
                compile_fn = (lambda: file_index(base, store)) if not size else (
                    lambda: compile_pack(base, store, chunking=kind, target_size=size))
                compiled, compile_ms = clocked(compile_fn)
                for operation in operations:
                    source = workspace / "current"
                    if source.exists():
                        resolved = source.resolve()
                        if source.is_symlink() or resolved.parent != workspace.resolve() or resolved.name != "current":
                            raise ValueError("Refusing cleanup outside the private benchmark directory")
                        shutil.rmtree(resolved)
                    shutil.copytree(base, source)
                    working = workspace / "current.npk"
                    shutil.copy2(store, working)
                    changed_bytes = mutate(source, operation)
                    fn = (lambda: file_index(source, working)) if not size else (lambda: update_pack(working, source))
                    metrics, update_ms = clocked(fn)
                    verified = True
                    if size:
                        verify_pack(working)
                    query = "anchorlongmanual"
                    if size:
                        hits, query_ms = clocked(lambda: query_pack(working, query, limit=5))
                        retrieval_passed = "long_manual.md" in json.dumps(hits)
                    else:
                        with closing(sqlite3.connect(working)) as db:
                            hits, query_ms = clocked(lambda: db.execute(
                                "SELECT path FROM search WHERE search MATCH ? ORDER BY rank LIMIT 5", (query,)).fetchall())
                        retrieval_passed = ("long_manual.md",) in hits
                    # Full rebuilding the same candidate is the matched cold preprocessing control.
                    full_store = workspace / "full.npk"
                    full_store.unlink(missing_ok=True)
                    full_fn = (lambda: file_index(source, full_store)) if not size else (
                        lambda: compile_pack(source, full_store, chunking=kind, target_size=size))
                    _, full_ms = clocked(full_fn)
                    row = {"candidate": candidate, "trial": trial, "operation": operation,
                        "source_bytes": source_bytes, "edit_bytes_lower_bound": changed_bytes,
                        "compile_ms": compile_ms, "update_ms": update_ms, "full_rebuild_ms": full_ms,
                        "query_ms": query_ms, "storage_bytes": working.stat().st_size,
                        "query_scope": "open+full validation+query" if size else "existing connection+query; no full integrity scan",
                        "retrieval_passed": retrieval_passed, "verified": verified, "metrics": metrics,
                        "compile_metrics": compiled}
                    rows.append(row)
                    with (output / "raw.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row) + "\n")
                print(json.dumps({"candidate": candidate, "trial": trial, "complete": True}), flush=True)
    summary = []
    for name in sorted({row["candidate"] for row in rows}):
        group = [row for row in rows if row["candidate"] == name]
        summary.append({"candidate": name, "median_update_ms": statistics.median(row["update_ms"] for row in group),
            "median_compile_ms": statistics.median(row["compile_ms"] for row in group),
            "median_storage_bytes": statistics.median(row["storage_bytes"] for row in group),
            "retrieval_fixture_pass_fraction": statistics.mean(row["retrieval_passed"] for row in group),
            "rows": len(group)})
    frontier = pareto_frontier(summary, ("median_update_ms", "median_compile_ms", "median_storage_bytes"), ("retrieval_fixture_pass_fraction",))
    (output / "summary.json").write_text(json.dumps({"candidates": summary, "pareto_frontier": frontier,
        "warning": "Aggregate across heterogeneous mutations; inspect per-operation raw results before selection. This is a parameter sweep, not open-ended evolution."}, indent=2))


if __name__ == "__main__":
    main()

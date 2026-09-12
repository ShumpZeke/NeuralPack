"""Deletion-only algorithm diagnostic: paired in-memory backups and SQLite work.

This isolates index cleanup plus file cascades. It excludes source scanning,
replacement compilation, hashing, commit/fsync, and query time. No end-to-end
claim follows from a speedup here. The paired end-to-end experiment is separate.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys
import time


def worker(root, arm, corpus, fraction, trial, rebuild=False):
    sys.path.insert(0, str(root / arm))
    compiler = importlib.import_module("npk.pack.compile")
    if rebuild:
        destination = root/"rebuild-cost"/f"{corpus}-{fraction}-{trial}"
        destination.mkdir(parents=True)
        source = destination/"source"
        shutil.copytree(root/"sources"/corpus, source)
        names = sorted(p for p in source.rglob("*") if p.is_file())
        count = len(names) if fraction == "all" else max(1, len(names)//10)
        for path in names[:count]:
            path.write_bytes(path.read_bytes()+b"\n# changed_partition marker\n")
        start = time.perf_counter_ns()
        cpu = time.process_time_ns()
        compiler.compile_pack(source, destination/"fresh.npk")
        row = {"corpus": corpus, "case": fraction, "trial": trial,
               "cpu_ms": (time.process_time_ns()-cpu)/1e6,
               "wall_ms": (time.perf_counter_ns()-start)/1e6}
        from npk.pack import verify
        assert verify(destination/"fresh.npk")["ok"]
        print(json.dumps(row), flush=True)
        return
    path = root/"workers"/f"champion-{corpus}-0"/"base.npk"
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    origin = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)
    origin.backup(con)
    origin.close()
    ids = [r[0] for r in con.execute("SELECT id FROM files ORDER BY path")]
    count = 1 if fraction == "one" else max(1, len(ids)//10) if fraction == "ten_percent" else len(ids)
    selected = ids[:count]
    ticks = 0
    def tick():
        nonlocal ticks
        ticks += 1
        return 0
    con.execute("BEGIN")
    con.set_progress_handler(tick, 100)
    start = time.perf_counter_ns()
    cpu = time.process_time_ns()
    if arm == "candidate":
        compiler._drop_lexical(con, selected)
    for file_id in selected:
        compiler._drop_file(con, file_id)
    cpu_ms = (time.process_time_ns()-cpu)/1e6
    wall_ms = (time.perf_counter_ns()-start)/1e6
    con.set_progress_handler(None, 0)
    assert con.execute("SELECT count(*) FROM files").fetchone()[0] == len(ids)-count
    assert con.execute("SELECT count(*) FROM lexical").fetchone()[0] == con.execute("SELECT count(*) FROM blocks").fetchone()[0]
    con.close()
    print(json.dumps({"arm": arm, "corpus": corpus, "case": fraction, "trial": trial,
                      "deleted_files": count, "wall_ms": wall_ms, "cpu_ms": cpu_ms,
                      "sqlite_progress_ticks_100": ticks}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", nargs=4)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--audit-query", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.audit_query:
        rows = []
        queries = {
            "repeated_join": "SELECT count(*) FROM blocks b LEFT JOIN lexical l ON b.id=l.block_id WHERE l.block_id IS NULL",
            "set_membership": "SELECT count(*) FROM blocks WHERE id NOT IN (SELECT block_id FROM lexical WHERE block_id IS NOT NULL)",
        }
        for size in (100, 1000):
            con = sqlite3.connect(":memory:")
            con.executescript("CREATE TABLE blocks(id INTEGER PRIMARY KEY); CREATE VIRTUAL TABLE lexical USING fts5(block_id UNINDEXED,content);")
            con.executemany("INSERT INTO blocks VALUES(?)", ((i,) for i in range(size)))
            con.executemany("INSERT INTO lexical(block_id,content) VALUES(?,?)", ((i, "source value") for i in range(size)))
            con.commit()
            for missing in (False, True):
                if missing:
                    con.execute("DELETE FROM lexical WHERE block_id=0")
                for trial in range(3):
                    for name in (list(queries) if trial % 2 == 0 else list(queries)[::-1]):
                        ticks = [0]
                        def tick():
                            ticks[0] += 1
                            return 0
                        con.set_progress_handler(tick, 100)
                        start = time.perf_counter_ns()
                        result = con.execute(queries[name]).fetchone()[0]
                        elapsed = (time.perf_counter_ns()-start)/1e6
                        con.set_progress_handler(None, 0)
                        assert result == int(missing)
                        rows.append({"case": name, "rows": size, "missing": missing, "trial": trial,
                                     "wall_ms": elapsed, "sqlite_progress_ticks_100": ticks[0]})
            con.close()
        args.output.write_text(json.dumps({"scope": "Synthetic missing-row SQL check only, not product runtime", "queries": queries, "rows": rows}, indent=2))
        return
    if args.worker:
        arm, corpus, fraction, trial = args.worker
        worker(root, arm, corpus, fraction, int(trial), args.rebuild)
        return
    order = [(arm, corpus, fraction, trial) for arm in ("champion", "candidate")
             for corpus in ("public", "synthetic") for fraction in ("one", "ten_percent", "all")
             for trial in range(3)]
    if args.rebuild:
        order = [job for job in order if job[0] == "candidate" and job[2] != "one"]
    random.Random(30902).shuffle(order)
    plan = {"jobs": order, "rebuild": args.rebuild,
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "parent_plan_sha256": hashlib.sha256((root/"plan.json").read_bytes()).hexdigest()}
    args.output.with_suffix(".plan.json").write_text(json.dumps(plan, indent=2))
    rows = []
    for arm, corpus, fraction, trial in order:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                                 "--worker", arm, corpus, fraction, str(trial)]+(["--rebuild"] if args.rebuild else []),
                                check=True, capture_output=True, text=True)
        rows.append(json.loads(result.stdout))
        print(rows[-1], flush=True)
    scope = "Clean compilation of the same edited sources, in a separate timing session; includes source scan and publication, excludes verification and source copying." if args.rebuild else __doc__
    args.output.write_text(json.dumps({"evidence_mode": "LOCAL", "scope": scope, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()

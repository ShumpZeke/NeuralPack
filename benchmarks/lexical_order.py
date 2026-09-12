"""LOCAL SQL ordering challengers; all stable variants must return identical IDs.

This isolates query execution on one artifact/connection with rotated method
order. It measures no answer quality and does not promote a query automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time

from benchmarks.compiled_corpus import build_corpus
from benchmarks.tasks_hard import build_task_suite
from npk.pack import compile_pack
from npk.pack.format import open_pack, read_manifest
from npk.pack.select import _content_terms


QUERIES = {
    "unstable_original": "SELECT block_id FROM lexical WHERE lexical MATCH ? ORDER BY bm25(lexical) LIMIT ?",
    "stable_join": (
        "SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid "
        "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
        "ORDER BY bm25(lexical),f.path COLLATE BINARY,b.ordinal LIMIT ?"),
    "stable_rank": (
        "SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid "
        "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
        "ORDER BY lexical.rank,f.path COLLATE BINARY,b.ordinal LIMIT ?"),
    "stable_materialized": (
        "WITH matched AS MATERIALIZED (SELECT block_id,bm25(lexical) score "
        "FROM lexical WHERE lexical MATCH ?) SELECT m.block_id FROM matched m "
        "JOIN blocks b ON b.id=m.block_id JOIN files f ON f.id=b.file_id "
        "ORDER BY m.score,f.path COLLATE BINARY,b.ordinal LIMIT ?"),
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    tasks=[t for t in build_task_suite(per_family=8,filler_tokens=15000,corpus="real") if t.split=="sealed"]
    records=[]
    with tempfile.TemporaryDirectory(prefix="npk-sql-order-") as tmp:
        root=Path(tmp)
        source=build_corpus(root,tasks)
        pack=root/"test.npk"
        compile_pack(source,pack)
        corpus_manifest=[{"path":p.relative_to(source).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(source.rglob("*")) if p.is_file()]
        with open_pack(pack) as con:
            available=int(read_manifest(con)["available_tokens"])
            names=list(QUERIES)
            plans={name:[tuple(r) for r in con.execute("EXPLAIN QUERY PLAN "+sql,('"retry"',60))]
                   for name,sql in QUERIES.items()}
            for repeat in range(4):
                for i,task in enumerate(tasks):
                    match=" OR ".join('"'+term+'"' for term in _content_terms(task.query))
                    offset=(i+repeat)%len(names)
                    expected=[r[0] for r in con.execute(QUERIES["stable_join"],(match,60))]
                    for name in names[offset:]+names[:offset]:
                        start=time.perf_counter()
                        ids=[r[0] for r in con.execute(QUERIES[name],(match,60))]
                        ms=(time.perf_counter()-start)*1000
                        if name!="unstable_original" and ids!=expected:
                            raise RuntimeError(f"stable order changed: {name}, {task.id}")
                        records.append({"repeat":repeat,"task":task.id,"query":task.query,"method":name,
                                        "ms":ms,"matches_stable_order":ids==expected,"ids":ids})
    summary=[]
    for name in QUERIES:
        rows=[r for r in records if r["method"]==name and r["repeat"]>0]
        summary.append({"method":name,"samples":len(rows),"warm_median_ms":statistics.median(r["ms"] for r in rows),
                        "stable_matches":sum(r["matches_stable_order"] for r in rows)})
    result={"evidence_mode":"LOCAL","generative_api_calls":0,"available_tokens":available,
            "sqlite_version":sqlite3.sqlite_version,"sql":QUERIES,"plans":plans,"summary":summary,
            "corpus_manifest":corpus_manifest,"rows":records,
            "harness_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "limitations":["Previously inspected correlated templates, not answer quality",
                           "Same-connection query microbenchmark, not full public runtime latency",
                           "Stable reference query executed first to validate each result; all methods warm"]}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()

"""Logical equality of two packs, ignoring only build-time metadata.

    python -m benchmarks.npkbench.equivalence A.npk B.npk

Compares every stored table row (including FTS5 instance postings and document
sizes) except wall-clock timestamps, the source root path, and digests that
cover those timestamps. Used to prove that a performance change to the
compiler leaves artifact contents unchanged on real repositories.
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List

IGNORED_MANIFEST = {"created_utc", "updated_utc", "root_sha256", "source_root"}
TABLE_QUERIES = {
    "files": "SELECT id,path,sha256,size,language FROM files ORDER BY id",
    "blocks": "SELECT id,file_id,ordinal,kind,name,start_line,end_line,tokens,sha256,text,path FROM blocks ORDER BY id",
    "symbols": "SELECT name,block_id,kind,is_def FROM symbols ORDER BY block_id,name,kind",
    "relations": "SELECT block_id,kind,name FROM relations ORDER BY block_id,kind,name",
    "assignments": "SELECT symbol,block_id,value_hash FROM assignments ORDER BY block_id,symbol,value_hash",
    "deps": "SELECT src_block_id,dst_block_id,kind FROM deps ORDER BY 1,2,3",
    "embeddings": "SELECT block_id,dim,vector FROM embeddings ORDER BY block_id",
    "provenance": "SELECT file_id,source_uri FROM provenance ORDER BY file_id",
    "lexical_docsize": "SELECT id,sz FROM lexical_docsize ORDER BY id",
    "lexical_config": "SELECT k,v FROM lexical_config ORDER BY k",
}


def _digest(con: sqlite3.Connection, sql: str) -> str:
    h = hashlib.sha256()
    for row in con.execute(sql):
        h.update(repr(tuple(row)).encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def fingerprint(path: Path) -> Dict[str, str]:
    con = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    try:
        out = {name: _digest(con, sql) for name, sql in TABLE_QUERIES.items()}
        con.execute("CREATE TEMP TABLE _ignore(x)")  # temp schema only; artifact untouched
        con.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, lexical, 'instance')")
        out["lexical_postings"] = _digest(con, "SELECT term,doc,col,offset FROM temp.v ORDER BY 1,2,3,4")
        manifest = {k: v for k, v in con.execute("SELECT key,value FROM manifest")
                    if k not in IGNORED_MANIFEST}
        out["manifest"] = hashlib.sha256(repr(sorted(manifest.items())).encode()).hexdigest()
        return out
    finally:
        con.close()


def differences(a: Path, b: Path) -> List[str]:
    fa, fb = fingerprint(a), fingerprint(b)
    return sorted(k for k in fa if fa[k] != fb.get(k))


def main(argv: List[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    diff = differences(Path(argv[0]), Path(argv[1]))
    print("identical" if not diff else f"DIFFERENT tables: {diff}")
    return 1 if diff else 0


if __name__ == "__main__":
    raise SystemExit(main())

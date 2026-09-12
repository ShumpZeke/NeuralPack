"""Experimental per-file integrity leaves, outside the product artifact format.

CONJECTURE: rehashing changed files plus global index storage can reduce seal
cost. The cache here is transient and invalidated using known benchmark edits.
Production adoption would require durable, transactionally correct invalidation
for every mutation, a format migration, and independent corruption attacks.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import tempfile
import time

from benchmarks.integrity_challengers import encode
from npk.pack import update_pack, verify
from npk.pack.format import compute_root_digest, connect

LOCAL_TABLES=("files","provenance","blocks","symbols","relations","embeddings","assignments")
GLOBAL_TABLES=("manifest","deps","lexical_data","lexical_idx","lexical_docsize","lexical_config",
               "integrity_files","integrity_dirty")


def feed_rows(digest,rows):
    for row in rows:
        digest.update(encode(len(row))+b"".join(encode(value) for value in row))


def rows(con,table,where="",parameters=()):
    columns=con.execute(f'SELECT * FROM "{table}" LIMIT 0').description
    order=",".join(str(i+1) for i in range(len(columns)))
    return con.execute(f'SELECT * FROM "{table}" {where} ORDER BY {order}',parameters)


def file_leaf(con,file_id):
    digest=hashlib.sha256(b"npk-experimental-file-leaf\0")
    for table in LOCAL_TABLES:
        digest.update(encode(table))
        if table=="files":where="WHERE id=?"
        elif table in {"provenance","blocks"}:where="WHERE file_id=?"
        else:where="WHERE block_id IN (SELECT id FROM blocks WHERE file_id=?)"
        feed_rows(digest,rows(con,table,where,(file_id,)))
    return digest.digest()


def full_leaves(con):
    return {r[0]:file_leaf(con,r[0]) for r in con.execute("SELECT id FROM files ORDER BY id")}


def root_digest(con,leaves):
    digest=hashlib.sha256(b"npk-experimental-file-root\0")
    feed_rows(digest,con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name"))
    for table in GLOBAL_TABLES:
        digest.update(encode(table))
        feed_rows(digest,rows(con,table,"WHERE key != 'root_sha256'" if table=="manifest" else ""))
    for file_id,value in sorted(leaves.items()):
        digest.update(encode(file_id)+encode(value))
    return digest.hexdigest()


def refreshed(con,leaves,changed_paths):
    current={r["id"]:r["path"] for r in con.execute("SELECT id,path FROM files")}
    return {file_id:file_leaf(con,file_id) if file_id not in leaves or path in changed_paths else leaves[file_id]
            for file_id,path in current.items()}


def timed(fn):
    start=time.perf_counter();result=fn()
    return result,(time.perf_counter()-start)*1000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError("new output required")
    plan=json.loads((args.run/"plan.json").read_text())
    source=args.run/"source/click-8.5.0";original=args.run/"bm25_windows.npk"
    with tempfile.TemporaryDirectory(prefix="npk-leaf-hypothesis-") as tmp:
        root=Path(tmp);base=root/"base";base.mkdir()
        for item in plan["source_manifest"]:
            path=source/item["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:raise RuntimeError("source changed")
            target=base/item["path"];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        with closing(connect(original,readonly=True)) as con:
            leaves,leaf_build_ms=timed(lambda:full_leaves(con))
        measurements=[]
        for label,paths in (("small_file",["src/click/globals.py"]),("large_file",["src/click/core.py"]),
                            ("ten_percent",[i["path"] for i in plan["source_manifest"][:11]])):
            work=root/label;shutil.copytree(base,work)
            pack=root/(label+".npk");shutil.copyfile(original,pack)
            for path in paths:
                target=work/path;target.write_bytes(target.read_bytes()+b"\n# leaf experiment edit\n")
            update_pack(pack,work)
            if not verify(pack)["ok"]:raise RuntimeError("existing updater produced invalid artifact")
            with closing(connect(pack,readonly=True)) as con:
                expected=root_digest(con,full_leaves(con))
                for trial in range(5):
                    def incremental():return root_digest(con,refreshed(con,leaves,set(paths)))
                    methods=[("current_v4_seal",lambda:compute_root_digest(con)),
                             ("known_dirty_file_leaves",incremental)]
                    if trial%2:methods.reverse()
                    for name,fn in methods:
                        value,elapsed=timed(fn)
                        if name!="current_v4_seal" and value!=expected:raise RuntimeError("incremental leaf root differs from full recomputation")
                        measurements.append({"edit":label,"changed_paths":paths,"trial":trial,"method":name,"ms":elapsed})
        summary=[{"edit":edit,"method":method,"median_ms":statistics.median(r["ms"] for r in measurements if r["edit"]==edit and r["method"]==method)}
                 for edit in sorted({r["edit"] for r in measurements})
                 for method in ("current_v4_seal","known_dirty_file_leaves")]
    args.output.write_text(json.dumps({"evidence_mode":"LOCAL","generative_calls":0,"available_tokens":plan["available_tokens"],
                                      "benchmark_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                      "initial_leaf_ms":leaf_build_ms,"rows":measurements,"summary":summary,
                                      "limitations":["Different experimental digest, not format-4 compatible and not integrated into production",
                                                     "Seal stage only; source scanning/indexing/commits are excluded",
                                                     "Dirty paths supplied by known experiment edits; no general invalidation implementation",
                                                     "Transient cache; no durable migration, crash recovery or authentication claim",
                                                     "Background LIVE requests may overlap; warm filesystem cache"]},indent=2))
    print(json.dumps(summary,indent=2))


if __name__=="__main__":main()

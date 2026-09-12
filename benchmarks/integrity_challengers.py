"""LOCAL v4-compatible digest challengers. No production implementation change.

Every candidate must reproduce the full existing digest, including schema and
FTS storage. Batching changes hash-call boundaries, not serialized byte order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import time

from npk.pack.format import PackError, compute_root_digest, open_pack

TABLES=("manifest","files","blocks","symbols","deps","embeddings","provenance","assignments",
        "lexical_data","lexical_idx","lexical_docsize","lexical_config")


def encode(value):
    if value is None:
        tag,data=b"n",b""
    elif isinstance(value,bytes):
        tag,data=b"b",value
    elif isinstance(value,int):
        tag,data=b"i",str(value).encode("ascii")
    elif isinstance(value,str):
        tag,data=b"s",value.encode("utf-8")
    else:
        raise PackError("unexpected value type in artifact")
    return tag+len(data).to_bytes(8,"big")+data


def candidate_digest(con,*,buffered=False,cache_ints=False):
    digest=hashlib.sha256(b"npk-integrity-v4\0")
    pending=bytearray();integers={}
    def framed(value):
        if not cache_ints or type(value) is not int:
            return encode(value)
        value_bytes=integers.get(value)
        if value_bytes is None:
            value_bytes=encode(value)
            if len(integers)<4096:
                integers[value]=value_bytes
        return value_bytes
    def feed_row(row,prefix=b""):
        encoded=prefix+b"".join(framed(value) for value in row)
        if buffered:
            pending.extend(encoded)
            if len(pending)>=65536:
                digest.update(pending);pending.clear()
        else:
            digest.update(encoded)
    for row in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name"):
        feed_row(row)
    for table in TABLES:
        feed_row([table])
        columns=con.execute(f'SELECT * FROM "{table}" LIMIT 0').description
        order=",".join(str(i+1) for i in range(len(columns)))
        where=" WHERE key != 'root_sha256'" if table=="manifest" else ""
        prefix=encode(len(columns))
        for row in con.execute(f'SELECT * FROM "{table}"{where} ORDER BY {order}'):
            feed_row(row,prefix)
    digest.update(pending)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packs",nargs="+",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--trials",type=int,default=5)
    args=parser.parse_args()
    if args.output.exists() or args.trials<1:
        raise ValueError("new output path and positive trial count required")
    variants={"champion":compute_root_digest,"row_batch":candidate_digest,
              "buffered":lambda con:candidate_digest(con,buffered=True),
              "buffered_int_cache":lambda con:candidate_digest(con,buffered=True,cache_ints=True)}
    rng=random.Random(214);rows=[]
    for path in args.packs:
        with open_pack(path) as con:
            expected=compute_root_digest(con)
            for trial in range(args.trials):
                order=list(variants);rng.shuffle(order)
                for name in order:
                    started=time.perf_counter();root=variants[name](con);elapsed=(time.perf_counter()-started)*1000
                    if root!=expected:
                        raise RuntimeError("candidate changed the artifact digest")
                    rows.append({"pack":path.name,"trial":trial,"method":name,"ms":elapsed,"root":root})
    summary=[{"pack":p,"method":m,"median_ms":statistics.median(r["ms"] for r in rows if r["pack"]==p and r["method"]==m)}
             for p in sorted({r["pack"] for r in rows}) for m in variants]
    args.output.write_text(json.dumps({"evidence_mode":"LOCAL","rows":rows,"summary":summary,
                                      "benchmark_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                      "limitations":["Digest microbenchmark; not whole compile/update timing",
                                                     "Warm/uncontrolled page cache; same machine with background LIVE requests",
                                                     "Digest equality on these artifacts is evidence, not a universal proof"]},indent=2))
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()

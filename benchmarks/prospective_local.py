"""LOCAL compile/update costs on the frozen prospective source collection.

Each edit starts from an independent copy of the same baseline. Appending a
comment measures small source edits, not semantic refactors or invalidation
of a dependency index (disabled). The frozen LIVE contexts are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import tempfile
import time

from npk.pack import PackSelector, compile_pack, update_pack, verify


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timed(operation):
    start=time.perf_counter()
    result=operation()
    return result,(time.perf_counter()-start)*1000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--trials",type=int,default=3)
    args=parser.parse_args()
    if args.trials<1 or args.output.exists():
        raise ValueError("positive trials and a new output path required")
    plan_path=args.run/"plan.json"
    plan=json.loads(plan_path.read_text())
    if digest(plan_path)!=(args.run/"plan.sha256").read_text().strip():
        raise ValueError("frozen plan changed")
    origin=args.run/"source/click-8.5.0"
    source_files=plan["source_manifest"]
    for item in source_files:
        if digest(origin/item["path"])!=item["sha256"]:
            raise ValueError("source changed")
    repo=Path(__file__).resolve().parents[1]
    code={p.relative_to(repo).as_posix():digest(p) for p in (repo/"npk").rglob("*.py")}
    os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
    os.environ["HF_HUB_CACHE"]=str(repo/"experiments/models/hf_cache")
    rng=random.Random(20260906)
    paths=sorted(i["path"] for i in source_files);rng.shuffle(paths)
    rows=[]
    with tempfile.TemporaryDirectory(prefix="npk-prospective-local-") as temp:
        root=Path(temp)
        base=root/"base";base.mkdir()
        for item in source_files:
            target=base/item["path"];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(origin/item["path"],target)
        configurations=[("bm25_windows",False,"deterministic","lexical"),
                        ("bm25_members",True,"deterministic","lexical"),
                        ("hybrid_members",True,"semantic","hybrid")]
        for trial in range(args.trials):
            order=list(configurations);rng.shuffle(order)
            for name,members,mode,retrieval in order:
                pack=root/f"{name}-{trial}.npk"
                options={"python_members":members,"mode":mode}
                stats,compile_ms=timed(lambda:compile_pack(base,pack,**options))
                if mode=="semantic" and stats.embedded!=stats.blocks:
                    raise RuntimeError("semantic index incomplete")
                selector=PackSelector(pack,retrieval=retrieval)
                queries=[t["question"] for t in plan["dataset"]["tasks"]]
                first,first_ms=timed(lambda:selector.select(queries[0],budget_tokens=2048))
                query_ms=[]
                for _ in range(3):
                    for query in queries:
                        result,elapsed=timed(lambda:selector.select(query,budget_tokens=2048))
                        if result.seed_failed or not result.evidence or result.total_tokens>2048:
                            raise RuntimeError("query contract failed")
                        query_ms.append(elapsed)
                checked,verify_ms=timed(lambda:verify(pack))
                if not checked["ok"]:
                    raise RuntimeError("artifact failed integrity verification")
                before=digest(pack)
                noop,noop_ms=timed(lambda:update_pack(pack,base))
                if noop.files_indexed or noop.files_removed or digest(pack)!=before:
                    raise RuntimeError("no-change update modified artifact")
                updates=[]
                for label,count in (("single_file",1),("one_percent",math.ceil(len(paths)*.01)),
                                    ("ten_percent",math.ceil(len(paths)*.10))):
                    changed=root/f"source-{name}-{trial}-{label}"
                    shutil.copytree(base,changed)
                    working=root/f"update-{name}-{trial}-{label}.npk"
                    shutil.copyfile(pack,working)
                    selected_paths=paths[:count]
                    for path in selected_paths:
                        with (changed/path).open("ab") as stream:
                            stream.write(b"\n# local incremental measurement marker\n")
                    updated,update_ms=timed(lambda:update_pack(working,changed))
                    if updated.files_indexed!=count or not verify(working)["ok"]:
                        raise RuntimeError("update touched unexpected files or invalidated integrity")
                    updates.append({"operation":label,"changed_files":count,"file_fraction":count/len(paths),
                                    "changed_paths":selected_paths,"update_ms":update_ms,"stats":updated.as_dict()})
                import psutil
                memory=psutil.Process().memory_info()._asdict()
                row={"method":name,"trial":trial,"compile_ms":compile_ms,"stats":stats.as_dict(),
                     "disk_bytes":pack.stat().st_size,"verify_ms":verify_ms,"noop_ms":noop_ms,
                     "first_query_ms":first_ms,"warm_query_ms":query_ms,
                     "warm_median_ms":statistics.median(query_ms),
                     "warm_p95_ms":sorted(query_ms)[math.ceil(.95*len(query_ms))-1],
                     "process_rss_bytes":memory["rss"],"process_peak_bytes":memory.get("peak_wset"),
                     "updates":updates}
                rows.append(row)
                print({k:row[k] for k in ("method","trial","compile_ms","warm_median_ms")},flush=True)
    for path,sha in code.items():
        if digest(repo/path)!=sha:
            raise RuntimeError("measured implementation changed")
    report={"evidence_mode":"LOCAL","generative_calls":0,"plan_sha256":digest(plan_path),
            "available_tokens":plan["available_tokens"],"source_manifest":source_files,"code_sha256":code,
            "benchmark_sha256":digest(Path(__file__)),"rows":rows,
            "limitations":["One machine; warm/uncontrolled filesystem and encoder caches",
                           "Source edits append comments, not representative semantic refactors",
                           "Process memory is cumulative across configurations, not per-method isolated RAM",
                           "Background LIVE network requests may overlap; no simultaneous CPU benchmark or test suite",
                           "First query follows compilation, so it is not a fresh-process cold-start measurement",
                           "No dollar price or answer-quality inference follows from these local timings"]}
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()

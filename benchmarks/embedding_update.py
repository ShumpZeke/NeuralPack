"""Paired LOCAL incremental-embedding costs on real urllib3 source.

No generative models or answer grading. Source copies are disposable. Identical
operations are run in isolated processes against champion and candidate code.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def timed(function):
    start=time.perf_counter()
    value=function()
    return value,(time.perf_counter()-start)*1000


def capture(pack,questions):
    from npk.pack import PackSelector,verify
    from npk.pack.format import open_pack
    if not verify(pack)["ok"]:
        raise RuntimeError("artifact failed integrity validation")
    with open_pack(pack) as con:
        source_rows=[tuple(r) for r in con.execute(
            "SELECT f.path,b.ordinal,b.start_line,b.end_line,b.text FROM blocks b "
            "JOIN files f ON b.file_id=f.id ORDER BY f.path,b.ordinal")]
        vectors={(r["path"],r["ordinal"]):(r["dim"],r["vector"]) for r in con.execute(
            "SELECT f.path,b.ordinal,e.dim,e.vector FROM blocks b JOIN files f ON b.file_id=f.id "
            "JOIN embeddings e ON e.block_id=b.id")}
    queries=[]
    for budget in (800,2000,4000):
        for question in questions:
            selected=PackSelector(pack,retrieval="hybrid").select(question,budget_tokens=budget)
            if selected.total_tokens>budget:
                raise RuntimeError("query exceeded budget")
            queries.append({"question":question,"budget":budget,"selected_tokens":selected.total_tokens,
                            "seed_failed":selected.seed_failed,
                            "evidence":[{"span":e.span,"sha256":hashlib.sha256(e.text.encode()).hexdigest()} for e in selected.evidence]})
    return source_rows,vectors,queries


def worker(args):
    sys.path.insert(0,str(Path(args.implementation).resolve()))
    from npk.pack import compile_pack,update_pack,verify
    from npk.context.embedding import get_backend
    from npk.pack.format import open_pack,read_manifest
    import numpy as np
    import psutil
    root=Path(args.work)
    source=root/"source"
    base=Path(args.source)
    shutil.copytree(base,source)
    backend=get_backend()
    _,load_ms=timed(lambda:backend.available())
    if not backend.available():
        raise RuntimeError("local encoder unavailable")
    # Count actual rows submitted to the encoder API, independently of new stats.
    original_embed=backend.embed_matrix
    calls=[]
    def counted(texts):
        calls.append(len(texts))
        return original_embed(texts)
    backend.embed_matrix=counted
    questions=json.loads(Path(args.questions).read_text())
    records=[]
    for members in (False,True):
        for p in source.rglob("*.py"):
            p.unlink()
        for p in base.rglob("*.py"):
            target=source/p.relative_to(base);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target)
        pack=root/("members.npk" if members else "windows.npk")
        stats,compile_ms=timed(lambda:compile_pack(source,pack,mode="semantic",python_members=members))
        if not stats.embedded:
            raise RuntimeError("semantic compiler produced no vectors")
        baseline=pack.read_bytes()
        with open_pack(pack) as con:
            available=int(read_manifest(con)["available_tokens"])
        original=(source/"util/retry.py").read_text(encoding="utf-8")
        marker="DEFAULT_BACKOFF_MAX = 120"
        if original.count(marker)!=1:
            raise RuntimeError("pinned source edit is not unique")
        samples=[]
        for operation in ("one_constant","blank_lines","rename","remove_file"):
            repeat_rows=[]
            for iteration in range(args.repeats):
                pack.write_bytes(baseline)
                retry=source/"util/retry.py"
                renamed=source/"util/retry_renamed.py"
                if renamed.exists():
                    renamed.unlink()
                retry.write_text(original,encoding="utf-8")
                if operation=="one_constant":
                    retry.write_text(original.replace(marker,f"DEFAULT_BACKOFF_MAX = {121+iteration}"),encoding="utf-8")
                elif operation=="blank_lines":
                    retry.write_text("\n"*(iteration+1)+original,encoding="utf-8")
                elif operation=="rename":
                    retry.rename(renamed)
                elif operation=="remove_file":
                    retry.unlink()
                # Keep model weights warm but remove process-local vector memoization.
                backend._cache.clear()
                if hasattr(backend,"_cache_bytes"):
                    backend._cache_bytes=0
                calls.clear()
                updated,update_ms=timed(lambda:update_pack(pack,source))
                submitted=sum(calls)
                if not verify(pack)["ok"]:
                    raise RuntimeError("updated artifact failed verification")
                repeat_rows.append({"iteration":iteration,"ms":update_ms,"encoder_rows_requested":submitted,
                                    "stats":updated.as_dict()})
            updated_sources,updated_vectors,updated_queries=capture(pack,questions)
            backend._cache.clear()
            if hasattr(backend,"_cache_bytes"):
                backend._cache_bytes=0
            fresh=root/"fresh.npk"
            _,fresh_ms=timed(lambda:compile_pack(source,fresh,mode="semantic",python_members=members))
            fresh_sources,fresh_vectors,fresh_queries=capture(fresh,questions)
            if updated_sources!=fresh_sources or updated_vectors.keys()!=fresh_vectors.keys():
                raise RuntimeError("incremental source/vector coverage disagrees with fresh compilation")
            errors=[float(np.max(np.abs(np.frombuffer(vector,dtype="<f4")-
                                        np.frombuffer(fresh_vectors[key][1],dtype="<f4"))))
                    for key,(dim,vector) in updated_vectors.items()]
            if max(errors,default=0)>1e-5:
                raise RuntimeError("incremental vectors differ materially from fresh compilation")
            samples.append({"operation":operation,"samples":repeat_rows,
                            "median_ms":statistics.median(r["ms"] for r in repeat_rows),
                            "median_encoder_rows_requested":statistics.median(r["encoder_rows_requested"] for r in repeat_rows),
                            "fresh_compile_ms":fresh_ms,"source_rows_equal":True,"max_vector_abs_error":max(errors,default=0),
                            "exact_query_matches":sum(a==b for a,b in zip(updated_queries,fresh_queries)),
                            "query_comparisons":len(fresh_queries),"updated_queries":updated_queries,"fresh_queries":fresh_queries})
            # Restore the named path after the final sample before the next operation.
            renamed=source/"util/retry_renamed.py"
            if renamed.exists():
                renamed.unlink()
            (source/"util/retry.py").write_text(original,encoding="utf-8")
        records.append({"python_members":members,"available_tokens":available,"files":len(list(base.rglob('*.py'))),
                        "compile_ms_warm_encoder":compile_ms,"pack_bytes":len(baseline),"operations":samples,
                        "process_rss_bytes":psutil.Process().memory_info().rss})
    Path(args.output).write_text(json.dumps({"encoder_load_ms":load_ms,"records":records}),encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--implementation")
    parser.add_argument("--source")
    parser.add_argument("--questions")
    parser.add_argument("--work")
    parser.add_argument("--champion",default="857bc1f")
    parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    if args.worker:
        worker(args);return
    repo=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(repo))
    from benchmarks.repository_tasks import SOURCE,dataset
    data=dataset()
    code_hashes={p.relative_to(repo).as_posix():sha(p) for p in (repo/"npk").rglob("*.py")}
    result={"evidence_mode":"LOCAL","generative_api_calls":0,"champion":args.champion,
            "source_manifest":data["source_manifest"],"package":data["package"],"version":data["version"],
            "candidate_hashes":code_hashes,"limitations":["One library; curated source-derived queries",
              "Warm model weights; process tensor caches cleared before each update",
              "Queries verify incremental/fresh equivalence, not answer accuracy",
              "Float32 vector equality uses 1e-5 tolerance because batch composition changes rounding",
              "No dollar or answer-quality claim"]}
    with tempfile.TemporaryDirectory(prefix="npk-embedding-update-") as tmp:
        root=Path(tmp).resolve()
        source=root/"corpus";source.mkdir()
        for p in SOURCE.rglob("*.py"):
            dest=source/p.relative_to(SOURCE);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,dest)
        questions=root/"questions.json"
        questions.write_text(json.dumps([t["question"] for t in data["tasks"]]),encoding="utf-8")
        old=root/"champion";old.mkdir()
        with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(["git","archive",args.champion],cwd=repo))) as archive:
            archive.extractall(old,filter="data")
        for label,implementation in (("champion_result",old),("candidate_result",repo)):
            work=root/label;work.mkdir()
            output=work/"result.json"
            env=dict(os.environ,HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",TOKENIZERS_PARALLELISM="false",
                     HF_HUB_CACHE=str(repo/"experiments/models/hf_cache"))
            subprocess.run([sys.executable,str(Path(__file__).resolve()),"--worker","--implementation",str(implementation),
                            "--source",str(source),"--questions",str(questions),"--work",str(work),
                            "--repeats",str(args.repeats),"--output",str(output)],cwd=implementation,env=env,check=True)
            result[label]=json.loads(output.read_text())
            print(label,[{"members":r["python_members"],"operations":[{k:o[k] for k in
                  ("operation","median_ms","median_encoder_rows_requested","exact_query_matches","query_comparisons")}
                  for o in r["operations"]]} for r in result[label]["records"]],flush=True)
        if any(sha(repo/p)!=h for p,h in code_hashes.items()):
            raise RuntimeError("candidate changed during measurement")
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(gzip.compress(json.dumps(result,sort_keys=True).encode(),mtime=0))


if __name__=="__main__":
    main()

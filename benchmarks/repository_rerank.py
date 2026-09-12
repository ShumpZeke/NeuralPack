"""LOCAL cross-encoder challenger over real .npk BM25 candidates.

Uses the same source blocks and rendered budget as BM25. No generative model
or credential is used. This benchmark does not add a runtime dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from benchmarks.repository_eval import budgeted_context, provenance, source_coverage
from benchmarks.repository_tasks import SOURCE, dataset
from npk.pack import compile_pack, verify
from npk.pack.compile import estimate_tokens
from npk.pack.format import load_blocks, open_pack, read_manifest
from npk.pack.select import _lexical_channel

MODEL_ID="cross-encoder/ms-marco-MiniLM-L-6-v2"
REVISION="233902d25c440f23af6f7d6e94d2946bac0bee0a"


class LocalReranker:
    def __init__(self,cache):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        kwargs={"revision":REVISION,"cache_dir":str(cache),"local_files_only":True,"trust_remote_code":False}
        self.tokenizer=AutoTokenizer.from_pretrained(MODEL_ID,**kwargs)
        self.model=AutoModelForSequenceClassification.from_pretrained(MODEL_ID,use_safetensors=True,**kwargs).eval()

    def rank(self,query,blocks):
        import torch
        if not blocks:
            return [],[]
        scores=[]
        with torch.inference_mode():
            for start in range(0,len(blocks),16):
                batch=blocks[start:start+16]
                encoded=self.tokenizer([query]*len(batch),[b.text for b in batch],padding=True,
                                       truncation="only_second",max_length=512,return_tensors="pt")
                logits=self.model(**encoded).logits.reshape(-1)
                if len(logits)!=len(batch) or not torch.isfinite(logits).all():
                    raise RuntimeError("reranker returned malformed scores")
                scores.extend(logits.tolist())
        order=sorted(range(len(blocks)),key=lambda i:-scores[i])
        return [blocks[i] for i in order],[scores[i] for i in order]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--budgets",nargs="+",type=int,default=[500,1000,2000,4000])
    parser.add_argument("--candidates",type=int,default=60)
    args=parser.parse_args()
    if args.candidates<=0 or any(b<=0 for b in args.budgets):
        raise ValueError("candidate and token budgets must be positive")
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    data=dataset()
    run={"dataset":data,"provenance":provenance(),"arguments":vars(args),
         "harness_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         "model":{"id":MODEL_ID,"revision":REVISION,"max_length":512,"truncation":"only_second","batch_size":16},
         "limitations":["Developer-known questions, not independent answer-quality validation",
                        "Source-span coverage is a diagnostic, not answer accuracy",
                        "Cross-encoder scores are uncalibrated relevance logits",
                        "Long passages are truncated only for scoring; selected source remains intact",
                        "Reranking is measured once per question and reused across budget diagnostics"]}
    (root/"manifest.json").write_text(json.dumps(run,indent=2),encoding="utf-8")
    started=time.perf_counter()
    reranker=LocalReranker(Path(__file__).resolve().parents[1]/"experiments/models/hf_cache")
    load_ms=(time.perf_counter()-started)*1000
    rows=[];compilations={}
    for members in (False,True):
        policy="members" if members else "windows"
        pack=root/(policy+".npk")
        compilations[policy]=compile_pack(SOURCE,pack,python_members=members).as_dict()
        if not verify(pack)["ok"]:
            raise RuntimeError("compiled source failed integrity validation")
        for task in data["tasks"]:
            started=time.perf_counter()
            with open_pack(pack) as con:
                available=int(read_manifest(con)["available_tokens"])
                ids=_lexical_channel(con,task["question"],args.candidates)
                by_id={b.id:b for b in load_blocks(con,ids)}
                candidates=[by_id[i] for i in ids]
            seed_ms=(time.perf_counter()-started)*1000
            started=time.perf_counter()
            ordered,scores=reranker.rank(task["question"],candidates)
            rerank_ms=(time.perf_counter()-started)*1000
            for method,blocks in (("bm25",candidates),("cross_encoder",ordered)):
                for budget in args.budgets:
                    kept,context=budgeted_context(blocks,budget)
                    count=estimate_tokens(context) if context else 0
                    assert count<=budget
                    rows.append({"task":task["id"],"policy":policy,"method":method,"budget":budget,
                                 "available_tokens":available,"selected_tokens":count,"seed_failed":not kept,
                                 "seed_ms":seed_ms,"rerank_ms":rerank_ms if method=="cross_encoder" else 0,
                                 "candidate_count":len(candidates),"spans":[b.span for b in kept],
                                 "context":context,"context_sha256":hashlib.sha256(context.encode()).hexdigest(),
                                 **source_coverage(kept,task["required"])})
            print({"task":task["id"],"policy":policy,"candidates":len(candidates),"rerank_ms":round(rerank_ms,2)},flush=True)
    result={**run,"evidence_mode":"LOCAL","generative_api_calls":0,"model_load_ms":load_ms,
            "compilations":compilations,"rows":rows}
    import torch,psutil
    memory=psutil.Process().memory_info()._asdict()
    result["local_compute"]={"torch_threads":torch.get_num_threads(),"device":"cpu",
                             "rss_bytes_after_queries":memory["rss"],"peak_bytes":memory.get("peak_wset")}
    (root/"results.json").write_text(json.dumps(result,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()

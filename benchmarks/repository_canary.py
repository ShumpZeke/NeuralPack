"""Check answer-model usefulness with oracle-supplied and full repository source.

No retrieval algorithm is evaluated or promoted here. Default is LOCAL; --live
explicitly authorizes one request per uncached task/control. This uses existing
developer-known questions to qualify an answering baseline before a larger run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmarks.repository_eval import grade_answer, live_answer, provenance
from benchmarks.repository_tasks import SOURCE, dataset
from npk.pack.compile import estimate_tokens


def controls(task):
    selected=[]
    for item in task["required"]:
        start,end=item["span"]
        lines=(SOURCE/item["path"]).read_text(encoding="utf-8").splitlines()
        selected.append(f"[Source: {item['path']}:{start}-{end}]\n"+"\n".join(lines[start-1:end]))
    full="\n\n".join(f"[Source: {p.relative_to(SOURCE).as_posix()}:1-{len(p.read_text(encoding='utf-8').splitlines())}]\n{p.read_text(encoding='utf-8')}"
                     for p in sorted(SOURCE.rglob("*.py")))
    return {"oracle_supplied":"\n\n".join(selected),"full":full}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--model",required=True)
    parser.add_argument("--tasks",nargs="+",default=["disabled_vs_zero","server_delay_cap","redirect_method_change"])
    parser.add_argument("--max-output-tokens",type=int,default=2048)
    parser.add_argument("--reasoning-effort",choices=["none","high","max"])
    parser.add_argument("--live",action="store_true")
    args=parser.parse_args()
    data=dataset()
    data["tasks"]=[t for t in data["tasks"] if t["id"] in args.tasks]
    if len(data["tasks"])!=len(set(args.tasks)):
        raise ValueError("unknown task")
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    cache=root/"responses";cache.mkdir(exist_ok=True)
    folder=root/"contexts";folder.mkdir(exist_ok=True)
    run={"dataset":data,"provenance":provenance(),"arguments":vars(args),
         "harness_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         "limitations":["Developer-known diagnostic canaries; no independent quality claim",
                        "Oracle-supplied spans are supplied by the evaluator, not found by NeuralPack",
                        "Oracle-supplied and full contexts have different budgets; this is not a matched-budget retrieval contest"]}
    (root/"manifest.json").write_text(json.dumps(run,indent=2),encoding="utf-8")
    rows=[]
    for task in data["tasks"]:
        contexts=controls(task)
        for arm,context in contexts.items():
            digest=hashlib.sha256(context.encode()).hexdigest()
            (folder/(digest+".txt")).write_text(context,encoding="utf-8")
            result=live_answer(args.model,task["question"],context,cache,live=args.live,
                               max_output_tokens=args.max_output_tokens,reasoning_effort=args.reasoning_effort) if args.live else {
                                   "evidence_mode":"LOCAL","api_attempts_this_run":0}
            grade=grade_answer(result.get("content"),task["answer"]) if result.get("transport_success") else {
                "task_success":None,"parse_error":None}
            row={"task":task["id"],"arm":arm,"context_sha256":digest,"selected_tokens":estimate_tokens(context),
                 "available_tokens":estimate_tokens(contexts["full"]),**result,**grade}
            rows.append(row)
            print({k:row.get(k) for k in ("task","arm","evidence_mode","transport_success","task_success","http_status","error_type","usage")},flush=True)
            (root/"results.json").write_text(json.dumps({**run,"rows":rows},indent=2),encoding="utf-8")


if __name__=="__main__":
    main()

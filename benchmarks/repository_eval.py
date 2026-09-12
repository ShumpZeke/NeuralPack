"""Real-code retrieval diagnostics and explicit opt-in LIVE answer validation.

Default execution is LOCAL and requires no API key. Live requests are sent once
per uncached prompt, without hidden retries. Raw answers and provider usage are
recorded; replay is labelled separately. No LLM grades or rewrites the questions.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request

from benchmarks.repository_tasks import SOURCE, dataset
from npk.pack import PackSelector, compile_pack, verify
from npk.pack.compile import estimate_tokens

SYSTEM = ("Answer a code-behavior question about urllib3 2.7.0. Use the supplied source when present. "
          "You may use your own knowledge, but use null for values you cannot determine. "
          "Return only a JSON object with exactly the requested keys, without prose or Markdown fences.")


def equal_answer(got, expected):
    if isinstance(expected,dict):
        return isinstance(got,dict) and got.keys()==expected.keys() and all(equal_answer(got[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return isinstance(got,list) and len(got)==len(expected) and all(equal_answer(a,b) for a,b in zip(got,expected))
    if isinstance(expected,(int,float)) and not isinstance(expected,bool):
        return isinstance(got,(int,float)) and not isinstance(got,bool) and got==expected
    return type(got) is type(expected) and got==expected


def grade_answer(content, expected):
    def unique_object(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate answer key')
            result[key]=value
        return result
    def reject_constant(value):
        raise ValueError('non-JSON numeric constant')
    try:
        parsed=json.loads(content,object_pairs_hook=unique_object,parse_constant=reject_constant)
    except (ValueError,TypeError):
        return {"task_success":False,"parse_error":True,"parsed":None}
    return {"task_success":equal_answer(parsed,expected),"parse_error":False,"parsed":parsed}


def render(evidence):
    return "\n\n".join(f"[Source: {e.span}]\n{e.text}" for e in evidence)


def budgeted_context(evidence,budget):
    kept=[]
    for block in evidence:
        if estimate_tokens(render(kept+[block])) <= budget:
            kept.append(block)
    return kept,render(kept)


def source_coverage(evidence,required):
    covered={}
    for e in evidence:
        match=re.search(r":(\d+)-(\d+)$",e.span)
        if not match:
            raise ValueError("evidence span is missing")
        start,end=map(int,match.groups())
        covered.setdefault(e.path,set()).update(range(start,end+1))
    hits=[]
    for item in required:
        start,end=item["span"]
        need=set(range(start,end+1))
        hits.append(need <= covered.get(item["path"],set()))
    return {"all_required_spans":all(hits) if hits else None,
            "required_span_fraction":sum(hits)/len(hits) if hits else None}


def provenance():
    root=Path(__file__).resolve().parents[1]
    paths=[*sorted((root/"npk").rglob("*.py")), Path(__file__),
           root/"benchmarks/repository_tasks.py"]
    packages={}
    for name in ("urllib3","torch","transformers","sentence-transformers"):
        try:
            packages[name]=version(name)
        except PackageNotFoundError:
            packages[name]=None
    return {"started_utc":datetime.now(timezone.utc).isoformat(),
            "git_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),
            "code_sha256":{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            "packages":packages,
            "dollar_cost":None,"cost_reason":"No verified endpoint billing rate; usage is recorded without invented prices"}


def answer_payload(model,question,context,*,max_output_tokens=384,reasoning_effort=None,
                   system_prompt=SYSTEM,temperature=0,top_p=None,chat_template_kwargs=None):
    if type(max_output_tokens) is not int or max_output_tokens<=0:
        raise ValueError("max_output_tokens must be a positive integer")
    if not isinstance(system_prompt,str) or not system_prompt:
        raise ValueError("system_prompt must be a nonempty string")
    if type(temperature) not in (int,float) or not 0<=temperature<=2:
        raise ValueError('temperature must be between 0 and 2')
    if top_p is not None and (type(top_p) not in (int,float) or not 0<top_p<=1):
        raise ValueError('top_p must be within (0,1]')
    if chat_template_kwargs is not None:
        if (type(chat_template_kwargs) is not dict or not chat_template_kwargs
            or set(chat_template_kwargs)-{'thinking','enable_thinking','low_effort'}
            or any(type(v) is not bool for v in chat_template_kwargs.values())):
            raise ValueError('only explicit boolean thinking template flags are supported')
    messages=[{"role":"system","content":system_prompt},
              {"role":"user","content":f"SOURCE\n{context}\n\nQUESTION\n{question}"}]
    payload={"model":model,"messages":messages,"temperature":temperature,"max_tokens":max_output_tokens}
    if reasoning_effort is not None:
        payload["reasoning_effort"]=reasoning_effort
    if top_p is not None:payload['top_p']=top_p
    if chat_template_kwargs is not None:payload['chat_template_kwargs']=dict(chat_template_kwargs)
    return payload


def retry_after_seconds(value, now):
    """Parse the HTTP delay or date without retaining arbitrary header text."""
    if not isinstance(value, str) or not value.strip(): return None
    value = value.strip()
    if value.isascii() and value.isdecimal():
        try: return int(value)
        except ValueError: return None
    try:
        instant = parsedate_to_datetime(value)
        if instant.tzinfo is None: return None
        return max(0, (instant-now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def live_answer(model,question,context,cache,*,live,max_output_tokens=384,reasoning_effort=None,
                system_prompt=SYSTEM,timeout_seconds=60,execution_code_sha256=None,
                temperature=0,top_p=None,chat_template_kwargs=None):
    if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=600:
        raise ValueError("timeout_seconds must be between 0 and 600")
    payload=answer_payload(model,question,context,max_output_tokens=max_output_tokens,
                           reasoning_effort=reasoning_effort,system_prompt=system_prompt,
                           temperature=temperature,top_p=top_p,chat_template_kwargs=chat_template_kwargs)
    serialized=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    key=hashlib.sha256(serialized).hexdigest()
    path=cache/(key+".json")
    if path.exists():
        result=json.loads(path.read_text(encoding="utf-8"))
        if result["request_sha256"] != key:
            raise RuntimeError("response cache identity mismatch")
        return {**result,"evidence_mode":"REPLAY","api_attempts_this_run":0}
    if not live:
        return {"evidence_mode":"REPLAY_MISS","api_attempts_this_run":0,"content":None}
    from npk.providers.nvidia import _load_env_key
    key_value=_load_env_key()
    if not key_value:
        raise RuntimeError("NIM credential is not configured")
    request=urllib.request.Request("https://integrate.api.nvidia.com/v1/chat/completions",data=serialized,
                                   headers={"Authorization":"Bearer "+key_value,"Content-Type":"application/json"})
    started=time.perf_counter()
    result={"evidence_mode":"LIVE","request_sha256":key,"model":model,"api_attempts_this_run":1,
            "question":question,"context_sha256":hashlib.sha256(context.encode()).hexdigest(),
            "socket_timeout_seconds":timeout_seconds,
            "execution_code_sha256":execution_code_sha256 or {
                "benchmarks/repository_eval.py":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    try:
        with urllib.request.urlopen(request,timeout=timeout_seconds) as response:
            raw=json.loads(response.read())
        choices=raw.get("choices",[])
        if not choices:
            raise ValueError("no choices in provider response")
        result.update({"content":choices[0].get("message",{}).get("content"),
                       "usage":raw.get("usage"),"raw_response":raw,"transport_success":True})
    except urllib.error.HTTPError as exc:
        # Keep diagnostic details without retaining a credential echoed by a service.
        result.update({"content":None,"transport_success":False,"http_status":exc.code})
        result['retry_after_seconds'] = retry_after_seconds(
            exc.headers.get('Retry-After') if exc.headers else None, datetime.now(timezone.utc))
        from npk.telemetry import redact_secrets
        try:
            detail=exc.read(4096).decode("utf-8",errors="replace").replace(key_value,"[redacted]")
            result["error_detail"]=redact_secrets(detail)[:1000]
        except OSError:
            pass
    except (OSError,ValueError) as exc:
        result.update({"content":None,"transport_success":False,"error_type":type(exc).__name__})
    result["latency_ms"]=(time.perf_counter()-started)*1000
    path.write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--semantic",action="store_true")
    execution=parser.add_mutually_exclusive_group()
    execution.add_argument("--live",action="store_true")
    execution.add_argument("--replay",action="store_true")
    parser.add_argument("--live-budget",type=int,default=2000)
    parser.add_argument("--budgets",nargs="+",type=int,default=[500,1000,2000,4000])
    parser.add_argument("--model",default="meta/llama-3.2-11b-vision-instruct")
    parser.add_argument("--max-output-tokens",type=int,default=384)
    parser.add_argument("--reasoning-effort",choices=["none","high","max"])
    parser.add_argument("--tasks",nargs="*")
    args=parser.parse_args()
    if any(b <= 0 for b in [*args.budgets,args.live_budget]):
        raise ValueError("budgets must be positive")
    if args.live_budget not in args.budgets:
        raise ValueError("live budget must be included in offline sweep")
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    cache=root/"responses";cache.mkdir(exist_ok=True)
    contexts=root/"contexts";contexts.mkdir(exist_ok=True)
    data=dataset()
    run=provenance()
    run["answer_generation"]={"model":args.model,"max_output_tokens":args.max_output_tokens,
                              "reasoning_effort":args.reasoning_effort,"temperature":0}
    if args.tasks:
        data["tasks"]=[t for t in data["tasks"] if t["id"] in args.tasks]
        if len(data["tasks"]) != len(set(args.tasks)):
            raise ValueError("unknown task selection")
    os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
    (root/"run-manifest.json").write_text(json.dumps({"dataset":data,"provenance":run,"arguments":vars(args)},indent=2),encoding="utf-8")
    configurations=[("bm25_windows",False,"deterministic"),("bm25_members",True,"deterministic")]
    if args.semantic:
        configurations.append(("hybrid_members",True,"semantic"))
    selectors={};compilations={}
    for name,members,mode in configurations:
        pack=root/(name+".npk")
        stats=compile_pack(SOURCE,pack,python_members=members,mode=mode)
        if mode=="semantic" and not stats.embedded:
            raise RuntimeError("semantic experiment requested without a local embedding index")
        if not verify(pack)["ok"]:
            raise RuntimeError("compiled repository failed verification")
        compilations[name]=stats.as_dict()
        selectors[name]=PackSelector(pack,retrieval="hybrid" if mode=="semantic" else "lexical")
    full="\n\n".join(f"[Source: {p.relative_to(SOURCE).as_posix()}:1-{len(p.read_text(encoding='utf-8').splitlines())}]\n{p.read_text(encoding='utf-8')}"
                       for p in sorted(SOURCE.rglob("*.py")))
    rows=[]
    for task in data["tasks"]:
        live_contexts={"none":"", "full":full}
        for budget in args.budgets:
            for arm,selector in selectors.items():
                started=time.perf_counter()
                selection=selector.select(task["question"],budget_tokens=budget)
                kept,text=budgeted_context(selection.evidence,budget)
                row={"task":task["id"],"arm":arm,"budget":budget,"evidence_mode":"LOCAL",
                     "source_available_tokens":estimate_tokens(full),"selected_tokens":estimate_tokens(text) if text else 0,
                     "seed_failed":selection.seed_failed or not kept,"latency_ms":(time.perf_counter()-started)*1000,
                     "spans":[e.span for e in kept],**source_coverage(kept,task["required"])}
                rows.append(row)
                if budget==args.live_budget:
                    live_contexts[arm]=text
        if args.live or args.replay:
            for arm,text in live_contexts.items():
                # Failed selection remains a failure, rather than an empty-context win.
                if arm not in {"none","full"} and not text:
                    rows.append({"task":task["id"],"arm":arm,"evidence_mode":"SELECTION_FAILED","task_success":False})
                    continue
                context_hash=hashlib.sha256(text.encode()).hexdigest()
                (contexts/(context_hash+".txt")).write_text(text,encoding="utf-8")
                result=live_answer(args.model,task["question"],text,cache,live=args.live,
                                   max_output_tokens=args.max_output_tokens,reasoning_effort=args.reasoning_effort)
                grade=grade_answer(result.get("content"),task["answer"]) if result.get("transport_success") else {
                    "task_success":None,"parse_error":None,"parsed":None}
                row={"task":task["id"],"arm":arm,"budget":args.live_budget if arm not in {"full","none"} else None,
                     "source_available_tokens":estimate_tokens(full),"selected_tokens":estimate_tokens(text) if text else 0,
                     **result,**grade}
                rows.append(row)
                print({k:row.get(k) for k in ("task","arm","evidence_mode","task_success","http_status","usage")},flush=True)
                (root/"partial.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    summaries=[]
    for budget in args.budgets:
        for arm in selectors:
            group=[r for r in rows if r.get("budget")==budget and r["arm"]==arm and r["evidence_mode"]=="LOCAL"]
            summaries.append({"arm":arm,"budget":budget,"tasks":len(group),
                              "required_span_coverage":statistics.mean(r["required_span_fraction"] for r in group),
                              "all_spans_tasks":sum(r["all_required_spans"] for r in group),
                              "median_ms":statistics.median(r["latency_ms"] for r in group)})
    result={"dataset":data,"provenance":run,"compilations":compilations,"summaries":summaries,"rows":rows,
            "token_estimator":"chars/4 including source headers; excludes identical query/system wrappers",
            "source_available_tokens":estimate_tokens(full),"generative_optimization_calls":0,
            "live_api_attempts":sum(r.get("api_attempts_this_run",0) for r in rows)}
    (root/"results.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    for row in summaries:
        print(row,flush=True)


if __name__ == "__main__":
    main()

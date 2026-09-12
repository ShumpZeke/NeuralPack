"""Freeze privileged-source and target-configuration controls, not retrievers.

The questions are known. Manually chosen source symbols are diagnostic input;
their availability and usefulness do not demonstrate automatic selection quality.
"""
import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from benchmarks.answer_records import import_replays
from benchmarks.prospective_eval import request_key, write_json
from benchmarks.repository_eval import source_coverage

SUPPORT={
    'layered_scope':('collections/__init__.py',('ChainMap',)),
    'signed_counts':('collections/__init__.py',('Counter',)),
    'nested_cache':('functools.py',('_CacheInfo','_HashedSeq','_make_key','lru_cache','_lru_cache_wrapper')),
    'derived_ordering':('functools.py',('_convert','total_ordering','_gt_from_lt','_le_from_lt','_ge_from_lt')),
    'cleanup_suppression':('contextlib.py',('_BaseExitStack','ExitStack','suppress')),
    'bound_partial':('functools.py',('partialmethod',)),
    'dispatched_types':('functools.py',('singledispatch','_find_impl','_compose_mro','_c3_mro','_c3_merge')),
    'missing_front':('collections/__init__.py',('ChainMap',)),
}


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def tokens(text):return max(1,len(text)//4) if text else 0


def support_pieces(body, names, path):
    """Exact top-level definitions, including decorators and assignment metadata."""
    text=body.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
    tree=ast.parse(text);lines=text.split('\n');found={}
    for node in tree.body:
        if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            bound=[node.name]
            start=min([node.lineno]+[d.lineno for d in node.decorator_list])
        elif isinstance(node,ast.Assign):
            bound=[t.id for t in node.targets if isinstance(t,ast.Name)];start=node.lineno
        else:continue
        for name in set(bound)&set(names):
            if name in found:raise ValueError('Ambiguous privileged source declaration')
            found[name]=(start,node.end_lineno)
    if set(found)!=set(names):raise ValueError('Missing privileged source declaration')
    pieces=[]
    for name,(start,end) in sorted(found.items(),key=lambda x:x[1]):
        part='\n'.join(lines[start-1:end]);pieces.append({
            'path':path,'span':f'{path}:{start}-{end}','symbol':name,'text':part,'source_sha256':sha(body)})
    return pieces


def prepare(root,parent,manuals):
    repo=Path(__file__).resolve().parents[1]
    if root.exists():raise ValueError('New frozen diagnostic directory required')
    parent_raw=(parent/'plan.json').read_bytes();parent_plan=read(parent/'plan.json')
    assert sha(parent_raw)==(parent/'plan.sha256').read_text().strip()
    ledger=read(parent/'ledger.json')
    assert set(ledger)==set(parent_plan['requests']) and all(e['state']=='DONE' for e in ledger.values())
    tasks=[deepcopy(t) for t in parent_plan['dataset']['tasks'] if t['id'] in SUPPORT]
    assert {t['id'] for t in tasks}==set(SUPPORT) and len(tasks)==8
    acquisition=read(manuals/'acquisition.json');manifest={x['path']:x for x in acquisition['source_manifest']}
    assert acquisition['commit']=='0cc81280367df838c4b199f8f0378837165071c2'
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    root.mkdir(parents=True);(root/'source').mkdir();conditions=[];contexts={}
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL preparation attempted network')):
        for task in tasks:
            name,names=SUPPORT[task['id']];path='cpython/Lib/'+name
            body=(manuals/'source'/path).read_bytes();assert sha(body)==manifest[path]['sha256']
            destination=root/'source'/path;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(body)
            pieces=support_pieces(body,names,path);context='\n\n'.join(p['text'] for p in pieces)
            assert 0<tokens(context)<=8192
            coverage=source_coverage([SimpleNamespace(**p) for p in pieces],task['required'])
            assert coverage['all_required_spans']
            digest=sha(context.encode());contexts[digest]=context
            support={'task':task['id'],'cohort':'known_target_controls','corpus':'original','method':'privileged_source',
                     'budget':8192,'selected_tokens':tokens(context),'context_sha256':digest,
                     'selection_ms':0,'seed_failed':False,'selection_timing_status':'NOT_MEASURED_PRIVILEGED_CONSTRUCTION',
                     'evidence':[{k:v for k,v in p.items() if k!='text'} for p in pieces],**coverage}
            candidates=[]
            for method in ('bm25','none'):
                rows=[r for r in parent_plan['observations'] if r['task']==task['id'] and r['method']==method
                      and r['budget']==(8192 if method=='bm25' else None)]
                assert len(rows)==1;row=deepcopy(rows[0])
                context=(parent/'contexts'/(row['context_sha256']+'.txt')).read_bytes().decode()
                assert sha(context.encode())==row['context_sha256'];contexts[row['context_sha256']]=context
                row.update(cohort='known_target_controls',corpus='original')
                candidates.append(row)
            candidates.append(support);shift=len(conditions)//3%3
            conditions.extend(candidates[shift:]+candidates[:shift])
        direct=deepcopy(parent_plan['settings']);reasoning=deepcopy(direct)
        assert direct['chat_template_kwargs']=={'enable_thinking':False} and direct['max_output_tokens']==2048
        reasoning.update(chat_template_kwargs={'enable_thinking':True},max_output_tokens=16384,timeout_seconds=180)
        versions={name:{'sha256':value,'text':(repo/name).read_bytes().decode()} for name,value in current.items()}
        (root/'preparation-sources.json.gz').write_bytes(gzip.compress(json.dumps(versions).encode(),mtime=0))
        summaries=[]
        for configuration,settings in (('direct',direct),('reasoning',reasoning)):
            run=root/configuration;run.mkdir();(run/'contexts').mkdir();observations=[];requests={}
            for condition in conditions:
                row=deepcopy(condition);task=next(t for t in tasks if t['id']==row['task'])
                context=contexts[row['context_sha256']];key=request_key(settings,task['question'],context)
                (run/'contexts'/(row['context_sha256']+'.txt')).write_bytes(context.encode())
                row.update(request_sha256=key,selected_prompt_tokens_estimate=tokens(
                    settings['system_prompt']+f"SOURCE\n{context}\n\nQUESTION\n{task['question']}"))
                # These are original-corpus controls even when source spans were
                # selected manually; never invent a new available-context count.
                original=next(r for r in parent_plan['observations'] if r['task']==task['id'])
                for k in ('corpus_tokens','available_tokens','baseline_prompt_tokens_estimate'):row[k]=original[k]
                observations.append(row);requests.setdefault(key,{'question':task['question'],'context_sha256':row['context_sha256']})
            plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','configuration':configuration,
                  'dataset':{'tasks':tasks},'settings':settings,'methods':['bm25','privileged_source'],'budgets':[8192],
                  'observations':observations,'requests':requests,'code_sha256':current,
                  'parent_plan_sha256':sha(parent_raw),'source_commit':acquisition['commit'],
                  'preparation_sources_sha256':sha((root/'preparation-sources.json.gz').read_bytes()),
                  'settings_source':{'url':'https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/build',
                                     'verified_on':'2026-09-07','modelcard_url':'https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard'},
                  'limitations':['Known developer-authored questions; not sealed independent validation',
                      'Privileged source uses manually named definitions and larger spans, not an automatic retrieval algorithm',
                      'Containing required spans does not prove sufficiency; external/C-accelerated behavior may be absent',
                      '8192 estimated evidence-token cap; actual provider tokens are measured separately',
                      'Reasoning configuration also raises output cap from 2048 to 16384 and socket timeout from 90 to 180 seconds',
                      'This is a combined target-configuration diagnostic, not an isolated thinking-flag causal test',
                      'Direct identical payloads replay terminal parent outcomes, including errors; no failed call is retried',
                      'No-context control is not a successful context optimization',
                      'One target call per new payload; optimizer makes zero generative calls',
                      'No compute-normalized superiority, context minimality or dollar-savings claim']}
            write_json(run/'plan.json',plan);(run/'plan.sha256').write_text(sha((run/'plan.json').read_bytes()))
            reused=import_replays(parent,run,plan) if configuration=='direct' else {'replayed_records':0,'pending_new_requests':len(requests)}
            summaries.append({'configuration':configuration,'plan_sha256':sha((run/'plan.json').read_bytes()),**reused})
        assert [r['context_sha256'] for r in read(root/'direct/plan.json')['observations']]==[
            r['context_sha256'] for r in read(root/'reasoning/plan.json')['observations']]
        preflight={'evidence_mode':'LOCAL','generative_calls':0,'tasks':len(tasks),'conditions':len(conditions),
                   'plans':summaries,'privileged_tokens':{r['task']:r['selected_tokens'] for r in conditions if r['method']=='privileged_source'},
                   'source_sha256':{p.relative_to(root/'source').as_posix():sha(p.read_bytes()) for p in (root/'source').rglob('*.py')},
                   'preparation_sources_sha256':sha((root/'preparation-sources.json.gz').read_bytes())}
        write_json(root/'preflight.json',preflight);print(preflight)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--manuals',type=Path,required=True);args=parser.parse_args()
    prepare(args.output.resolve(),args.parent.resolve(),args.manuals.resolve())

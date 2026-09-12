"""Freeze same-source rendering experiments and privileged source controls.

No inference is performed. Each model gets its own fixed plan and fresh ledger.
Old questions and controls are explicitly a diagnostic follow-up, not a holdout.
"""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import time
import click

from benchmarks.evidence_diagnostics import (definitions,pieces_from_symbols,trace_called_symbols,
    from_evidence,render,fit_labeled,validate_pieces)
from benchmarks.identifier_tasks import TASKS
from benchmarks.prospective_eval import SYSTEM,request_key,write_json
from npk.pack import compile_pack,verify,PackSelector
from npk.pack.compile import estimate_tokens
from npk.pack.format import open_pack,load_blocks


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root):
    repo=Path(__file__).resolve().parents[1]
    if root.exists():raise ValueError('new diagnostic run directory required')
    root.mkdir(parents=True);source=root/'source';source.mkdir()
    parent=repo/'experiments/runs/repository-identifier-live-v1/plan.json'
    assert sha(parent)==parent.with_suffix('.sha256').read_text().strip()
    prior=json.loads(parent.read_text());origin=repo/'experiments/runs/packs/cycle12-seeds-final/source'
    assert version('click')=='8.5.0';registered={}
    for item in prior['source_manifest']:
        original=origin/item['path'];assert sha(original)==item['sha256']
        target=source/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
        if item['path'].startswith('src/click/') and item['path'].endswith('.py'):
            installed=Path(click.__file__).resolve().parent/item['path'][len('src/click/'):]
            assert sha(installed)==item['sha256']
            for spelling in (str(installed),str(installed).replace('\\','/')):registered[spelling]=item['path']
    pack=root/'project.npk';stats=compile_pack(source,pack)
    assert verify(pack)['ok']
    with open_pack(pack) as con:all_pieces=[from_evidence(b) for b in load_blocks(con)]
    validate_pieces(source,all_pieces);full=render(all_pieces,False)
    available_tokens=estimate_tokens(full);selector=PackSelector(pack);budgets=[2048,8192]
    definitions_by_family={t.id:t for t in TASKS};observations=[];contexts={};controls={}
    def add(task,method,budget,pieces,labeled,selection_ms=0,seed_failed=False):
        validate_pieces(source,pieces);context=render(pieces,labeled);plain=render(pieces,False)
        tokens=estimate_tokens(context) if context else 0
        assert budget is None or tokens<=budget
        digest=hashlib.sha256(context.encode()).hexdigest();contexts[digest]=context
        observations.append({'task':task['id'],'method':method,'budget':budget,'context_sha256':digest,
            'selected_tokens':tokens,'selected_source_tokens':estimate_tokens(plain) if plain else 0,
            'rendering':'provenance_labels' if labeled else 'bare_source','selection_ms':selection_ms,
            'seed_failed':seed_failed or (budget is not None and not pieces),
            'evidence':[asdict(p) for p in pieces]})
    for task in prior['dataset']['tasks']:
        spec=definitions_by_family[task['family']]
        called,unmapped,answer=trace_called_symbols(spec.oracle,registered)
        assert answer==task['answer'] and called,'oracle changed or no calls were captured'
        # A missing named function is a failed diagnostic preparation, not an
        # excuse to silently drop executed source. Comprehensions are disclosed.
        required=pieces_from_symbols(source,[(r['path'],r['symbol']) for r in task['required']],include_class_context=True)
        traced=pieces_from_symbols(source,called,include_class_context=True)
        controls[task['id']]={'called_symbols':sorted(called),'unmapped_comprehensions':sorted(unmapped),
                              'required_tokens':estimate_tokens(render(required,True)),
                              'called_tokens':estimate_tokens(render(traced,True))}
        add(task,'required_definitions',None,required,True)
        add(task,'called_definitions',None,traced,True)
        add(task,'none',None,[],False)
        add(task,'full',None,all_pieces,False)
        for budget in budgets:
            start=time.perf_counter();selected=selector.select(task['question'],budget_tokens=budget)
            selection_ms=1000*(time.perf_counter()-start)
            assert selected.query==task['question'] and not selected.used_generative_llm
            pieces=[from_evidence(e) for e in selected.evidence]
            assert render(pieces,False)==selected.context_text()
            add(task,'bm25_windows',budget,pieces,False,selection_ms,selected.seed_failed)
            start=time.perf_counter();paired=fit_labeled(pieces,budget)
            fitted_ms=selection_ms+1000*(time.perf_counter()-start)
            add(task,'bm25_labeled',budget,paired,True,fitted_ms,selected.seed_failed)
            add(task,'bm25_same_blocks',budget,paired,False,fitted_ms,selected.seed_failed)
        print({'task':task['id'],**{k:v for k,v in controls[task['id']].items() if k.endswith('_tokens')}},flush=True)
    paths=[p for d in ('npk','benchmarks') for p in (repo/d).rglob('*.py')]
    sources={p.relative_to(repo).as_posix():sha(p) for p in paths}
    models={
        'deepseek':{'model':'deepseek-ai/deepseek-v4-flash-0731','reasoning_effort':'none'},
        'nemotron':{'model':'nvidia/nemotron-3-super-120b-a12b','reasoning_effort':None,
                    'temperature':1.0,'top_p':0.95,'chat_template_kwargs':{'enable_thinking':False}},
    }
    for name,settings in models.items():
        folder=root/name;folder.mkdir();destination=folder/'contexts';destination.mkdir()
        settings={**settings,'system_prompt':SYSTEM,'max_output_tokens':2048,'timeout_seconds':90}
        rows=[];requests={}
        for index,task in enumerate(prior['dataset']['tasks']):
            candidates=[r for r in observations if r['task']==task['id']]
            offset=index%len(candidates)
            for original in candidates[offset:]+candidates[:offset]:
                row=dict(original);context=contexts[row['context_sha256']]
                (destination/(row['context_sha256']+'.txt')).write_bytes(context.encode())
                key=request_key(settings,task['question'],context)
                row.update(request_sha256=key,corpus_tokens=prior['corpus_tokens'],available_tokens=available_tokens,
                    baseline_prompt_tokens_estimate=estimate_tokens(SYSTEM+f"SOURCE\n{full}\n\nQUESTION\n{task['question']}"),
                    selected_prompt_tokens_estimate=estimate_tokens(SYSTEM+f"SOURCE\n{context}\n\nQUESTION\n{task['question']}"))
                if row['seed_failed']:row['status']='SELECTION_FAILED'
                else:requests.setdefault(key,{'question':task['question'],'context_sha256':row['context_sha256']})
                rows.append(row)
        plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL',
              'parent_plan_sha256':sha(parent),'dataset':prior['dataset'],'settings':settings,'budgets':budgets,
              'source_manifest':prior['source_manifest'],'corpus_tokens':prior['corpus_tokens'],
              'available_tokens':available_tokens,'compilation':stats.as_dict(),'controls':controls,
              'code_sha256':sources,'observations':rows,'requests':requests,
              'limitations':[
                  'Diagnostic follow-up on eight previously inspected families; not independent held-out validation',
                  'Each run is an explicitly planned new replication, not a retry of earlier failed transport',
                  'Called definitions use privileged executable oracles; not a deployable retrieval baseline or proven sufficient/minimal context',
                  'Controls include only pinned source definitions/class context, not oracle bodies, locals, outputs or branch traces; external library behavior may still matter',
                  'Required/called/full/none are reference controls without a context cap; compare retrieval only at matched estimated budgets',
                  'Labeled and same-block arms contain identical source; headers consume budget and can drop blocks from normal BM25 selection',
                  'Selected tokens include rendering overhead; available_tokens describes bare compiled source. No cross-representation reduction or MSC ratio is reported',
                  'One observation per method/budget/task/model; methods and budgets are correlated, model settings differ',
                  'Temperatures follow the declared study configuration; neither reproducible output nor effective server reasoning mode is guaranteed by request fields',
                  'Provider load and local machine activity are uncontrolled; prices remain unverified and dollar cost is N/A'],
              'provider_configuration_sources':[
                  'https://build.nvidia.com/deepseek-ai/deepseek-v4-flash-0731',
                  'https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b']}
        write_json(folder/'plan.json',plan);(folder/'plan.sha256').write_text(sha(folder/'plan.json'),encoding='ascii')
        print({'model':name,'observations':len(rows),'unique_requests':len(requests),'generative_calls':0},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args().output.resolve())

"""Prospective LOCAL unit/neighbor comparison on pinned SQLAlchemy manuals."""
import argparse
from functools import partial
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.boundary_retrieval import fixed_chars
from benchmarks.evidence_diagnostics import from_evidence,render,validate_pieces,fit_labeled
from benchmarks.unit_passages import coalesce,select
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.compiled_source_contract import require_compiled_sources
from npk.pack import compile_pack,verify,PackSelector
from npk.pack.compile import estimate_tokens
from npk.pack.format import open_pack,load_blocks,read_manifest


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def public_context(selected,budget):
    pieces=coalesce([from_evidence(e) for e in selected.evidence])
    pieces=fit_labeled(pieces,budget)
    return pieces,render(pieces,True)


def required_passages(tasks,source):
    specs={
        'commit_without_autoflush':[('session_basics.rst',423,426)],
        'nested_flush_boundary':[('session_transaction.rst',195,198),('session_transaction.rst',207,211)],
        'failed_flush_recovery':[('session_basics.rst',438,442)],
        'rollback_expiration':[('session_basics.rst',723,724)],
        'close_reusability':[('session_basics.rst',763,766),('session_basics.rst',770,773)],
        'refresh_unflushed_value':[('session_state_management.rst',477,484)],
        'joined_collection_uniqueness':[('queryguide/relationships.rst',470,474)],
        'streamed_unique_rows':[('queryguide/api.rst',265,269),('queryguide/api.rst',271,274)],
        'deletion_collection_state':[('session_basics.rst',346,349)],
        'autobegin_disabled':[('session_basics.rst',603,610)],
    }
    assert set(specs)=={t['id'] for t in tasks}
    result=[]
    for task in tasks:
        required=[]
        for relative,start,end in specs[task['id']]:
            path='sqlalchemy/doc/build/orm/'+relative;lines=(source/path).read_text(encoding='utf-8').split('\n')
            text='\n'.join(lines[start-1:end]);assert text.strip()
            required.append({'path':path,'span':[start,end],'text':text,'sha256':sha(text.encode())})
        result.append({**task,'required':required})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--tasks',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compiled',type=Path,help='Reuse independently verified completed artifact builds; retain their original measurement identity')
    a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];root=a.output.resolve();source=(a.corpus/'source').resolve()
    if root.exists():raise ValueError('New frozen comparison directory required')
    acquisition=read(a.corpus/'acquisition.json');oracles=read(a.tasks)
    for item in acquisition['source_manifest']:assert sha((source/item['path']).read_bytes())==item['sha256']
    assert oracles['oracle_source_sha256']==sha((repo/'benchmarks/sqlalchemy_oracles.py').read_bytes())
    tasks=required_passages(oracles['tasks'],source);budgets=[512,1024,2048,4096]
    configurations={
        'public_bm25':('fixed2048','public','lexical'),
        'shared_bm25':('fixed2048','seed','lexical'),
        'micro_seed':('units512','seed','lexical'),
        'micro_neighbor1':('units512','neighbor1','lexical'),
        'micro_neighbor2':('units512','neighbor2','lexical'),
        'micro_paragraph':('units512','paragraph','lexical'),
        'public_hybrid':('semantic2048','public','hybrid'),
        'shared_hybrid':('semantic2048','seed','hybrid'),
    }
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    compilation_origin=None;previous=None
    if a.compiled:
        previous=read(a.compiled/'compilation.json');prior_plan=read(a.compiled/'manifest.json')
        assert prior_plan['acquisition_sha256']==sha((a.corpus/'acquisition.json').read_bytes())
        for name,digest in prior_plan['code_sha256'].items():
            if name.startswith('npk/') or name=='benchmarks/boundary_retrieval.py':assert sha((repo/name).read_bytes())==digest
        compilation_origin={'path':str(a.compiled.resolve()),'compilation_sha256':sha((a.compiled/'compilation.json').read_bytes()),
                            'manifest_sha256':sha((a.compiled/'manifest.json').read_bytes()),
                            'note':'Original LOCAL compilation measurements reused; no new compilation speed measurement'}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,'trials':3,'compilation_origin':compilation_origin,
              'acquisition_sha256':sha((a.corpus/'acquisition.json').read_bytes()),'source_manifest':acquisition['source_manifest'],
              'oracle_sha256':sha(a.tasks.read_bytes()),'tasks':tasks,'budgets':budgets,'configurations':configurations,
              'limitations':['Ten developer-authored scenarios, prospectively frozen before retrieval; not independently sealed',
                             'Required manual passages are a diagnostic, not an exhaustive sufficiency proof',
                             'Observed answer labels are never added to the compiled corpus or sent into retrieval',
                             'Public controls use PackSelector then common source coalescing and labeled budget fitting',
                             'Shared controls isolate assembly from indexing; every final rendered context has the same cap',
                             'One initial compile per artifact; three shuffled query sweeps, no controlled host load',
                             'All query sweeps share a process with the optional local encoder loaded',
                             'MiniLM uses its pinned 256-token input limit and 2,000-character document prefix; long queries can be truncated',
                             'No generative answer requests, answer accuracy or dollar claims in this LOCAL preparation']}
    root.mkdir(parents=True);(root/'contexts').mkdir();write_json(root/'manifest.json',manifest)
    write_json(root/'execution-sources.json',{name:(repo/name).read_bytes().decode() for name in code})
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    compiler=importlib.import_module('npk.pack.compile');builds={};corpora={};packs={};rows=[]
    raw='\n\n'.join((source/item['path']).read_text(encoding='utf-8') for item in acquisition['source_manifest'])
    corpus_tokens=estimate_tokens(raw)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL unit experiment attempted network')):
        for name,width,mode in [('fixed2048',2048,'deterministic'),('units512',512,'deterministic'),('semantic2048',2048,'semantic')]:
            pack=root/(name+'.npk');packs[name]=pack
            if previous:
                src=a.compiled/(name+'.npk');assert sha(src.read_bytes())==previous['corpora'][name]['pack_sha256']
                assert verify(src)['ok'];require_compiled_sources(src,acquisition['source_manifest'])
                shutil.copyfile(src,pack);assert sha(pack.read_bytes())==previous['corpora'][name]['pack_sha256']
                builds[name]=previous['builds'][name];corpora[name]=previous['corpora'][name]
                print({'reused_verified_artifact':name,'blocks':corpora[name]['blocks']},flush=True)
                continue
            import psutil
            rss_before=psutil.Process().memory_info().rss
            start=time.perf_counter_ns();cpu=time.process_time_ns()
            if mode=='semantic':
                import torch
                torch.set_num_threads(2)
            with patch.object(compiler,'split_source',partial(fixed_chars,max_chars=width)):
                stats=compile_pack(source,pack,mode=mode)
            elapsed=(time.perf_counter_ns()-start)/1e6;cpu_ms=(time.process_time_ns()-cpu)/1e6
            assert verify(pack)['ok']
            require_compiled_sources(pack,acquisition['source_manifest'])
            if mode=='semantic':assert stats.embedded==stats.blocks and stats.embedded>0
            with open_pack(pack) as con:blocks=load_blocks(con);metadata=read_manifest(con)
            validate_pieces(source,[from_evidence(b) for b in blocks]);available=estimate_tokens('\n\n'.join(b.text for b in blocks))
            corpora[name]={'corpus_tokens':corpus_tokens,'available_tokens':available,'blocks':len(blocks),
                           'source_files':len(acquisition['source_manifest']),'pack_sha256':sha(pack.read_bytes())}
            builds[name]={'initial_compile_ms':elapsed,'cpu_ms':cpu_ms,'pack_bytes':pack.stat().st_size,'stats':stats.as_dict(),
                          'process_rss_before':rss_before,'process_rss_after':psutil.Process().memory_info().rss,
                          'encoder_identity':json.loads(metadata['encoder_identity']) if metadata.get('encoder_identity') else None,
                          'torch_cpu_threads':2 if mode=='semantic' else None}
            write_json(root/'compilation.json',{'builds':builds,'corpora':corpora})
            print({'compiled':name,'milliseconds':elapsed,'blocks':len(blocks),'available_tokens':available},flush=True)
        encoder_start=time.perf_counter_ns()
        import torch
        from npk.context.embedding import get_backend
        torch.set_num_threads(2)
        backend=get_backend();assert backend.available()
        assert backend.identity()==builds['semantic2048']['encoder_identity']
        encoder_setup_ms=(time.perf_counter_ns()-encoder_start)/1e6
        write_json(root/'compilation.json',{'builds':builds,'corpora':corpora,'compilation_origin':compilation_origin,'query_encoder_setup_ms':encoder_setup_ms})
        rng=random.Random(2409)
        for trial in range(3):
            order=[(t,name,b) for t in tasks for name in configurations for b in budgets];rng.shuffle(order)
            for task,name,budget in order:
                artifact,policy,ranking=configurations[name];pack=packs[artifact];question=task['question']
                start=time.perf_counter_ns()
                if policy=='public':
                    selected=PackSelector(pack,retrieval=ranking).select(question,budget_tokens=budget)
                    pieces,context=public_context(selected,budget)
                    status='fallback_required' if selected.seed_failed or not pieces else 'selected'
                    notes=selected.notes;channels=selected.channels_used;risk=selected.risk_band
                    original_query=selected.query;tokens=estimate_tokens(context) if pieces else 0
                else:
                    selected=select(pack,question,budget,mode=policy,ranking=ranking)
                    pieces=selected.pieces;context=selected.context_text();status=selected.status
                    notes=selected.notes;channels=selected.channels;risk=selected.risk
                    original_query=selected.query;tokens=selected.selected_tokens
                elapsed=(time.perf_counter_ns()-start)/1e6
                assert original_query==question and tokens<=budget
                validate_pieces(source,pieces);digest=sha(context.encode());(root/'contexts'/(digest+'.txt')).write_bytes(context.encode())
                rows.append({'task':task['id'],'method':name,'budget':budget,'trial':trial,'selection_ms':elapsed,
                             'corpus_tokens':corpus_tokens,'available_tokens':corpora[artifact]['available_tokens'],
                             'baseline_prompt_tokens':estimate_tokens(raw+'\n\n'+question),'selected_tokens':tokens,
                             'context_sha256':digest,'status':status,'risk':risk,'channels':channels,'notes':notes,
                             'pieces':[{'path':p.path,'start':p.start,'end':p.end,'span':p.span} for p in pieces],
                             **source_coverage(pieces,task['required'])})
            write_json(root/'observations.json',{'rows':rows});print({'trial':trial,'selections':len(rows)},flush=True)
    assert code=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    unique=[]
    for task in tasks:
        for name in configurations:
            for budget in budgets:
                group=[r for r in rows if (r['task'],r['method'],r['budget'])==(task['id'],name,budget)]
                assert len(group)==3 and len({r['context_sha256'] for r in group})==1
                record={k:v for k,v in group[0].items() if k not in ('trial','selection_ms')}
                record['median_selection_ms']=statistics.median(r['selection_ms'] for r in group);unique.append(record)
    summary=[]
    for name in configurations:
        for budget in budgets:
            group=[r for r in unique if r['method']==name and r['budget']==budget]
            summary.append({'method':name,'budget':budget,'tasks':len(group),'all_required_spans':sum(r['all_required_spans'] for r in group),
                            'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group),
                            'median_selection_ms':statistics.median(r['median_selection_ms'] for r in group),
                            'fallbacks':sum(r['status']=='fallback_required' for r in group)})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','builds':builds,'corpora':corpora,'rows':rows,'unique':unique,'summary':summary,'query_encoder_setup_ms':encoder_setup_ms})
    print({'complete':True,'summary':summary})


if __name__=='__main__':main()

"""Matched-budget query-view experiment with executable labels kept out of search."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch
from benchmarks.operation_seeds import METHODS,rank,focused_text,question_views,operation_views
from benchmarks.unit_passages import select
from benchmarks.unit_answer_plan import reconstruct,tokens
from benchmarks.evidence_diagnostics import Piece,render
from benchmarks.repository_eval import source_coverage
from benchmarks.compiled_source_contract import require_compiled_sources
from benchmarks.prospective_eval import write_json
from npk.pack import verify
from npk.pack.compile import _source_lines


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def new_required(tasks,sources):
    specs={
        'no_autoflush_explicit_flush':[('session_basics.rst',383,386),('session_basics.rst',415,421)],
        'expire_discards_pending':[('session_state_management.rst',477,484)],
        'refresh_autoflush_other':[('session_basics.rst',388,397)],
        'expunge_pending_insert':[('session_state_management.rst',395,400)],
        'merge_managed_copy':[('session_state_management.rst',225,230)],
        'nested_rollback_selectivity':[('session_transaction.rst',207,213)],
        'rollback_pending_state':[('session_basics.rst',714,717),('session_state_management.rst',395,396)],
        'identity_map_reload':[('session_basics.rst',457,461),('session_basics.rst',527,535)],
        'autoflush_during_select':[('session_basics.rst',388,394)],
        'dynamic_reset_reuse':[('session_basics.rst',757,761),('session_basics.rst',770,776)],
    }
    assert set(specs)=={t['id'] for t in tasks};result=[]
    for task in tasks:
        required=[]
        for name,start,end in specs[task['id']]:
            path='sqlalchemy/doc/build/orm/'+name;text='\n'.join(sources[path][start-1:end]);assert text.strip()
            required.append({'path':path,'span':[start,end],'text_sha256':sha(text.encode())})
        result.append({**task,'required':required,'cohort':'new_scenarios'})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--new-tasks',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New frozen operation run required')
    parent=read(a.parent/'results.json');acquired=read(a.corpus/'acquisition.json');oracle=read(a.new_tasks)
    assert oracle['oracle_source_sha256']==sha((repo/'benchmarks/operation_oracles.py').read_bytes())
    assert oracle['helper_source_sha256']==sha((repo/'benchmarks/sqlalchemy_oracles.py').read_bytes())
    sources={}
    for item in acquired['source_manifest']:
        body=(a.corpus/'source'/item['path']).read_bytes();assert sha(body)==item['sha256'];sources[item['path']]=_source_lines(body.decode())
    tasks=[{**t,'cohort':'known_scenarios'} for t in parent['tasks']]+new_required(oracle['tasks'],sources)
    # Deliberately irrelevant, explicitly separated query padding is an attack,
    # not a new independent answer task. It leaves every scenario byte intact.
    padding=('Unrelated inventory from a different service; it has no bearing on the scenario below.\n'+
             'connection pool retry cache route mapper join delete cascade transaction schema namespace index metadata event listener batch result.\n'*18+
             'End of unrelated inventory. The actual question and scenario follow.\n\n')
    requests=[]
    for task in tasks:
        for layout in ('original','padded'):
            requests.append({**task,'base_task':task['id'],'id':task['id']+'-'+layout,'layout':layout,
                             'question':task['question'] if layout=='original' else padding+task['question']})
    packs={name:a.parent/(name+'.npk') for name in ('fixed2048','semantic2048')}
    for name,pack in packs.items():
        assert sha(pack.read_bytes())==parent['corpora'][name]['pack_sha256'] and verify(pack)['ok']
        require_compiled_sources(pack,acquired['source_manifest'])
    budgets=[1024,2048,4096];code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,'tasks':requests,'methods':METHODS,'budgets':budgets,'trials':3,
              'source_manifest':acquired['source_manifest'],'corpora':parent['corpora'],'builds':parent['builds'],
              'parent_results_sha256':sha((a.parent/'results.json').read_bytes()),'new_oracle_sha256':sha(a.new_tasks.read_bytes()),
              'reference':{'python_ast':'https://docs.python.org/3.12/library/ast.html','sqlite_fts5':'https://www.sqlite.org/fts5.html','checked_on':'2026-09-07'},
              'limitations':['20 developer-authored executable scenarios; ten known and ten new in an inspected corpus, not sealed independent validation',
                             'Padding creates paired robustness checks, not independent answer tasks',
                             'Annotated passages are incomplete diagnostics; some API bodies are in Python source not included in this manual corpus',
                             'Original query and system instructions survive; focused views only rank candidates, not guarantee semantic preservation or evidence sufficiency',
                             'Existing clause splitting/fusion is reused over the shared lexical index, not the old separately fielded-index implementation',
                             'All methods share blocks, candidate limits and provenance-budgeted assembly; no new compilation or index cost',
                             'Queries, source evidence and API costs use separate accounting; no answer accuracy or dollar claims from LOCAL retention',
                             'Three shuffled sweeps, host load uncontrolled; no overlapping agent CPU benchmarks, tests, archive compression or LIVE calls']}
    root.mkdir(parents=True);(root/'contexts').mkdir();write_json(root/'manifest.json',manifest)
    write_json(root/'execution-sources.json',{name:(repo/name).read_bytes().decode() for name in code})
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    full=render([Piece(path,1,len(lines),'\n'.join(lines)) for path,lines in sorted(sources.items())],True)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL query experiment attempted network')):
        import torch
        from npk.context.embedding import get_backend
        torch.set_num_threads(2);backend=get_backend();assert backend.available()
        assert backend.identity()==parent['builds']['semantic2048']['encoder_identity']
        windows=[]
        for task in requests:
            query=task['question'];focus,spans=focused_text(query);operations,signals=operation_views(query)
            views={'full':query,'question':focus,'operations':' '.join(v.text for v in operations)}
            row={'task':task['id'],'base_task':task['base_task'],'layout':task['layout'],'views':{},'question_spans':[vars(v) for v in spans],
                 'operation_spans':[vars(v) for v in operations],'operation_signals':signals}
            for name,text in views.items():
                encoded=backend._tokenizer(text,truncation=False,return_offsets_mapping=True,add_special_tokens=True)
                truncated=backend._tokenizer(text,truncation=True,max_length=backend.max_length,return_offsets_mapping=True,add_special_tokens=True)
                offsets=[(s,e) for s,e in truncated['offset_mapping'] if e>s];end=max((e for s,e in offsets),default=0)
                row['views'][name]={'text':text,'tokenizer_input_tokens':len(encoded['input_ids']),
                                    'kept_encoder_tokens':len(truncated['input_ids']),'retained_text_end':end,'truncated':end<len(text.rstrip()),
                                    'retained_text':text[:end]}
            windows.append(row)
        write_json(root/'encoder-windows.json',windows)
        print({'prepared_requests':len(requests),'base_scenarios':len(tasks),'methods':len(METHODS),'budgets':budgets},flush=True)
        rows=[];rng=random.Random(2707)
        for trial in range(3):
            cells=[(t,m,b) for t in requests for m in METHODS for b in budgets];rng.shuffle(cells)
            for task,method,budget in cells:
                observed={};start=time.perf_counter_ns()
                def routed(con,query,limit):
                    ids,signals=rank(con,query,method,limit);observed.update(signals);return ids
                pack=packs['semantic2048' if method in ('hybrid','question_hybrid') else 'fixed2048']
                with patch('benchmarks.unit_passages._lexical_channel',routed):
                    result=select(pack,task['question'],budget,system_prompt='Preserve the caller instructions exactly.')
                elapsed=(time.perf_counter_ns()-start)/1e6;context=result.context_text()
                assert result.query==task['question'] and result.system_prompt=='Preserve the caller instructions exactly.' and not result.used_generative_llm
                coverage=source_coverage(result.pieces,task['required'])
                row={'trial':trial,'task':task['id'],'base_task':task['base_task'],'cohort':task['cohort'],'layout':task['layout'],'method':method,'budget':budget,
                     'corpus_tokens':parent['corpora']['fixed2048']['corpus_tokens'],'available_tokens':result.available_tokens,
                     'baseline_prompt_tokens_estimate':tokens(f'SOURCE\n{full}\n\nQUESTION\n{task["question"]}'),
                     'selected_prompt_tokens_estimate':tokens(f'SOURCE\n{context}\n\nQUESTION\n{task["question"]}'),
                     'selected_tokens':result.selected_tokens,'context_sha256':sha(context.encode()),'status':result.status,'signals':observed,
                     'notes':result.notes,'latency_ms':elapsed,**coverage,'pieces':[{'path':v.path,'start':v.start,'end':v.end,'span':v.span} for v in result.pieces]}
                assert reconstruct(row,sources)[1]==context
                (root/'contexts'/(row['context_sha256']+'.txt')).write_bytes(context.encode());rows.append(row)
            write_json(root/'observations.json',rows);print({'trial':trial,'observations':len(rows)},flush=True)
    grouped={}
    for row in rows:grouped.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    unique=[]
    for group in grouped.values():
        assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
        unique.append({k:v for k,v in group[0].items() if k not in ('trial','latency_ms')}|{'median_ms':statistics.median(r['latency_ms'] for r in group)})
    summary=[]
    for cohort in ('known_scenarios','new_scenarios'):
        for layout in ('original','padded'):
            for method in METHODS:
                for budget in budgets:
                    group=[r for r in unique if (r['cohort'],r['layout'],r['method'],r['budget'])==(cohort,layout,method,budget)]
                    summary.append({'cohort':cohort,'layout':layout,'method':method,'budget':budget,'tasks':len(group),
                                    'all_required_passages':sum(r['all_required_spans'] for r in group),'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group),
                                    'median_ms':statistics.median(r['median_ms'] for r in group),'embedding_used':sum(r['signals'].get('embedding_used',False) for r in group),
                                    'fallback_required':sum(r['status']=='fallback_required' for r in group)})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'unique':unique,'summary':summary})
    print({'status':'COMPLETE','observations':len(rows),'cells':len(unique),'summary':summary},flush=True)


if __name__=='__main__':main()

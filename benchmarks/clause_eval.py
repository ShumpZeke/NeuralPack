"""Matched-budget LOCAL verbatim-clause challengers through public .npk selection."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import statistics
import time
from unittest.mock import patch
from benchmarks.clause_seeds import build,rank,METHODS
from benchmarks.repository_eval import source_coverage
from benchmarks.evidence_diagnostics import from_evidence,validate_pieces
from benchmarks.prospective_eval import write_json
from npk.pack import PackSelector,verify
from npk.pack.format import open_pack,load_blocks


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def timed(call):
    start=time.perf_counter();value=call();return value,(time.perf_counter()-start)*1000


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--tasks',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];run=a.run.resolve();corpus=a.corpus.resolve()
    if run.exists():raise ValueError('new clause run required')
    prior=json.loads((a.parent/'results.json').read_text());fresh=json.loads(a.tasks.read_text())
    assert prior['status']=='COMPLETE' and sha(a.tasks)==a.tasks.with_suffix('.sha256').read_text().strip()
    assert fresh['definition_sha256']==sha(repo/'benchmarks/clause_tasks.py')
    tasks=[*fresh['tasks'],*[dict(t,cohort='previous_'+t['cohort']) for t in prior['tasks']]]
    assert len({t['id'] for t in tasks})==len(tasks)
    source=corpus/'expanded-source';pack=corpus/'expanded.npk'
    assert verify(pack)['ok']
    for item in prior['source_manifest']:assert sha(source/item['path'])==item['sha256']
    with open_pack(pack) as con:blocks=load_blocks(con)
    validate_pieces(source,[from_evidence(b) for b in blocks])
    full='\n\n'.join(b.text for b in blocks)
    raw_source='\n\n'.join((source/item['path']).read_text(encoding='utf-8') for item in prior['source_manifest'])
    methods=['bm25',*METHODS];budgets=[512,2048,8192]
    hashes={f.relative_to(repo).as_posix():sha(f) for directory in ('npk','benchmarks') for f in (repo/directory).rglob('*.py')}
    manifest={'status':'PREPARED','evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'methods':methods,'budgets':budgets,
              'task_definition_sha256':sha(a.tasks),'parent_results_sha256':sha(a.parent/'results.json'),
              'source_manifest':prior['source_manifest'],'code_sha256':hashes,'pack_sha256':sha(pack),
              'available_tokens':len(full)//4,'corpus_tokens':len(raw_source)//4,
              'limitations':['Eight developer-authored new behavior cases, 28 previously inspected controls; not a sealed evaluation',
                             'Clause views are exact source-query spans, not semantic decomposition; original query always retained',
                             'Focus excludes only auxiliary clauses beginning with a JSON-output instruction; original still searched',
                             'Same blocks and chars/4 budget, 60 candidates with 240 empty-selection widening, no graph or neural models',
                             'Required source-span coverage is a diagnostic, not task accuracy or proof of sufficiency',
                             'One ranking per method/task reused across budgets; latency includes all search views but excludes one-time index build',
                             'Runtime core unchanged; SQLite OS caches and unrelated host activity uncontrolled']}
    run.mkdir(parents=True);contexts=run/'contexts';contexts.mkdir();write_json(run/'manifest.json',manifest)
    module=importlib.import_module('npk.pack.select');native=module._lexical_channel;selector=PackSelector(pack)
    rows=[];rankings=[]
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL clause run attempted network')):
        index=run/'clauses.sqlite';con,build_ms=timed(lambda:build(index,blocks))
        try:
            for i,task in enumerate(tasks):
                order=methods[i%len(methods):]+methods[:i%len(methods)]
                for method in order:
                    if method=='bm25':
                        with open_pack(pack) as original:ids,rank_ms=timed(lambda:native(original,task['question'],240))
                        info={'original_query':task['question'],'views':[{'start':0,'end':len(task['question']),'text':task['question']}],'policy':'bm25'}
                    else:
                        (ids,info),rank_ms=timed(lambda:rank(con,task['question'],method,240))
                    assert info['original_query']==task['question'] and info['views'][0]['text']==task['question']
                    assert all(v['text']==task['question'][v['start']:v['end']] for v in info['views'])
                    rankings.append({'task':task['id'],'method':method,'ids':ids,'ranking_ms':rank_ms,**info})
                    for budget in budgets:
                        def channel(db,query,limit):
                            assert query==task['question'];return ids[:limit]
                        with patch.object(module,'_lexical_channel',channel):
                            selected,assembly_ms=timed(lambda:selector.select(task['question'],budget_tokens=budget))
                        assert selected.query==task['question'] and selected.total_tokens<=budget and not selected.used_generative_llm
                        if method=='bm25':assert selector.select(task['question'],budget_tokens=budget).context_text()==selected.context_text()
                        validate_pieces(source,[from_evidence(e) for e in selected.evidence])
                        raw=selected.context_text().encode();digest=hashlib.sha256(raw).hexdigest();(contexts/(digest+'.txt')).write_bytes(raw)
                        present={e.path for e in selected.evidence};required_paths={r['path'] for r in task['required']}
                        rows.append({'corpus':'expanded','task':task['id'],'cohort':task['cohort'],'method':method,'budget':budget,
                                     'context_sha256':digest,'selected_tokens':selected.total_tokens,'available_tokens':selected.available_tokens,
                                     'corpus_tokens':len(raw_source)//4,'seed_failed':selected.seed_failed,'status':selected.as_dict()['status'],
                                     'risk_band':selected.risk_band,'selection_ms':rank_ms+assembly_ms,'ranking_ms':rank_ms,'assembly_ms':assembly_ms,
                                     'evidence':[e.as_dict(include_text=False) for e in selected.evidence],
                                     'selected_required_file_fraction':sum(path in present for path in required_paths)/len(required_paths),
                                     'required_source_present':all((source/path).is_file() for path in required_paths),
                                     **source_coverage(selected.evidence,task['required'])})
                print({'task':task['id'],'rows':len(rows)},flush=True)
        finally:con.close()
    assert all(sha(repo/path)==value for path,value in hashes.items())
    summary=[]
    for cohort in dict.fromkeys(t['cohort'] for t in tasks):
        for method in methods:
            for budget in budgets:
                group=[r for r in rows if (r['cohort'],r['method'],r['budget'])==(cohort,method,budget)]
                summary.append({'cohort':cohort,'method':method,'budget':budget,'tasks':len(group),
                                'all_required_spans':sum(r['all_required_spans'] for r in group),
                                'mean_required_span_fraction':statistics.mean(r['required_span_fraction'] for r in group),
                                'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group)})
    write_json(run/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'rankings':rankings,'summary':summary,
                                  'builds':[{'index_bytes':index.stat().st_size,'build_ms':build_ms,'blocks':len(blocks)}]})
    print({'COMPLETE':True,'observations':len(rows),'new_task_summary':[r for r in summary if r['cohort']=='prospective_clauses']},flush=True)


if __name__=='__main__':main()

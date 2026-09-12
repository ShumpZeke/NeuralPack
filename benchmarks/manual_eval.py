"""Matched-budget corpus ablation: original source versus source plus API manuals."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import statistics
import time
from unittest.mock import patch
from benchmarks.clause_seeds import build,rank
from benchmarks.repository_eval import source_coverage
from benchmarks.evidence_diagnostics import from_evidence,validate_pieces
from npk.pack import PackSelector,verify
from npk.pack.format import open_pack,load_blocks


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,value): path.write_text(json.dumps(value,indent=2),encoding='utf-8')
def timed(call):
    start=time.perf_counter_ns();value=call();return value,(time.perf_counter_ns()-start)/1e6


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manuals',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];run=a.run.resolve()
    if run.exists():raise ValueError('new matched-corpus run required')
    parent=repo/'experiments/runs/packs/cycle18-clauses-v1/results.json'
    data=json.loads(parent.read_text());assert data['status']=='COMPLETE'
    acquired=json.loads((a.manuals/'acquisition.json').read_text())
    assert acquired['parent_results_sha256']==sha(parent)
    assert sha(a.manuals/'acquisition.json')==(a.manuals/'acquisition.sha256').read_text()
    baseroot=repo/'experiments/runs/packs/cycle14-seeds-v1'
    configs={'original':(baseroot/'expanded.npk',baseroot/'expanded-source',data['source_manifest']),
             'with_manuals':(a.manuals/'full-0.npk',a.manuals/'source',acquired['source_manifest'])}
    old={(r['task'],r['method'],r['budget']):r for r in data['rows']}
    tasks=[dict(t,cohort='known_'+t['cohort']) for t in data['tasks']]
    methods=['bm25','flat_fields'];budgets=[512,2048,8192]
    code={f.relative_to(repo).as_posix():sha(f) for folder in ('npk','benchmarks') for f in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'methods':methods,'budgets':budgets,
              'parent_results_sha256':sha(parent),'acquisition_sha256':sha(a.manuals/'acquisition.json'),
              'code_sha256':code,'added_manuals':acquired['added'],
              'limitations':['All 36 questions were inspected previously; no independent sealed quality claim',
                             'Required CODE spans are a diagnostic only; selected manual prose may supply equivalent facts',
                             'Manual source paths indicate retrieval, not comprehension or sufficiency',
                             'Identical budget caps within and across declared corpora; available context grows only in the manual arm',
                             'No graph, dense model, reranker or generative optimizer; both methods share public pack assembly',
                             'One ranking per task/method reused across caps; indexing outside selection timing',
                             'No CPU tests/mutations overlapped; LIVE answer IO and uncontrolled host activity did']}
    run.mkdir(parents=True);(run/'contexts').mkdir();dump(run/'manifest.json',manifest)
    native=importlib.import_module('npk.pack.select')._lexical_channel
    module=importlib.import_module('npk.pack.select');rows=[];ranks=[];builds=[];corpora={}
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL retrieval attempted network')):
        for corpus,(pack,source,sources) in configs.items():
            assert verify(pack)['ok']
            for item in sources:assert sha(source/item['path'])==item['sha256']
            with open_pack(pack) as con:blocks=load_blocks(con)
            validate_pieces(source,[from_evidence(b) for b in blocks])
            available=len('\n\n'.join(b.text for b in blocks))//4
            total=len('\n\n'.join((source/i['path']).read_text(encoding='utf-8') for i in sources))//4
            corpora[corpus]={'available_tokens':available,'corpus_tokens':total,'source_manifest':sources,
                             'pack_sha256':sha(pack),'blocks':len(blocks)}
            selector=PackSelector(pack);index=run/(corpus+'.sqlite')
            con,build_ms=timed(lambda:build(index,blocks))
            builds.append({'corpus':corpus,'build_ms':build_ms,'index_bytes':index.stat().st_size})
            try:
                for i,task in enumerate(tasks):
                    for method in methods[i%2:]+methods[:i%2]:
                        if method=='bm25':
                            with open_pack(pack) as base:ids,rank_ms=timed(lambda:native(base,task['question'],240))
                        else:
                            (ids,info),rank_ms=timed(lambda:rank(con,task['question'],method,240))
                            assert info['original_query']==task['question']
                        ranks.append({'corpus':corpus,'task':task['id'],'method':method,'ids':ids,'ranking_ms':rank_ms})
                        for budget in budgets:
                            def channel(db,query,limit):
                                assert query==task['question'];return ids[:limit]
                            with patch.object(module,'_lexical_channel',channel):
                                selected,assembly_ms=timed(lambda:selector.select(task['question'],budget_tokens=budget))
                            assert selected.query==task['question'] and selected.total_tokens<=budget
                            assert selected.available_tokens==available and not selected.used_generative_llm
                            validate_pieces(source,[from_evidence(e) for e in selected.evidence])
                            raw=selected.context_text().encode();digest=hashlib.sha256(raw).hexdigest()
                            if corpus=='original':assert digest==old[(task['id'],method,budget)]['context_sha256']
                            (run/'contexts'/(digest+'.txt')).write_bytes(raw)
                            rows.append({'corpus':corpus,'cohort':task['cohort'],'task':task['id'],'method':method,'budget':budget,
                                'available_tokens':available,'corpus_tokens':total,'selected_tokens':selected.total_tokens,
                                'context_sha256':digest,'selection_ms':rank_ms+assembly_ms,'ranking_ms':rank_ms,'assembly_ms':assembly_ms,
                                'seed_failed':selected.seed_failed,'status':selected.as_dict()['status'],'risk_band':selected.risk_band,
                                'evidence':[e.as_dict(include_text=False) for e in selected.evidence],
                                'required_source_present':all((source/r['path']).is_file() for r in task['required']),
                                'manual_paths':sorted({e.path for e in selected.evidence}&{m['path'] for m in acquired['added']}),
                                **source_coverage(selected.evidence,task['required'])})
                print({'corpus':corpus,'available_tokens':available,'rows':len(rows)},flush=True)
            finally:con.close()
    assert code=={f.relative_to(repo).as_posix():sha(f) for folder in ('npk','benchmarks') for f in (repo/folder).rglob('*.py')}
    summary=[]
    for corpus in configs:
        for cohort in dict.fromkeys(t['cohort'] for t in tasks):
            for method in methods:
                for budget in budgets:
                    group=[r for r in rows if (r['corpus'],r['cohort'],r['method'],r['budget'])==(corpus,cohort,method,budget)]
                    summary.append({'corpus':corpus,'cohort':cohort,'method':method,'budget':budget,'tasks':len(group),
                        'all_required_code_spans':sum(r['all_required_spans'] for r in group),
                        'mean_required_code_span_fraction':statistics.mean(r['required_span_fraction'] for r in group),
                        'tasks_with_manuals':sum(bool(r['manual_paths']) for r in group),
                        'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group)})
    assert len(rows)==432
    dump(run/'results.json',{**manifest,'status':'COMPLETE','corpora':corpora,'rows':rows,'rankings':ranks,'builds':builds,'summary':summary})
    print({'complete':True,'observations':len(rows),'original_contexts_reproduced':216})


if __name__=='__main__':main()

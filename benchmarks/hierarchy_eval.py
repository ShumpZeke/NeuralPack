"""Frozen LOCAL document-routing challengers with matched source and budgets."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import time
from unittest.mock import patch
from benchmarks.hierarchical_seeds import build,rank,documents,METHODS
from benchmarks.repository_eval import source_coverage
from benchmarks.evidence_diagnostics import from_evidence,validate_pieces
from benchmarks.prospective_eval import write_json
from npk.pack import PackSelector,verify
from npk.pack.format import open_pack,load_blocks


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def timed(call):
    start=time.perf_counter();value=call();return value,1000*(time.perf_counter()-start)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--tasks',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    args=p.parse_args();repo=Path(__file__).resolve().parents[1];run=args.run.resolve();parent=args.parent.resolve()
    if run.exists():raise ValueError('new hierarchy run required')
    prior=json.loads((parent/'results.json').read_text());fresh=json.loads(args.tasks.read_text())
    assert sha(args.tasks)==args.tasks.with_suffix('.sha256').read_text().strip()
    tasks=[*fresh['tasks'],*[dict(t,cohort='previous_stdlib_controls' if t['cohort']=='prospective_stdlib' else t['cohort']) for t in prior['tasks']]]
    methods=['bm25',*METHODS];budgets=[512,2048,8192]
    hashes={p.relative_to(repo).as_posix():sha(p) for directory in ('npk','benchmarks') for p in (repo/directory).rglob('*.py')}
    manifest={'status':'PREPARED','evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'methods':methods,'budgets':budgets,
              'task_definition_sha256':sha(args.tasks),'parent_results_sha256':sha(parent/'results.json'),
              'source_manifest':prior['source_manifest'],'code_sha256':hashes,
              'limitations':['Eight new composed questions are developer-authored, not independent holdout; twenty previous cases are explicit controls',
                             'Questions combine known libraries and are correlated with previous component questions',
                             'Click-only lacks all new standard-library source; those rows are out-of-corpus diagnostics, not promotion evidence',
                             'Document routing uses full-source BM25 with fixed metadata weights; no generative rewriting, embeddings or graph',
                             'Fixed gates of 1,4,16 files, soft reciprocal-rank prior, balanced four-file sampling and flat escape are uncalibrated challengers',
                             'Query-time rankings are injected into the public lexical channel; no production retrieval defaults change',
                             'All methods use identical window blocks, initial 60 candidates with 240 empty-selection escalation, and floor(chars/4) budget caps',
                             'Whole required-span coverage does not establish sufficient evidence or task accuracy',
                             'File-presence/routing coverage uses known source labels only during evaluation, never during ranking',
                             'Timing is one standalone ranking per task/method with rotated order, reused across budgets; local OS caches uncontrolled']}
    run.mkdir(parents=True);contexts=run/'contexts';contexts.mkdir();write_json(run/'manifest.json',manifest)
    module=importlib.import_module('npk.pack.select');native_lexical=module._lexical_channel
    rows=[];rankings=[];builds=[]
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL hierarchy experiment attempted network')):
        for corpus in ('expanded','click_only'):
            pack=parent/(corpus+'.npk');source=parent/(corpus+'-source')
            assert verify(pack)['ok']
            for item in prior['source_manifest']:
                if corpus=='click_only' and item['path'].startswith('cpython/'):continue
                assert sha(source/item['path'])==item['sha256']
            with open_pack(pack) as con:blocks=load_blocks(con)
            validate_pieces(source,[from_evidence(b) for b in blocks]);lookup={b.id:b for b in blocks}
            index=run/(corpus+'-hierarchy.sqlite');con,build_ms=timed(lambda:build(index,blocks,source))
            builds.append({'corpus':corpus,'build_ms':build_ms,'index_bytes':index.stat().st_size,'blocks':len(blocks),
                           'pack_sha256':sha(pack),'pack_bytes':pack.stat().st_size})
            selector=PackSelector(pack)
            for i,task in enumerate(tasks):
                doc_ranks,doc_ms=timed(lambda:documents(con,task['question']))
                required_paths=sorted({r['path'] for r in task['required']})
                order=methods[i%len(methods):]+methods[:i%len(methods)]
                for method in order:
                    if method=='bm25':
                        with open_pack(pack) as original:
                            ids,ranking_ms=timed(lambda:native_lexical(original,task['question'],240))
                        info={'routed_paths':[],'policy':'bm25'}
                    else:
                        result,ranking_ms=timed(lambda:rank(con,task['question'],method,240));ids,info=result
                    assert len(ids)==len(set(ids)) and all(key in lookup for key in ids)
                    candidate_paths={lookup[key].path for key in ids}
                    ranks_record={'corpus':corpus,'task':task['id'],'method':method,'candidate_ids':ids,'ranking_ms':ranking_ms,
                                  **info,'document_ranks':doc_ranks,'document_rank_ms':doc_ms,'required_paths':required_paths,
                                  'candidate_required_file_fraction':sum(p in candidate_paths for p in required_paths)/len(required_paths)}
                    rankings.append(ranks_record)
                    for budget in budgets:
                        def channel(db,query,limit):
                            assert query==task['question'];return ids[:limit]
                        with patch.object(module,'_lexical_channel',channel):
                            selected,assembly_ms=timed(lambda:selector.select(task['question'],budget_tokens=budget))
                        assert selected.query==task['question'] and selected.total_tokens<=budget and not selected.used_generative_llm
                        if method=='bm25':assert selector.select(task['question'],budget_tokens=budget).context_text()==selected.context_text()
                        validate_pieces(source,[from_evidence(e) for e in selected.evidence])
                        raw=selected.context_text().encode();digest=hashlib.sha256(raw).hexdigest()
                        (contexts/(digest+'.txt')).write_bytes(raw)
                        present={e.path for e in selected.evidence}
                        rows.append({'corpus':corpus,'task':task['id'],'cohort':task['cohort'],'method':method,'budget':budget,
                            'context_sha256':digest,'selected_tokens':selected.total_tokens,'available_tokens':selected.available_tokens,
                            'seed_failed':selected.seed_failed,'status':selected.as_dict()['status'],'risk_band':selected.risk_band,
                            'selection_ms':ranking_ms+assembly_ms,'ranking_ms':ranking_ms,'assembly_ms':assembly_ms,
                            'evidence':[e.as_dict(include_text=False) for e in selected.evidence],
                            'required_source_present':all((source/p).is_file() for p in required_paths),
                            'selected_required_file_fraction':sum(p in present for p in required_paths)/len(required_paths),
                            **source_coverage(selected.evidence,task['required'])})
                print({'corpus':corpus,'task':task['id'],'observations':len(rows)},flush=True)
            con.close();write_json(run/'results.json',{**manifest,'status':'RUNNING','rows':rows,'rankings':rankings,'builds':builds})
    assert all(sha(repo/path)==digest for path,digest in hashes.items())
    write_json(run/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'rankings':rankings,'builds':builds})
    print({'status':'COMPLETE','observations':len(rows),'generative_calls':0})


if __name__=='__main__':main()

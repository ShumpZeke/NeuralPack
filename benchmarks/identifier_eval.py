"""Matched-budget LOCAL seed comparison on a frozen public Click collection.

Candidate channels are injected into the actual PackSelector assembly, labelled
as prototypes. Frozen task answers are not used for retrieval or local scoring.
"""
import argparse
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import statistics
import time
from unittest.mock import patch


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run',type=Path)
    parser.add_argument('--semantic',action='store_true');parser.add_argument('--rerank',action='store_true')
    args=parser.parse_args();repo=Path(__file__).resolve().parents[1]
    run=(args.run or repo/'experiments/runs/packs/cycle12-seeds').resolve()
    if run.exists() or args.output.exists():raise ValueError('new run/output paths required')
    run.mkdir();source=run/'source';source.mkdir()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_CACHE=str(repo/'experiments/models/hf_cache'))
    from npk.pack import compile_pack,verify,PackSelector
    from npk.pack.format import open_pack,load_blocks
    from benchmarks.repository_eval import source_coverage
    from benchmarks.repository_rerank import LocalReranker,MODEL_ID,REVISION
    from benchmarks.seed_candidates import rank
    from benchmarks.identifier_report import canonical_tasks
    module=importlib.import_module('npk.pack.select')
    plan_path=repo/'experiments/runs/repository-click-v1/plan.json';plan=json.loads(plan_path.read_text())
    assert sha(plan_path)==plan_path.with_suffix('.sha256').read_text().strip()
    origin=plan_path.parent/'source/click-8.5.0'
    for item in plan['source_manifest']:
        path=origin/item['path'];assert sha(path)==item['sha256']
        target=source/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    task_path=repo/'experiments/results/cycle12-identifier-tasks.json'
    assert sha(task_path)==task_path.with_suffix('.sha256').read_text().strip()
    fresh=json.loads(task_path.read_text())
    tasks=[dict(t,cohort='identifier_pairs') for t in fresh['tasks']]+[dict(t,cohort='previous_behavior_controls',family=t['id'],query_style='original') for t in plan['dataset']['tasks']]
    tasks,namespace_mapping=canonical_tasks(tasks,plan['source_manifest'],source,'src/click/')
    methods=['bm25','bm25_source_scope','camel_expansion','empty_seed_expansion','lexical_fusion','symbol_priority']
    if args.semantic:methods.append('hybrid')
    if args.rerank:methods.append('cross_encoder')
    budgets=[512,2048,8192]
    hashes={p.relative_to(repo).as_posix():sha(p) for directory in ('npk','benchmarks') for p in (repo/directory).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'source_manifest':plan['source_manifest'],
              'required_path_mapping':namespace_mapping,
              'new_tasks_sha256':sha(task_path),'source_code_sha256':hashes,'methods':methods,'budgets':budgets,
              'notes':['Prototypes replace candidate channel only; selection, budgeting, fallback and original query use PackSelector',
                       'Source-only BM25 has explicitly supplied src/click/ scope; its metadata advantage is disclosed',
                       'Full required source spans are not proven minimum sufficient context; coverage is not accuracy',
                       'Identifier/prose variants share gold facts; prior 12 controls were previously inspected',
                       'Model reranking is cached across budgets; CPU latency is reported separately, not as repeated model work']}
    (run/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    reranker=None
    if args.rerank:
        start=time.perf_counter();reranker=LocalReranker(repo/'experiments/models/hf_cache')
        manifest['reranker']={'id':MODEL_ID,'revision':REVISION,'load_ms':1000*(time.perf_counter()-start),'max_length':512,'candidates':60}
    rows=[];compilations=[]
    for members in (False,True):
        policy='members' if members else 'windows';pack=run/(policy+'.npk')
        stats=compile_pack(source,pack,mode='semantic' if args.semantic else 'deterministic',python_members=members)
        assert verify(pack)['ok']
        # Independently reconstruct every compiled block before measuring any
        # retrieval. Hash consistency alone cannot establish literal provenance.
        with open_pack(pack) as con:
            for block in load_blocks(con):
                lines=(source/block.path).read_text(encoding='utf-8').split('\n')
                assert 1<=block.start_line<=block.end_line<=len(lines)
                assert block.text=='\n'.join(lines[block.start_line-1:block.end_line])
        if args.semantic:assert stats.embedded==stats.blocks
        compilations.append({'policy':policy,'stats':stats.as_dict(),'disk_bytes':pack.stat().st_size})
        for index,task in enumerate(tasks):
            reranked=None;rerank_ms=0
            if reranker is not None:
                with open_pack(pack) as con:
                    ids=rank(con,task['question'],60,'bm25');blocks={b.id:b for b in load_blocks(con,ids)}
                start=time.perf_counter();ordered,_=reranker.rank(task['question'],[blocks[i] for i in ids])
                rerank_ms=1000*(time.perf_counter()-start);reranked=[b.id for b in ordered]
            order=methods[index%len(methods):]+methods[:index%len(methods)]
            for method in order:
                selector=PackSelector(pack,retrieval='hybrid' if method=='hybrid' else 'lexical')
                def channel(con,query,limit):
                    return reranked[:limit] if method=='cross_encoder' else rank(con,query,limit,method)
                for budget in budgets:
                    start=time.perf_counter()
                    if method=='hybrid':selected=selector.select(task['question'],budget_tokens=budget)
                    else:
                        with patch.object(module,'_lexical_channel',channel):selected=selector.select(task['question'],budget_tokens=budget)
                    elapsed=1000*(time.perf_counter()-start)
                    assert selected.total_tokens<=budget and selected.query==task['question'] and not selected.used_generative_llm
                    rows.append({'task':task['id'],'family':task['family'],'cohort':task['cohort'],'query_style':task['query_style'],
                                 'policy':policy,'method':method,'budget':budget,'available_tokens':selected.available_tokens,
                                 'selected_tokens':selected.total_tokens,'seed_failed':selected.seed_failed,'selection_ms':elapsed,
                                 'rerank_ms':rerank_ms if method=='cross_encoder' else 0,'context':selected.context_text(),
                                 'context_sha256':hashlib.sha256(selected.context_text().encode()).hexdigest(),
                                 'evidence':[e.as_dict(include_text=False) for e in selected.evidence],
                                 **source_coverage(selected.evidence,task['required'])})
            print({'policy':policy,'task':task['id'],'rerank_ms':round(rerank_ms,1)},flush=True)
        # Durable checkpoint after each policy, including raw context and provenance.
        args.output.write_bytes(gzip.compress(json.dumps({**manifest,'status':'RUNNING','compilations':compilations,'rows':rows}).encode(),mtime=0))
    assert all(sha(repo/path)==digest for path,digest in hashes.items())
    args.output.write_bytes(gzip.compress(json.dumps({**manifest,'status':'COMPLETE','compilations':compilations,'rows':rows}).encode(),mtime=0))


if __name__=='__main__':main()

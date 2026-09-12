"""Freeze answer trials from independently checked LOCAL identifier selections.

No API calls here. Execute the resulting plan with prospective_eval only after
preflight. The prose member of each correlated pair is fixed before live answers.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from benchmarks.identifier_report import regrade
from benchmarks.identifier_tasks import TASKS
from benchmarks.prospective_eval import SYSTEM, request_key, write_json
from npk.pack.compile import estimate_tokens
from npk.pack.format import open_pack, load_blocks, verify


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(local, source, pack, output):
    repo=Path(__file__).resolve().parents[1]
    if output.exists():raise ValueError('new plan directory required')
    report=regrade(json.loads(gzip.decompress(local.read_bytes())),source)
    for name in ('benchmarks/identifier_tasks.py','benchmarks/identifier_report.py'):
        if sha(repo/name)!=report['source_code_sha256'][name]:
            raise ValueError('task or provenance code changed since LOCAL execution')
    # Reproduce executable answers before any request can be dispatched.
    tasks=[t for t in report['tasks'] if t['cohort']=='identifier_pairs' and t['query_style']=='prose']
    assert len(tasks)==len(TASKS)==8
    definitions={t.id:t for t in TASKS}
    with patch('socket.socket.connect',side_effect=AssertionError('oracle attempted network')):
        for task in tasks:assert definitions[task['family']].oracle()==task['answer']
    if not verify(pack)['ok']:raise ValueError('full-context artifact failed verification')
    with open_pack(pack) as con:
        blocks=load_blocks(con)
        stored={row['path']:row['sha256'] for row in con.execute('SELECT path,sha256 FROM files')}
    if stored!={f['path']:f['sha256'] for f in report['source_manifest']}:
        raise ValueError('full-context artifact differs from the declared collection')
    for block in blocks:
        lines=(source/block.path).read_text(encoding='utf-8').split('\n')
        if block.text!='\n'.join(lines[block.start_line-1:block.end_line]):
            raise ValueError('full-context block has invalid source provenance')
    full='\n\n'.join(b.text for b in blocks)
    corpus='\n\n'.join((source/f['path']).read_text(encoding='utf-8') for f in report['source_manifest'])
    corpus_tokens=estimate_tokens(corpus);available_tokens=estimate_tokens(full)
    settings={'model':'deepseek-ai/deepseek-v4-flash-0731','reasoning_effort':'none',
              'max_output_tokens':2048,'timeout_seconds':90,'system_prompt':SYSTEM}
    methods={'bm25':'bm25_windows','bm25_source_scope':'bm25_source_scope',
             'hybrid':'hybrid_windows','cross_encoder':'cross_encoder_windows'}
    budgets=[512,2048,8192]
    by_key={(r['task'],r['method'],r['budget']):r for r in report['rows'] if r['policy']=='windows'}
    output.mkdir(parents=True);contexts=output/'contexts';contexts.mkdir()
    observations=[];requests={}
    for index,task in enumerate(tasks):
        candidates=[('none',None,'',None),('full',None,full,None)]
        for budget in budgets:
            for method,label in methods.items():
                row=by_key[(task['id'],method,budget)]
                candidates.append((label,budget,row['context'],row))
        offset=index%len(candidates)
        for method,budget,context,local_row in candidates[offset:]+candidates[:offset]:
            context_sha=hashlib.sha256(context.encode()).hexdigest()
            (contexts/(context_sha+'.txt')).write_bytes(context.encode())
            key=request_key(settings,task['question'],context)
            count=estimate_tokens(context) if context else 0
            assert budget is None or count<=budget
            row={'task':task['id'],'method':method,'budget':budget,'request_sha256':key,
                 'context_sha256':context_sha,'corpus_tokens':corpus_tokens,'available_tokens':available_tokens,
                 'baseline_prompt_tokens_estimate':estimate_tokens(SYSTEM+f"SOURCE\n{full}\n\nQUESTION\n{task['question']}"),
                 'selected_tokens':count,
                 'selected_prompt_tokens_estimate':estimate_tokens(SYSTEM+f"SOURCE\n{context}\n\nQUESTION\n{task['question']}")}
            if local_row:
                row.update(selection_ms=local_row['selection_ms']+local_row['rerank_ms'],
                           local_assembly_ms=local_row['selection_ms'],local_rerank_ms=local_row['rerank_ms'],
                           seed_failed=local_row['seed_failed'],provenance=local_row['evidence'],
                           all_required_spans=local_row['all_required_spans'],
                           required_span_fraction=local_row['required_span_fraction'])
            observations.append(row)
            if local_row and (local_row['seed_failed'] or not context):
                row['status']='SELECTION_FAILED'
            else:requests.setdefault(key,{'question':task['question'],'context_sha256':context_sha})
    plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL',
          'champion_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
          'frozen_dataset_sha256':report['new_tasks_sha256'],'dataset':{'tasks':tasks},
          'settings':settings,'budgets':budgets,'configurations':methods,'compilations':report['compilations'],
          'source_manifest':report['source_manifest'],'local_report_sha256':sha(local),
          'corpus_tokens':corpus_tokens,'available_tokens':available_tokens,
          'token_estimator':'chars/4; context is exact selected block text, prompt estimates exclude chat framing',
          'selection_code_sha256':report['source_code_sha256'],
          'code_sha256':{p.relative_to(repo).as_posix():sha(p) for d in ('npk','benchmarks') for p in (repo/d).rglob('*.py')},
          'limitations':[
              'Eight developer-authored Click families; prose variants only, fixed before LIVE but after LOCAL diagnostics',
              'Windows policy and four methods chosen after LOCAL results; no externally sealed evaluation',
              'Source-scope BM25 is given explicit src/click/ metadata, also available to any competent baseline',
              'Required source spans are conservative diagnostics, not proven minimum sufficient context or accuracy',
              'Full control uses all compiled windows; source corpus count also reported per task',
              'Local timings come from the archived LOCAL run; reranker work reused across budget points is charged to each stand-alone query estimate',
              'Estimated budgets are matched; actual model input usage may differ',
              'One model configuration, endpoint caching/load uncontrolled, no verified dollar pricing',
              'No remote preprocessing arm is executed; no performance claim against that architecture'],
          'observations':observations,'requests':requests}
    write_json(output/'plan.json',plan)
    (output/'plan.sha256').write_text(sha(output/'plan.json'),encoding='ascii')
    print({'tasks':len(tasks),'observations':len(observations),'unique_requests':len(requests),
           'available_tokens':available_tokens,'generative_calls':0},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('local','source','pack','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();prepare(**vars(args))

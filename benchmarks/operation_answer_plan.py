"""Reconstruct every LOCAL selection before freezing target-answer requests."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.answer_records import import_replays
from benchmarks.prospective_eval import request_key,write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.unit_answer_plan import reconstruct,tokens
from benchmarks.evidence_diagnostics import Piece,render
from benchmarks.source_archive import manifest_sources
from npk.pack.compile import _source_lines
from npk.pack.source_policy import check_source


METHODS=('bm25','question_only','operations_rrf','hybrid','question_hybrid')
BUDGETS=(1024,4096)


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def prepare(local,corpus,parent_live,root):
    if root.exists():raise ValueError('New frozen target-answer run required')
    repo=Path(__file__).resolve().parents[1];data=read(local/'results.json');previous=read(parent_live/'plan.json')
    assert data['status']=='COMPLETE' and data['generative_calls']==0
    sources={name.removeprefix('source/'):_source_lines(body.decode()) for name,body in manifest_sources(corpus/'source',data['source_manifest'],'source').items()}
    tasks={t['id']:t for t in data['tasks']};cells={}
    for row in data['rows']:
        pieces,context=reconstruct(row,sources);assert (local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
        assert all(row[k]==v for k,v in source_coverage(pieces,tasks[row['task']]['required']).items())
        cells.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    assert len(data['rows'])==2880 and len(cells)==960
    for rows in cells.values():assert sorted(r['trial'] for r in rows)==[0,1,2] and len({r['context_sha256'] for r in rows})==1
    originals=[t for t in tasks.values() if t['layout']=='original'];assert len(originals)==20
    # Byte-identical old answer controls must correspond to the same scenarios,
    # not merely to method names or reported grades.
    old_questions={t['id']:t['question'] for t in previous['dataset']['tasks']}
    for task in originals:
        if task['cohort']=='known_scenarios':assert task['question']==old_questions[task['base_task']]
    full=render([Piece(path,1,len(lines),'\n'.join(lines)) for path,lines in sorted(sources.items())],True)
    check_source(full,'public-source answer control')
    settings=dict(previous['settings']);root.mkdir(parents=True);(root/'contexts').mkdir();observations=[];requests={}
    for i,task in enumerate(originals):
        conditions=[]
        for method in METHODS:
            for budget in BUDGETS:
                group=cells[task['id'],method,budget];row=group[0];_,context=reconstruct(row,sources)
                conditions.append((method,budget,context,row,sorted(r['latency_ms'] for r in group)[1]))
        conditions.extend([('none',None,'',None,0),('full',None,full,None,0)])
        offset=i%len(conditions)
        for method,budget,context,row,latency in conditions[offset:]+conditions[:offset]:
            digest=sha(context.encode());key=request_key(settings,task['question'],context)
            (root/'contexts'/(digest+'.txt')).write_bytes(context.encode())
            failed=row is not None and row['status']=='fallback_required'
            if not failed:requests.setdefault(key,{'question':task['question'],'context_sha256':digest})
            observations.append({'task':task['id'],'base_task':task['base_task'],'cohort':task['cohort'],'corpus':'sqlalchemy_manuals',
                                 'method':method,'budget':budget,'request_sha256':key,'context_sha256':digest,
                                 'corpus_tokens':data['corpora']['fixed2048']['corpus_tokens'],'available_tokens':data['corpora']['fixed2048']['available_tokens'],
                                 'selected_tokens':tokens(context),'selection_ms':latency,'status':'SELECTION_FAILED' if failed else 'SELECTED' if row else 'CONTROL',
                                 'baseline_prompt_tokens_estimate':tokens(settings['system_prompt']+f'SOURCE\n{full}\n\nQUESTION\n{task["question"]}'),
                                 'selected_prompt_tokens_estimate':tokens(settings['system_prompt']+f'SOURCE\n{context}\n\nQUESTION\n{task["question"]}'),
                                 'measurement':row})
    code={p.relative_to(repo).as_posix():{'sha256':sha(p.read_bytes()),'text':p.read_bytes().decode()} for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    (root/'preparation-sources.json.gz').write_bytes(gzip.compress(json.dumps(code).encode(),mtime=0))
    plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','settings':settings,'methods':METHODS,'budgets':BUDGETS,
          'dataset':{'tasks':[{'id':t['id'],'base_task':t['base_task'],'cohort':t['cohort'],'question':t['question'],'answer':t['expected'],'required':t['required']} for t in originals]},
          'source_manifest':data['source_manifest'],'local_results_sha256':sha((local/'results.json').read_bytes()),
          'preparation_sources_sha256':sha((root/'preparation-sources.json.gz').read_bytes()),'observations':observations,'requests':requests,
          'limitations':data['limitations']+[
              'Only original query layouts receive target answers; padded layouts remain LOCAL robustness diagnostics',
              'Five methods and two caps specified in preparation code before target answers; not independently sealed methods or tasks',
              'Byte-identical completed cycle24 requests, including transport failures, are imported as explicit REPLAY and never resubmitted',
              'One stochastic response per new payload with the same target configuration; no automatic retry of failed or uncertain requests',
              'No-source control measures prior knowledge and is not an empty-context optimization win',
              'Full-source control sends all 153 files without truncation; reported provider usage is separate from character estimates',
              'Zero generative optimizer calls; provider prices, billing, local dollar cost and net savings remain N/A']}
    assert len(observations)==240
    write_json(root/'plan.json',plan);(root/'plan.sha256').write_text(sha((root/'plan.json').read_bytes()),encoding='ascii')
    replays=import_replays(parent_live,root,plan)
    preflight={'evidence_mode':'LOCAL','generative_calls':0,'source_selections_reconstructed':2880,'unique_cells':960,
               'base_scenarios':20,'target_observations':240,'unique_requests':len(requests),'replay_import':replays,
               'plan_sha256':sha((root/'plan.json').read_bytes()),'full_source_tokens_estimate':tokens(full)}
    write_json(root/'preflight.json',preflight);print(preflight,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('local','corpus','parent-live','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();prepare(a.local.resolve(),a.corpus.resolve(),a.parent_live.resolve(),a.output.resolve())

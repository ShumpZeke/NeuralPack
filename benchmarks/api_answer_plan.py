"""Reconstruct frozen corpus comparisons and prepare explicit target-only requests."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import random
from benchmarks.api_source_eval import region_counts
from benchmarks.evidence_diagnostics import Piece,render
from benchmarks.prospective_eval import request_key,write_json
from benchmarks.replay_continuation import import_completed
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from benchmarks.unit_answer_plan import reconstruct,tokens
from npk.pack.compile import _source_lines


METHODS=('bm25','hybrid')
BUDGETS=(1024,4096)
CORPORA=('manuals','expanded')


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def prepare(local,corpus,parent_live,root):
    if root.exists():raise ValueError('New target-answer run required')
    repo=Path(__file__).resolve().parents[1];data=read(local/'results.json');parent=read(parent_live/'plan.json')
    assert data['status']=='COMPLETE' and data['generative_calls']==0
    sources={name.removeprefix('source/'):_source_lines(body.decode()) for name,body in manifest_sources(corpus/'source',data['source_manifests']['expanded'],'source').items()}
    inventory=read(corpus/'source-inventory.json');tasks={t['id']:t for t in data['tasks']};cells={}
    for row in data['rows']:
        pieces,context=reconstruct(row,sources);task=tasks[row['task']]
        assert (local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
        if task['required']:
            assert all(row[k]==v for k,v in source_coverage(pieces,task['required']).items())
        else:assert row['all_required_spans'] is None, 'Unannotated tasks cannot become automatic source-metric wins'
        assert all(row[k]==v for k,v in region_counts(pieces,inventory['docstrings']).items())
        cells.setdefault((row['task'],row['corpus'],row['method'],row['budget']),[]).append(row)
    assert len(data['rows'])==1080 and len(cells)==360 and len(tasks)==30
    for rows in cells.values():assert sorted(r['trial'] for r in rows)==[0,1,2] and len({r['context_sha256'] for r in rows})==1
    known={t['id']:t for t in parent['dataset']['tasks']}
    for task in tasks.values():
        if task['cohort']=='known_scenarios':assert task['question']==known[task['id']]['question'] and task['expected']==known[task['id']]['answer']
    full={cohort:render([Piece(item['path'],1,len(sources[item['path']]),'\n'.join(sources[item['path']])) for item in manifest],True)
          for cohort,manifest in data['source_manifests'].items()}
    settings=dict(parent['settings']);root.mkdir(parents=True);(root/'contexts').mkdir();observations=[];requests={}
    for index,task in enumerate(tasks.values()):
        conditions=[(c,m,b,cells[task['id'],c,m,b]) for c in CORPORA for m in METHODS for b in BUDGETS]
        conditions.append(('control','none',None,None));offset=index%len(conditions)
        for cohort,method,budget,group in conditions[offset:]+conditions[:offset]:
            if group:
                row=group[0];_,context=reconstruct(row,sources);selection_ms=sorted(r['latency_ms'] for r in group)[1]
                stats={k:row[k] for k in ('corpus_tokens','available_tokens','baseline_prompt_tokens_estimate','selected_prompt_tokens_estimate')}
                # LOCAL estimates exclude system; target-plan estimates explicitly add it.
                stats['baseline_prompt_tokens_estimate']=tokens(settings['system_prompt']+f'SOURCE\n{full[cohort]}\n\nQUESTION\n{task["question"]}')
                stats['selected_prompt_tokens_estimate']=tokens(settings['system_prompt']+f'SOURCE\n{context}\n\nQUESTION\n{task["question"]}')
            else:
                row=None;context='';selection_ms=0
                stats={'corpus_tokens':None,'available_tokens':None,'baseline_prompt_tokens_estimate':None,
                       'selected_prompt_tokens_estimate':tokens(settings['system_prompt']+f'SOURCE\n\n\nQUESTION\n{task["question"]}')}
            digest=sha(context.encode());key=request_key(settings,task['question'],context)
            (root/'contexts'/(digest+'.txt')).write_bytes(context.encode())
            failed=row is not None and row['status']=='fallback_required'
            if not failed:requests.setdefault(key,{'question':task['question'],'context_sha256':digest})
            observations.append({'task':task['id'],'cohort':task['cohort'],'corpus':cohort,'method':method,'budget':budget,
                                 'request_sha256':key,'context_sha256':digest,'selected_tokens':tokens(context),'selection_ms':selection_ms,
                                 'status':'SELECTION_FAILED' if failed else 'SELECTED' if row else 'CONTROL','measurement':row,**stats})
    keys=list(requests);random.Random(28017).shuffle(keys);requests={key:requests[key] for key in keys}
    code={p.relative_to(repo).as_posix():{'sha256':sha(p.read_bytes()),'text':p.read_bytes().decode()} for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    (root/'preparation-sources.json.gz').write_bytes(gzip.compress(json.dumps(code).encode(),mtime=0))
    plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','settings':settings,'methods':METHODS,'budgets':BUDGETS,'corpora':CORPORA,
          'dataset':{'tasks':[{'id':t['id'],'cohort':t['cohort'],'question':t['question'],'answer':t['expected']} for t in tasks.values()]},
          'source_manifests':data['source_manifests'],'local_results_sha256':sha((local/'results.json').read_bytes()),
          'preparation_sources_sha256':sha((root/'preparation-sources.json.gz').read_bytes()),'observations':observations,'requests':requests,
          'request_order_seed':28017,
          'limitations':data['limitations']+['Two methods, two caps and both corpora specified in preparation code before LOCAL results',
            'Request order shuffled before any new target calls; replayed payloads are skipped without changing remaining order',
            'No-source control measures prior knowledge; it is not an empty-context optimization success',
            'Expanded full source exceeds 2.5M estimated tokens; no full-source or remote-preprocessing arm is executed in this cycle',
            'One target response per new payload; failures remain missing and are never automatically retried',
            'Matching old payloads including failed calls retain explicit REPLAY and original LIVE provenance',
            'Dollar cost, net savings and billing break-even are N/A; provider usage is measured separately from character estimates']}
    assert len(observations)==270
    write_json(root/'plan.json',plan);(root/'plan.sha256').write_text(sha((root/'plan.json').read_bytes()),encoding='ascii')
    imported=import_completed(parent_live,root,plan)
    preflight={'evidence_mode':'LOCAL','generative_calls':0,'reconstructed_selections':1080,'unique_selection_cells':360,
               'base_scenarios':len(tasks),'target_observations':len(observations),'unique_requests':len(requests),
               'replayed_records':imported['replayed_records'],'inherited_replays':imported['inherited_replays'],
               'pending_new_requests':imported['pending_new_requests'],'plan_sha256':sha((root/'plan.json').read_bytes())}
    write_json(root/'preflight.json',preflight);print(preflight,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('local','corpus','parent-live','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();prepare(a.local,a.corpus,a.parent_live,a.output)

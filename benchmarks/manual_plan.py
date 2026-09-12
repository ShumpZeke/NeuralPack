"""Freeze a manual-corpus answer comparison and import only exact terminal replays."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch
from benchmarks.answer_records import import_replays
from benchmarks.modern_seed_plan import tokens
from benchmarks.prospective_eval import request_key,write_json
from npk.pack.format import open_pack,load_blocks


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--local',type=Path,required=True);p.add_argument('--manuals',type=Path,required=True)
    p.add_argument('--parent-live',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('new frozen answer plan required')
    data=json.loads((a.local/'results.json').read_text());assert data['status']=='COMPLETE'
    old_plan=json.loads((a.parent_live/'plan.json').read_text())
    assert sha(a.parent_live/'plan.json')==(a.parent_live/'plan.sha256').read_text().strip()
    ledger=json.loads((a.parent_live/'ledger.json').read_text())
    assert set(ledger)==set(old_plan['requests']) and all(e['state']=='DONE' for e in ledger.values())
    originals={t['id']:t for t in old_plan['dataset']['tasks']}
    for task in data['tasks']:
        assert task['question']==originals[task['id']]['question'] and task['answer']==originals[task['id']]['answer']
    # The LOCAL run predates reporting and mutation-harness repairs, not changes
    # to its measured retrieval algorithm. Both versions are retained explicitly.
    changed={name for name,value in data['code_sha256'].items() if sha(repo/name)!=value}
    assert changed <= {'benchmarks/economics.py','benchmarks/modern_seed_report.py',
                       'benchmarks/contract_mutations.py'}
    current={f.relative_to(repo).as_posix():sha(f) for folder in ('npk','benchmarks') for f in (repo/folder).rglob('*.py')}
    dependency=repo/'experiments/results/cycle18-checkpoint-evidence.json.xz'
    assert sha(dependency)==json.loads((repo/'experiments/results/cycle18-checkpoint-scan.json').read_text())['archive_sha256']
    sources={'original':repo/'experiments/runs/packs/cycle14-seeds-v1/expanded-source','with_manuals':a.manuals/'source'}
    packs={'original':repo/'experiments/runs/packs/cycle14-seeds-v1/expanded.npk','with_manuals':a.manuals/'full-0.npk'}
    source_lines={};full={};seen=set()
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL preparation attempted network')):
        for corpus,meta in data['corpora'].items():
            source_lines[corpus]={}
            for item in meta['source_manifest']:
                path=(sources[corpus]/item['path']).resolve()
                assert path.is_relative_to(sources[corpus].resolve()) and sha(path)==item['sha256']
                source_lines[corpus][item['path']]=path.read_bytes().decode().replace('\r\n','\n').replace('\r','\n').split('\n')
            assert sha(packs[corpus])==meta['pack_sha256']
            with open_pack(packs[corpus]) as con:full[corpus]='\n\n'.join(b.text for b in load_blocks(con))
            assert tokens(full[corpus])==meta['available_tokens']
        for row in data['rows']:
            identity=(row['corpus'],row['task'],row['method'],row['budget']);assert identity not in seen;seen.add(identity)
            pieces=[]
            for e in row['evidence']:
                match=re.fullmatch(re.escape(e['path'])+r':(\d+)-(\d+)',e['span']);assert match
                start,end=map(int,match.groups());lines=source_lines[row['corpus']][e['path']]
                assert 1<=start<=end<=len(lines);pieces.append('\n'.join(lines[start-1:end]))
            raw='\n\n'.join(pieces).encode()
            assert hashlib.sha256(raw).hexdigest()==row['context_sha256']
            assert raw==(a.local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
            assert tokens(raw.decode())==row['selected_tokens']<=row['budget']
        assert seen=={(c,t['id'],m,b) for c in sources for t in data['tasks'] for m in data['methods'] for b in data['budgets']}
        root.mkdir(parents=True);(root/'contexts').mkdir()
        settings=old_plan['settings'];methods=data['methods'];budgets=[2048,8192];observations=[];requests={}
        for i,task in enumerate(data['tasks']):
            selected=[dict(r) for r in data['rows'] if r['task']==task['id'] and r['budget'] in budgets]
            for corpus in sources:
                selected.append({'corpus':corpus,'task':task['id'],'cohort':task['cohort'],'method':'none','budget':None,
                    'selected_tokens':0,'context_sha256':hashlib.sha256(b'').hexdigest(),'selection_ms':0,'seed_failed':False,'evidence':[]})
            shift=i%len(selected)
            for row in selected[shift:]+selected[:shift]:
                context='' if row['method']=='none' else (a.local/'contexts'/(row['context_sha256']+'.txt')).read_bytes().decode()
                (root/'contexts'/(row['context_sha256']+'.txt')).write_bytes(context.encode())
                key=request_key(settings,task['question'],context);meta=data['corpora'][row['corpus']]
                row.update(request_sha256=key,corpus_tokens=meta['corpus_tokens'],available_tokens=meta['available_tokens'],
                    baseline_prompt_tokens_estimate=tokens(settings['system_prompt']+f"SOURCE\n{full[row['corpus']]}\n\nQUESTION\n{task['question']}"),
                    selected_prompt_tokens_estimate=tokens(settings['system_prompt']+f"SOURCE\n{context}\n\nQUESTION\n{task['question']}"))
                if row['seed_failed']:row['status']='SELECTION_FAILED'
                else:requests.setdefault(key,{'question':task['question'],'context_sha256':row['context_sha256']})
                observations.append(row)
        plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','dataset':{'tasks':data['tasks']},
            'settings':settings,'methods':methods,'budgets':budgets,'observations':observations,'requests':requests,
            'corpora':data['corpora'],'parent_results_sha256':sha(a.local/'results.json'),
            'selection_code_sha256':data['code_sha256'],'code_sha256':current,'nonselection_tools_changed_after_selection':sorted(changed),
            'source_archive_dependencies':{dependency.name:sha(dependency)},
            'limitations':[*data['limitations'],
                'Original answers and identical new-corpus payloads are REPLAY from the terminal parent run, including failures',
                'Only unseen request identities receive new LIVE calls; prior failed/uncertain calls are not retried',
                'No-context controls are not optimized outputs and do not count as token-saving successes',
                'One observation per unique payload; shared responses are not independent replications',
                'Manuals were chosen after inspecting failures; this is a known-task corpus ablation',
                'Selection predates accounting-reporter repairs; measured npk and retrieval helpers match their recorded source hashes',
                'No full-context or remote-preprocessor answer arm; reference full prompt counts are estimates only',
                'API load, caching and sampling are uncontrolled; dollar costs and net savings are unknown']}
        write_json(root/'plan.json',plan);(root/'plan.sha256').write_text(sha(root/'plan.json'))
        reused=import_replays(a.parent_live,root,plan)
        bodies={name:{'sha256':value,'text':(repo/name).read_bytes().decode()} for name,value in current.items()}
        (root/'preparation-sources.json.gz').write_bytes(gzip.compress(json.dumps(bodies).encode(),mtime=0))
        result={'evidence_mode':'LOCAL','generative_calls':0,'plan_sha256':sha(root/'plan.json'),
            'source_reconstructed_observations':len(seen),'planned_observations':len(observations),
            'unique_requests':len(requests),'preparation_sources_sha256':sha(root/'preparation-sources.json.gz'),**reused}
        write_json(root/'preflight.json',result);print(result)


if __name__=='__main__':main()

"""Recount and reconstruct every local-budget observation before reporting it."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def audit(run, snapshot, asset, output):
    plan=read(run/'plan.json');data=read(run/'results.json')
    assert data['plan_sha256']==sha((run/'plan.json').read_bytes())
    assert plan['snapshot_sha256']==sha((snapshot/'snapshot.json').read_bytes())
    assert plan['asset_sha256']==sha(asset.read_bytes())
    assert plan['pack_sha256']==sha((run/'compiled.npk').read_bytes())
    captured=(run/'execution-sources.json.gz').read_bytes()
    assert sha(captured)==plan['execution_sources_sha256']
    assert 'npk/pack/tokenizer.py' in json.loads(gzip.decompress(captured))
    for name, info in read(snapshot/'snapshot.json')['files'].items():
        assert sha((snapshot/name).read_bytes())==info['sha256']
    from tokenizers import Tokenizer
    codec=Tokenizer.from_file(str(asset));codec.no_truncation();codec.no_padding()
    tasks={t['task_id']:t for t in plan['tasks']}
    source={p.relative_to(snapshot/'corpus/test_src').as_posix():p.read_bytes().decode().replace('\r\n','\n').replace('\r','\n').split('\n')
            for p in (snapshot/'corpus/test_src').rglob('*.py')}
    assert len(codec.encode('\n\n'.join('\n'.join(lines) for _,lines in sorted(source.items())),add_special_tokens=False).ids)==plan['corpus_tokens']
    rows={};items_checked=0
    for row in data['rows']:
        key=(row['query'],row['budget'],row['arm']);assert key not in rows
        body=(run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert sha(body)==row['context_sha256'];text=body.decode()
        assert '\n\n'.join(e['text'] for e in row['items'])==text
        count=len(codec.encode(text,add_special_tokens=False).ids)
        assert count==row['actual_tokens']
        if row['arm']!='estimated':assert count==row['reported_tokens']<=row['budget']
        assert row['fallback']==(not row['items'])
        for item in row['items']:
            path,extent=item['span'].rsplit(':',1);lo,hi=map(int,extent.split('-'))
            assert path==item['path'] and 1<=lo<=hi<=len(source[path])
            assert item['text']=='\n'.join(source[path][lo-1:hi]);items_checked+=1
        expected={t['task_id'] for t in plan['tasks'] if t['query']==row['query']}
        assert set(row['hits'])==expected
        for tid,hit in row['hits'].items():
            task=tasks[tid];_,span=task['span'].rsplit(':',1);start,end=map(int,span.split('-'))
            relevant=[]
            for item in row['items']:
                _,extent=item['span'].rsplit(':',1);lo,hi=map(int,extent.split('-'))
                if item['path']==task['path'] and lo<=end and hi>=start:relevant.append(item['text'])
            flat=' '.join('\n\n'.join(relevant).split())
            assert hit==(bool(task['needles']) and all(n in flat for n in task['needles']))
        rows[key]=row
    queries={t['query'] for t in tasks.values()}
    assert set(rows)=={(q,b,a) for q in queries for b in plan['budgets'] for a in plan['arms']}
    assert all(rows[q,b,'cached']['context_sha256']==rows[q,b,'exact']['context_sha256']
               for q in queries for b in plan['budgets'])
    summaries=[]
    for saved in data['summary']:
        arm,budget=saved['arm'],saved['budget'];group=[r for (q,b,a),r in rows.items() if (a,b)==(arm,budget)]
        hits=sum(sum(r['hits'].values()) for r in group)
        assert hits==saved['attributed_needle_hits']
        assert saved['query_budget_overruns']==sum(r['actual_tokens']>budget for r in group)
        changed=sum(r['context_sha256']!=rows[r['query'],budget,'exact']['context_sha256'] for r in group)
        assert saved['contexts_changed_from_exact']==changed
        wins=[];losses=[]
        for r in group:
            baseline=rows[r['query'],budget,'exact']
            for tid,hit in r['hits'].items():
                if hit and not baseline['hits'][tid]:wins.append(tid)
                if not hit and baseline['hits'][tid]:losses.append(tid)
        summaries.append({**saved,'wins_against_exact':wins,'losses_against_exact':losses})
    profiles=data['profile']
    seen=set()
    for row in profiles:
        key=tuple(row[k] for k in ('query','budget','arm','trial','state'))
        assert key not in seen;seen.add(key)
        assert 0<=row['cache_retained_bytes']<=4*1024*1024 and 0<=row['cache_entries']<=4096
        assert row['wall_ms']>=0 and row['cpu_ms']>=0
    chosen=sorted(queries,key=lambda q:sha(q.encode()))[:12]
    assert seen=={(q,b,a,t,s) for q in chosen for b in plan['budgets'] for a in plan['arms']
                  for t in range(3) for s in ('cold_count_cache','immediate_repeat')}
    for summary in summaries:
        for state in ('cold_count_cache','immediate_repeat'):
            values=[r['wall_ms'] for r in profiles if (r['arm'],r['budget'],r['state'])==
                    (summary['arm'],summary['budget'],state)]
            assert summary[state+'_median_ms']==statistics.median(values)
    report={'status':'AUDITED','evidence_mode':'LOCAL','generative_calls':0,'new_api_calls':0,
            'plan_sha256':data['plan_sha256'],'selections':len(rows),'source_items_checked':items_checked,
            'profile_observations':len(profiles),'corpus_tokens':plan['corpus_tokens'],
            'tokenizer_sha256':plan['asset_sha256'],'summaries':summaries,'limitations':plan['limits']}
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({k:report[k] for k in ('status','selections','source_items_checked','profile_observations')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','snapshot','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();audit(a.run,a.snapshot,a.asset,a.output)

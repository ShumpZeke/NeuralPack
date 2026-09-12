"""Independent byte/span/count audit of the seed ablation; no answer scoring.

This deliberately does not import the experiment's retention/attribution helpers
or the product tokenizer. Candidate rank reproduction is a separate check.
"""
import argparse
from collections import defaultdict
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def attributed_hit(items, task):
    start,end=map(int,task['span'].rsplit(':',1)[1].split('-'))
    relevant=[]
    for item in items:
        path,span=item['span'].rsplit(':',1)
        lo,hi=map(int,span.split('-'))
        assert path==item['path']
        if path==task['path'] and lo<=end and hi>=start:relevant.append(item['text'])
    joined=' '.join('\n\n'.join(relevant).split())
    return bool(task['needles']) and all(needle in joined for needle in task['needles'])


def check_source_coverage(blocks,source):
    """Check available nonblank source lines, independently of selected hits."""
    coverage={path:[0]*len(text.split('\n')) for path,text in source.items()}
    for block in blocks.values():
        path,extent=block['span'].rsplit(':',1);lo,hi=map(int,extent.split('-'))
        assert path==block['path'] and path in coverage
        assert 1<=lo<=hi<=len(coverage[path])
        for i in range(lo-1,hi):coverage[path][i]+=1
    nonblank=overlap=0
    for path,text in source.items():
        for line,count in zip(text.split('\n'),coverage[path]):
            if not line.strip():continue
            nonblank+=1;overlap+=count>1
            assert count>0, 'Nonblank source line absent from compiled blocks'
    return {'nonblank_lines':nonblank,'uncovered_nonblank_lines':0,'multiply_covered_nonblank_lines':overlap,
            'limit':'Does not assert retention of every blank line or byte-for-byte source-file reconstruction'}


def check_row(row, body, blocks, tasks, count):
    assert sha(body)==row['context_sha256'], 'context digest'
    text=body.decode('utf-8')
    assert text=='\n\n'.join(e['text'] for e in row['items']), 'assembly'
    assert count(text)==row['selected_tokens']<=row['budget'], 'token budget'
    assert row['fallback']==(not row['items']), 'fallback status'
    assert row['risk_band'].startswith('uncalibrated:'), 'risk calibration'
    calls=row['seed_calls'];limit=60 if row['arm']=='body60' else 160
    assert calls and calls[0]['limit']==limit
    assert len(calls) in (1,2)
    if len(calls)==2:assert calls[1]['limit']==limit*4
    pool_ids=[]
    for call in calls:
        ids=call['ids']
        assert len(ids)==len(set(ids))<=call['limit']
        assert all(bid in blocks for bid in ids)
        pool_ids.extend(bid for bid in ids if bid not in pool_ids)
    seen=set()
    for item in row['items']:
        bid=item['block_id'];assert bid not in seen and bid in calls[-1]['ids']
        seen.add(bid)
        original=blocks[bid]
        for key in ('path','span','text','name','kind'):
            assert item[key]==original[key], 'source '+key
        assert item['channels']==['lexical']
        assert item['tokens']==count(item['text']), 'standalone count'
    expected={t['task_id']:t for t in tasks if t['query']==row['query']}
    assert expected and set(row['hits'])==set(row['candidate_pool_hits'])==set(expected)
    pool=[blocks[bid] for bid in pool_ids]
    for tid,task in expected.items():
        assert type(row['hits'][tid]) is bool and type(row['candidate_pool_hits'][tid]) is bool
        assert row['hits'][tid]==attributed_hit(row['items'],task), 'selected hit'
        assert row['candidate_pool_hits'][tid]==attributed_hit(pool,task), 'candidate hit'
    return len(row['items'])


def grouped_difference(rows, queries, budget, arm, baseline, seed=2902):
    # Repeated query strings are one cluster, including ambiguous C questions.
    diffs=[statistics.mean(rows[q,budget,arm]['hits'].values())-
           statistics.mean(rows[q,budget,baseline]['hits'].values()) for q in queries]
    rng=random.Random(seed)
    samples=sorted(statistics.mean(rng.choices(diffs,k=len(diffs))) for _ in range(2000))
    return {'query_mean_difference':statistics.mean(diffs),'bootstrap_95_interval':[samples[50],samples[1949]],
            'resamples':2000,'seed':seed,'unit':'distinct question string',
            'interpretation':'Exploratory paired interval on inspected data; multiple arm comparisons are not corrected'}


def audit(run,snapshot,pack,asset,output):
    if output.exists():raise ValueError('Fresh audit output required')
    plan=read(run/'plan.json');state=read(run/'state.json')
    assert state['status']=='COMPLETE'
    assert sha((snapshot/'snapshot.json').read_bytes())==plan['snapshot_sha256']
    assert sha(pack.read_bytes())==plan['pack_sha256']
    assert sha(asset.read_bytes())==plan['asset_sha256']
    assert sha((run/'features.sqlite').read_bytes())==plan['side_sha256']
    capture=(run/'sources.json.gz').read_bytes()
    assert sha(capture)==plan['sources_sha256']
    sources=json.loads(gzip.decompress(capture))
    assert set(sources)==set(plan['code_sha256'])
    assert all(sha(code.encode())==plan['code_sha256'][name] for name,code in sources.items())
    frozen=read(snapshot/'snapshot.json')
    for name,info in frozen['files'].items():assert sha((snapshot/name).read_bytes())==info['sha256']
    assert plan['tasks']==read(snapshot/'work/tasks_heldout.json')
    source_root=snapshot/'corpus/test_src'
    source={p.relative_to(source_root).as_posix():p.read_bytes().decode().replace('\r\n','\n').replace('\r','\n')
            for p in source_root.rglob('*.py')}
    from tokenizers import Tokenizer
    codec=Tokenizer.from_file(str(asset));codec.no_truncation();codec.no_padding()
    @lru_cache(maxsize=512)
    def count(text):return len(codec.encode(text,add_special_tokens=False).ids)
    corpus=count('\n\n'.join(source[path] for path in sorted(source)))
    con=sqlite3.connect(pack.resolve().as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    try:
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        blocks={}
        for row in con.execute('SELECT b.*,f.path FROM blocks b JOIN files f ON f.id=b.file_id'):
            item=dict(row);path=item['path'];lo=item['start_line'];hi=item['end_line']
            lines=source[path].split('\n');assert 1<=lo<=hi<=len(lines)
            assert item['text']=='\n'.join(lines[lo-1:hi])
            assert sha(item['text'].encode())==item['sha256']
            item['span']=f'{path}:{lo}-{hi}';blocks[item['id']]=item
    finally:con.close()
    source_coverage=check_source_coverage(blocks,source)
    tasks=plan['tasks'];rows={};checked=0
    for i,file in enumerate(sorted((run/'records').glob('*.json')),1):
        row=read(file);key=(row['query'],row['budget'],row['arm']);assert key not in rows
        assert file.stem==sha(json.dumps(list(key),ensure_ascii=False).encode())
        body=(run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        checked+=check_row(row,body,blocks,tasks,count);rows[key]=row
        if i%500==0:print({'phase':'audit','checked':i},flush=True)
    queries=sorted({t['query'] for t in tasks})
    assert set(rows)=={(q,b,a) for q in queries for b in plan['budgets'] for a in plan['arms']}
    assert len(rows)==state['completed']==state['planned']
    summaries=[]
    for budget in plan['budgets']:
        for arm in plan['arms']:
            group=[rows[q,budget,arm] for q in queries]
            base=[rows[q,budget,'body160'] for q in queries]
            family={}
            for label in sorted({t['family'] for t in tasks}):
                ids={t['task_id'] for t in tasks if t['family']==label}
                family[label]={'tasks':len(ids),'hits':sum(v for row in group for tid,v in row['hits'].items() if tid in ids)}
            wins=[];losses=[]
            for row,b in zip(group,base):
                for tid,hit in row['hits'].items():
                    if hit and not b['hits'][tid]:wins.append(tid)
                    if not hit and b['hits'][tid]:losses.append(tid)
            summaries.append({'arm':arm,'budget':budget,'task_hits':sum(sum(r['hits'].values()) for r in group),
                'task_count':len(tasks),'candidate_pool_hits':sum(sum(r['candidate_pool_hits'].values()) for r in group),
                'query_mean_retention':statistics.mean(statistics.mean(r['hits'].values()) for r in group),
                'median_selected_tokens':statistics.median(r['selected_tokens'] for r in group),
                'fallback_queries':sum(r['fallback'] for r in group),'overruns':0,'family':family,
                'wins_vs_body160':wins,'losses_vs_body160':losses,
                'context_changes_vs_body160':sum(r['context_sha256']!=b['context_sha256'] for r,b in zip(group,base)),
                'difference_vs_body160':grouped_difference(rows,queries,budget,arm,'body160')})
    report={'status':'AUDITED','evidence_mode':'LOCAL','generative_calls':0,'new_api_calls':0,
        'math_status':'EMPIRICAL','plan_sha256':sha((run/'plan.json').read_bytes()),
        'auditor_sha256':sha(Path(__file__).read_bytes()),'selections':len(rows),'source_items_checked':checked,
        'blocks_checked':len(blocks),'source_coverage':source_coverage,
        'distinct_queries':len(queries),'corpus_tokens_per_request':corpus,
        'tokenizer_sha256':plan['asset_sha256'],'summary':summaries,
        'per_task_context':[{ 'task_id':t['task_id'],'corpus_tokens':corpus,'available_tokens':corpus,
          'baseline_prompt_tokens':None,'baseline_prompt_reason':'Source-selection study; no target prompt constructed',
          'selections':[{'arm':a,'budget':b,'selected_tokens':rows[t['query'],b,a]['selected_tokens'],
                        'context_sha256':rows[t['query'],b,a]['context_sha256']} for b in plan['budgets'] for a in plan['arms']]}
          for t in tasks],
        'limits':plan['limitations']+['Needle retention and pool coverage do not measure answer correctness',
            'Candidate ranking reproducibility is checked separately; this report audits recorded output and source attribution',
            'Uncalibrated risk labels are not treated as confidence or quality measurements']}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:report[k] for k in ('status','selections','source_items_checked','blocks_checked')},flush=True)
    print([ {k:s[k] for k in ('budget','arm','task_hits','candidate_pool_hits')} for s in summaries],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','snapshot','pack','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();audit(a.run,a.snapshot,a.pack,a.asset,a.output)

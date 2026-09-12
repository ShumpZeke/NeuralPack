"""Matched-NIM-budget seed ablation with identical blocks and product packing.

Every arm calls PackSelector; only its lexical seed channel is substituted in
this single-threaded experiment. No benchmark labels enter ranking. Results are
checkpointed one selection at a time; this is not a clean latency benchmark.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import sys
import time
from unittest.mock import patch

from benchmarks import seed_metadata as features
from benchmarks.rival_reproduction import attributed_context,retention
from npk.pack import LocalTokenizer,PackSelector
from npk.pack.format import load_blocks,open_pack
from npk.pack.select import _lexical_channel


ARMS=('body60','body160','literal','retained','subwords','fields','names4','crisp_shared','crisp_shared_raises')
BUDGETS=(512,2048,8192)


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,data):
    pending=path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');pending.replace(path)


def code_digest():
    repo=Path(__file__).resolve().parents[1]
    files=list((repo/'npk').rglob('*.py'))+[Path(__file__),Path(features.__file__)]
    return {p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in files}


def run(snapshot,pack,asset,output,*,resume=False,max_jobs=None):
    if output.exists() and not resume:raise ValueError('Fresh experiment directory required')
    frozen=read(snapshot/'snapshot.json')
    for name,meta in frozen['files'].items():assert sha((snapshot/name).read_bytes())==meta['sha256']
    sys.path.insert(0,str(snapshot.resolve()))
    from crisp.index import analyze_terms
    from crisp.score import Scorer
    import tiktoken
    cl1=tiktoken.get_encoding('cl100k_base')
    tasks=read(snapshot/'work/tasks_heldout.json');groups=defaultdict(list)
    for task in tasks:groups[task['query']].append(task)
    # A fixed larger count cache amortizes repetitions across arms/budgets.
    # It changes no counts; timings include checkpoint I/O and are diagnostic.
    counter=LocalTokenizer(asset,cache_bytes=16*1024*1024)
    output.mkdir(parents=True,exist_ok=resume)
    records=output/'records';records.mkdir(exist_ok=resume)
    contexts=output/'contexts';contexts.mkdir(exist_ok=resume)
    side_path=output/'features.sqlite'
    plan={'evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'arms':ARMS,'budgets':BUDGETS,
          'snapshot_sha256':sha((snapshot/'snapshot.json').read_bytes()),'pack_sha256':sha(pack.read_bytes()),
          'asset_sha256':sha(asset.read_bytes()),'code_sha256':code_digest(),'shuffle_seed':2901,
          'limitations':['Inspected development tasks, not a new sealed answer evaluation',
                        'Identical NPK blocks and product packing; frozen CRISP scorer adapted to these blocks',
                        'Shared CRISP baseline retains its original cl100k-based IR length normalization',
                        'All context caps use the pinned NVIDIA tokenizer; query and caller wrappers excluded',
                        'No arbitrary support threshold or probability is promoted from the rival',
                        '16 MiB exact-count cache across arms; checkpointed timing is diagnostic, not a latency claim',
                        'Side index requires rebuilding after parent changes; no incremental speed claim']}
    if resume:
        prior=read(output/'plan.json')
        for key in ('tasks','arms','budgets','snapshot_sha256','pack_sha256','asset_sha256','code_sha256'):
            assert prior[key]==json.loads(json.dumps(plan[key])),key
        plan=prior
        assert sha(side_path.read_bytes())==plan['side_sha256']
    else:
        started=time.perf_counter_ns()
        built=features.build(pack,side_path,snapshot/'corpus/test_src',rival_analyze=analyze_terms,
                             count_cl100k=lambda text:len(cl1.encode_ordinary(text)))
        plan['side_build']={**built,'wall_ms':(time.perf_counter_ns()-started)/1e6}
        plan['side_sha256']=sha(side_path.read_bytes());plan['python']=sys.version
        repo=Path(__file__).resolve().parents[1]
        capture=gzip.compress(json.dumps({name:(repo/name).read_bytes().decode() for name in plan['code_sha256']}).encode(),mtime=0)
        (output/'sources.json.gz').write_bytes(capture);plan['sources_sha256']=sha(capture)
        save(output/'plan.json',plan)
    side=sqlite3.connect(side_path.resolve().as_uri()+'?mode=ro',uri=True);side.row_factory=sqlite3.Row
    side.execute('BEGIN');scorer=Scorer(side)
    with open_pack(pack) as parent:
        features.require_parent(side,parent)
        all_blocks={b.id:b for b in load_blocks(parent,[r[0] for r in parent.execute('SELECT id FROM blocks')])}
    def ranked(arm,parent,query,limit):
        features.require_parent(side,parent)
        if arm.startswith('body'):return _lexical_channel(parent,query,limit)
        if arm in ('literal','retained'):return features.original_index_rank(parent,query,limit,policy=arm)
        if arm in ('subwords','fields','names4'):return features.field_rank(side,query,limit,mode=arm)
        qp=scorer.plan(query)
        if arm=='crisp_shared':qp.relations=[]
        return [bid for bid,score in scorer.candidates(qp,limit)]
    selectors={arm:PackSelector(pack,tokenizer=counter,candidate_limit=60 if arm=='body60' else 160) for arm in ARMS}
    completed=set()
    for file in records.glob('*.json'):
        row=read(file);key=(row['query'],row['budget'],row['arm']);assert key not in completed
        body=(contexts/(row['context_sha256']+'.txt')).read_bytes();assert sha(body)==row['context_sha256']
        assert counter.count(body.decode())==row['selected_tokens']<=row['budget']
        completed.add(key)
    # Group work by query to reuse exact byte counts; randomized arm order and
    # fixed query shuffle do not consult answer labels.
    queries=sorted(groups);rng=random.Random(2901);rng.shuffle(queries)
    jobs=[]
    for query in queries:
        cells=[(budget,arm) for budget in BUDGETS for arm in ARMS];rng.shuffle(cells)
        jobs.extend((query,budget,arm) for budget,arm in cells)
    pending=[job for job in jobs if job not in completed]
    if max_jobs is not None:pending=pending[:max_jobs]
    print({'phase':'ready','completed':len(completed),'pending_batch':len(pending),'planned':len(jobs)},flush=True)
    try:
        for i,(query,budget,arm) in enumerate(pending,1):
            seed_calls=[]
            def seed(parent,q,limit):
                assert q==query
                ids=ranked(arm,parent,q,limit);seed_calls.append({'limit':limit,'ids':ids});return ids
            start=time.perf_counter_ns()
            with patch('npk.pack.select._lexical_channel',seed):
                selected=selectors[arm].select(query,budget_tokens=budget)
            elapsed=(time.perf_counter_ns()-start)/1e6
            text=selected.context_text();digest=sha(text.encode());count=counter.count(text)
            assert selected.query==query and count==selected.total_tokens<=budget and not selected.used_generative_llm
            (contexts/(digest+'.txt')).write_bytes(text.encode())
            items=[asdict(e) for e in selected.evidence]
            seeds=list(dict.fromkeys(bid for call in seed_calls for bid in call['ids']))
            pool=[{'path':all_blocks[bid].path,'span':all_blocks[bid].span,'text':all_blocks[bid].text} for bid in seeds]
            row={'query':query,'budget':budget,'arm':arm,'context_sha256':digest,'selected_tokens':count,
                 'diagnostic_wall_ms':elapsed,'fallback':selected.seed_failed,'risk_band':selected.risk_band,
                 'items':items,'seed_calls':seed_calls,
                 'hits':{t['task_id']:retention(attributed_context(items,t),t['needles'])['strict_hit'] for t in groups[query]},
                 'candidate_pool_hits':{t['task_id']:retention(attributed_context(pool,t),t['needles'])['strict_hit'] for t in groups[query]}}
            save(records/(sha(json.dumps([query,budget,arm],ensure_ascii=False).encode())+'.json'),row)
            completed.add((query,budget,arm))
            if i%100==0:print({'phase':'select','completed':len(completed),'planned':len(jobs)},flush=True)
    finally:side.close()
    assert code_digest()==plan['code_sha256']
    save(output/'state.json',{'status':'COMPLETE' if len(completed)==len(jobs) else 'CHECKPOINT',
                             'completed':len(completed),'planned':len(jobs)})
    print(read(output/'state.json'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','pack','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--max-jobs',type=int)
    a=p.parse_args();run(a.snapshot,a.pack,a.asset,a.output,resume=a.resume,max_jobs=a.max_jobs)

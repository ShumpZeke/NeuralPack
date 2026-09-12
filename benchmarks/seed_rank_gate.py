"""Reproduce every distinct recorded seed ranking from the captured code."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def selector_module_path():
    # npk.pack exports a function named select, shadowing the submodule as an
    # attribute. Importlib resolves the actual module and its source location.
    return Path(importlib.import_module('npk.pack.select').__file__).resolve()


def verify(run,snapshot,pack,output):
    if output.exists():raise ValueError('Fresh rank-gate output required')
    assert read(run/'state.json')['status']=='COMPLETE'
    plan=read(run/'plan.json');copied=read(run/'execution-copy.json');root=run/'execution-root'
    assert copied['plan_sha256']==sha((run/'plan.json').read_bytes())
    assert sha(pack.read_bytes())==plan['pack_sha256']
    assert sha((run/'features.sqlite').read_bytes())==plan['side_sha256']
    assert sha((snapshot/'snapshot.json').read_bytes())==plan['snapshot_sha256']
    for name,digest in copied['all_files'].items():assert sha((root/name).read_bytes())==digest
    for name,info in read(snapshot/'snapshot.json')['files'].items():assert sha((snapshot/name).read_bytes())==info['sha256']
    assert 'npk' not in sys.modules and 'benchmarks.seed_metadata' not in sys.modules
    sys.path[:0]=[str(root.resolve()),str(snapshot.resolve())]
    from npk.pack.format import open_pack
    from npk.pack.select import _lexical_channel,RRF_K
    from benchmarks import seed_metadata as features
    from crisp.score import Scorer
    assert Path(features.__file__).resolve().is_relative_to(root.resolve())
    assert selector_module_path().is_relative_to(root.resolve())
    expected={};selections=0
    for path in (run/'records').glob('*.json'):
        row=read(path);selections+=1
        last_ranks={bid:i for i,bid in enumerate(row['seed_calls'][-1]['ids'])}
        for item in row['items']:
            assert item['score']==1.0/(RRF_K+last_ranks[item['block_id']]), 'Reported RRF score mismatch'
        for call in row['seed_calls']:
            key=(row['query'],row['arm'],call['limit'])
            if key in expected:assert expected[key]==call['ids'], 'Repeated rank changed'
            else:expected[key]=call['ids']
    side=sqlite3.connect((run/'features.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        scorer=Scorer(side)
        with open_pack(pack) as parent:
            features.require_parent(side,parent)
            for i,((query,arm,limit),ids) in enumerate(sorted(expected.items()),1):
                if arm.startswith('body'):actual=_lexical_channel(parent,query,limit)
                elif arm in ('literal','retained'):
                    actual=features.original_index_rank(parent,query,limit,policy=arm)
                elif arm in ('subwords','fields','names4'):
                    actual=features.field_rank(side,query,limit,mode=arm)
                else:
                    assert arm in ('crisp_shared','crisp_shared_raises')
                    query_plan=scorer.plan(query)
                    if arm=='crisp_shared':query_plan.relations=[]
                    actual=[bid for bid,score in scorer.candidates(query_plan,limit)]
                assert actual==ids, ('Seed ranking mismatch',arm,limit,sha(query.encode()))
                if i%250==0:print({'phase':'rank_replay','checked':i,'planned':len(expected)},flush=True)
    finally:side.close()
    report={'status':'PASSED','evidence_mode':'LOCAL','new_api_calls':0,
            'plan_sha256':sha((run/'plan.json').read_bytes()),'selections':selections,
            'distinct_seed_calls':len(expected),'gate_sha256':sha(Path(__file__).read_bytes()),
            'sqlite_version':sqlite3.sqlite_version,'python':sys.version,
            'limitation':'Frozen implementation replay checks reproducibility, not independent relevance or correctness'}
    output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','snapshot','pack','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();verify(a.run,a.snapshot,a.pack,a.output)

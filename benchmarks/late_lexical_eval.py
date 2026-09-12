"""Paired candidate-list equality and ranking latency, including tie floods."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import statistics
import time
from benchmarks.late_lexical import rank
from npk.pack import compile_pack
from npk.pack.format import open_pack


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.run.exists() or a.output.exists():raise ValueError('new ranking experiment required')
    a.run.mkdir(parents=True);data=json.loads((a.parent/'results.json').read_text())
    queries=[t['question'] for t in data['tasks']]
    native=importlib.import_module('npk.pack.select')._lexical_channel
    repo=Path(__file__).resolve().parents[1]
    hashes={p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),repo/'benchmarks/late_lexical.py',repo/'npk/pack/select.py']}
    rows=[];rng=random.Random(1551)
    def measure(pack,name,questions):
        with open_pack(pack) as con:
            for trial in range(5):
                jobs=[(i,q,limit) for i,q in enumerate(questions) for limit in (60,240)];rng.shuffle(jobs)
                for i,q,limit in jobs:
                    methods=[('native',native),('late',rank)];rng.shuffle(methods);results={}
                    for method,call in methods:
                        start=time.perf_counter();result=call(con,q,limit);ms=1000*(time.perf_counter()-start)
                        results[method]=result;rows.append({'corpus':name,'task_index':i,'limit':limit,'trial':trial,'method':method,'wall_ms':ms,'candidates':len(result)})
                    assert results['native']==results['late']
        print({'corpus':name,'measurements':len(rows)},flush=True)
    measure(a.corpus/'expanded.npk','expanded',queries)
    # Synthetic equal-score stress is cost/equality evidence, not real-corpus size.
    for count in (100,2000):
        source=a.run/f'ties-{count}';source.mkdir()
        for i in range(count):(source/f'item{i:05}.py').write_text('SHARED_CONSTANT = 7\n')
        pack=a.run/f'ties-{count}.npk';compile_pack(source,pack)
        measure(pack,f'synthetic_ties_{count}',['SHARED_CONSTANT'])
    summary=[]
    for corpus in sorted({r['corpus'] for r in rows}):
        for limit in (60,240):
            times={method:statistics.median(r['wall_ms'] for r in rows if r['corpus']==corpus and r['limit']==limit and r['method']==method) for method in ('native','late')}
            summary.append({'corpus':corpus,'limit':limit,**times,'native_over_late':times['native']/times['late']})
    assert all(hashlib.sha256((repo/path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
    result={'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'summary':summary,'code_sha256':hashes,
            'equality_checks':len(rows)//2,'parent_results_sha256':hashlib.sha256((a.parent/'results.json').read_bytes()).hexdigest(),
            'limitations':['Five shuffled paired repetitions with warm connections; ranking only, no assembly or answer accuracy',
                           'Tie-flood corpora are synthetic stress tests, not public large-context claims','LIVE answer IO overlaps; machine activity and CPU scheduling uncontrolled',
                           'Prototype consumes the entire score boundary tie group; no constant worst-case work claim']}
    a.output.write_text(json.dumps(result,indent=2));print(summary)


if __name__=='__main__':main()

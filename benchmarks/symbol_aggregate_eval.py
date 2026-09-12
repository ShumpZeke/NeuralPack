"""Measure SQL-equivalent symbol aggregation before considering any promotion."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from benchmarks.prospective_eval import write_json
from benchmarks.symbol_aggregate import rank
from npk.pack.format import open_pack
from npk.pack.select import _symbol_channel


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('New measured result required')
    data=json.loads((a.local/'results.json').read_text());rows=[];rng=random.Random(2852)
    for trial in range(3):
        cells=[(c,t,m) for c in ('manuals','expanded') for t in data['tasks'] for m in ('original','aggregate_first')];rng.shuffle(cells)
        for corpus,task,method in cells:
            with open_pack(a.local/(corpus+'_deterministic.npk')) as con:
                call=_symbol_channel if method=='original' else rank;start=time.perf_counter_ns()
                ids=call(con,task['question'],60);elapsed=(time.perf_counter_ns()-start)/1e6
                rows.append({'corpus':corpus,'task':task['id'],'method':method,'trial':trial,'wall_ms':elapsed,'ids':ids})
        write_json(a.output.with_suffix('.partial.json'),{'rows':rows});print({'trial':trial,'observations':len(rows)},flush=True)
    summary=[];checked=0
    for corpus in ('manuals','expanded'):
        for task in data['tasks']:
            group=[r for r in rows if (r['corpus'],r['task'])==(corpus,task['id'])]
            assert len(group)==6 and all(r['ids']==group[0]['ids'] for r in group);checked+=1
        for method in ('original','aggregate_first'):
            medians=[statistics.median(r['wall_ms'] for r in rows if (r['corpus'],r['task'],r['method'])==(corpus,t['id'],method)) for t in data['tasks']]
            summary.append({'corpus':corpus,'method':method,'tasks':len(medians),'median_ms':statistics.median(medians)})
    result={'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'summary':summary,'identical_rankings':checked,
            'source_sha256':hashlib.sha256(Path(__file__).with_name('symbol_aggregate.py').read_bytes()).hexdigest(),
            'limitations':['Symbol-channel cost only; not complete selection latency','Same output ranks must be preserved; no answer-quality gain implied',
                           'Three shuffled repetitions with uncontrolled host load; no overlapping agent benchmarks, tests or LIVE requests']}
    write_json(a.output,result);print({'equivalent':checked,'summary':summary},flush=True)


if __name__=='__main__':main()

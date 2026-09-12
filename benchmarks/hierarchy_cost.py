"""Repeat standalone LOCAL ranking costs with CPU and wall time separately."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import time
from benchmarks.hierarchical_seeds import rank
from npk.pack.format import open_pack


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('new cost report required')
    d=json.loads((a.run/'results.json').read_text());native=importlib.import_module('npk.pack.select')._lexical_channel
    con=sqlite3.connect((a.run/'expanded-hierarchy.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    recorded={(r['task'],r['method']):r['candidate_ids'] for r in d['rankings'] if r['corpus']=='expanded'}
    rows=[];rng=random.Random(1509)
    try:
        with open_pack(a.corpus/'expanded.npk') as pack:
            # Warm connections explicitly. These are warm standalone ranking costs.
            native(pack,d['tasks'][0]['question'],240);rank(con,d['tasks'][0]['question'],'flat_fields')
            for trial in range(3):
                jobs=[(t,m) for t in d['tasks'] for m in d['methods']];rng.shuffle(jobs)
                for task,method in jobs:
                    start=time.perf_counter_ns();cpu=time.process_time_ns()
                    ids=native(pack,task['question'],240) if method=='bm25' else rank(con,task['question'],method,240)[0]
                    cpu_ms=(time.process_time_ns()-cpu)/1e6;wall_ms=(time.perf_counter_ns()-start)/1e6
                    assert ids==recorded[(task['id'],method)]
                    rows.append({'trial':trial,'task':task['id'],'method':method,'cpu_ms':cpu_ms,'wall_ms':wall_ms})
                print({'trial':trial,'ranking_equality_checks':len(rows)},flush=True)
    finally:con.close()
    summary={m:{k:statistics.median(r[k] for r in rows if r['method']==m) for k in ('cpu_ms','wall_ms')} for m in d['methods']}
    result={'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'median_ms':summary,
            'parent_results_sha256':hashlib.sha256((a.run/'results.json').read_bytes()).hexdigest(),
            'reporter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limitations':['Three shuffled repetitions with warm persistent connections; excludes assembly, source compilation and index build',
                           'CPU process timer granularity may round short operations to zero; wall time is measured separately',
                           'LIVE answer IO ran concurrently; host activity and CPU scheduling are uncontrolled',
                           'This experiment verifies ranking equality to the frozen run, not additional answer quality or universal speed guarantees']}
    a.output.write_text(json.dumps(result,indent=2));print(summary)


if __name__=='__main__':main()

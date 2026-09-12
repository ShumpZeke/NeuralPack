"""Paired repeated ranking costs for the frozen clause run; no model calls."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import time
from unittest.mock import patch
from benchmarks.clause_seeds import rank
from npk.pack.format import open_pack


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('new profile required')
    data=json.loads((a.run/'results.json').read_text());native=importlib.import_module('npk.pack.select')._lexical_channel
    recorded={(r['task'],r['method']):r['ids'] for r in data['rankings']}
    con=sqlite3.connect((a.run/'clauses.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    rows=[];rng=random.Random(1818)
    try:
        with open_pack(a.corpus/'expanded.npk') as pack,patch('socket.socket.connect',side_effect=AssertionError('profile attempted network')):
            native(pack,data['tasks'][0]['question'],240);rank(con,data['tasks'][0]['question'],'flat_fields')
            for trial in range(5):
                jobs=[(task,method) for task in data['tasks'] for method in data['methods']];rng.shuffle(jobs)
                for task,method in jobs:
                    start=time.perf_counter_ns();cpu=time.process_time_ns()
                    ids=native(pack,task['question'],240) if method=='bm25' else rank(con,task['question'],method,240)[0]
                    cpu_ms=(time.process_time_ns()-cpu)/1e6;wall_ms=(time.perf_counter_ns()-start)/1e6
                    assert ids==recorded[(task['id'],method)]
                    rows.append({'trial':trial,'task':task['id'],'method':method,'cpu_ms':cpu_ms,'wall_ms':wall_ms})
                print({'trial':trial,'equality_checks':len(rows)},flush=True)
    finally:con.close()
    summary={method:{key:statistics.median(r[key] for r in rows if r['method']==method) for key in ('wall_ms','cpu_ms')} for method in data['methods']}
    report={'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'median_ms':summary,
            'parent_results_sha256':hashlib.sha256((a.run/'results.json').read_bytes()).hexdigest(),
            'reporter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'limitations':['Five shuffled repetitions with warm persistent connections; excludes assembly, compilation and index build',
                           'CPU timer granularity can round short calls to zero; wall time recorded independently',
                           'LIVE answer IO ran concurrently; no CPU tests/mutations; host activity and OS caches uncontrolled',
                           'No additional quality inference from repeated deterministic rankings']}
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(summary)


if __name__=='__main__':main()

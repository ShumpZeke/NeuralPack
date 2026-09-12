"""Paired full-source scans with reference and optimized credential screening."""
import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    reference=repo/'experiments/runs/packs/cycle12-boundary-profile/candidate/npk/pack/source_policy.py'
    spec=importlib.util.spec_from_file_location('npk.pack.source_policy_reference',reference)
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    compiler=importlib.import_module('npk.pack.compile');current=compiler.check_source
    source=repo/'experiments/runs/repository-click-v1/source/click-8.5.0'
    expected=compiler.scan_source(source);rows=[];rng=random.Random(120612)
    for trial in range(20):
        arms=[('reference',baseline.check_source),('candidate',current)];rng.shuffle(arms)
        for arm,screen in arms:
            with patch.object(compiler,'check_source',screen):
                start=time.perf_counter();actual=compiler.scan_source(source)
                elapsed=1000*(time.perf_counter()-start)
            assert actual==expected,'screen optimization changed source data or metadata'
            rows.append({'trial':trial,'arm':arm,'scan_ms':elapsed})
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    result={'evidence_mode':'LOCAL','generative_calls':0,'files':len(expected),
            'source_manifest':[{'path':f.path,'sha256':f.sha256,'bytes':f.size} for f in expected],
            'rows':rows,'source_equivalence_checks':len(rows),
            'median_scan_ms':{arm:statistics.median(r['scan_ms'] for r in rows if r['arm']==arm) for arm in ('reference','candidate')},
            'code_sha256':{p.relative_to(repo).as_posix():sha(p) for p in (reference,Path(__file__),repo/'npk/pack/source_policy.py',repo/'npk/pack/compile.py')},
            'limitations':['Repeated scans on one machine with warm OS caches; no model calls in measured work',
                           'LIVE answer IO ran concurrently; endpoint latency is observational',
                           'Identical accepted source on this corpus is not proof of detecting arbitrary credentials']}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print({'median_scan_ms':result['median_scan_ms'],'equivalence_checks':len(rows)})


if __name__=='__main__':main()

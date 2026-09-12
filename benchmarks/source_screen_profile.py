"""LOCAL exact-pattern screening challengers over pinned public source.

These are equivalent-match candidates for the current patterns, not new secret
detectors. No source values or matches are printed or retained in the report.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from npk.pack.source_policy import PATTERNS

MARKERS={'nvidia':('nvapi-',),'openai':('sk-',),'aws':('AKIA','ASIA'),
         'github':('ghp_','gho_','ghu_','ghs_','ghr_','github_pat_'),
         'private_key':('PRIVATE KEY-----',)}


def matches(text,method):
    found=[]
    for name,pattern in PATTERNS:
        if method=='openai_literal' and name=='openai' and 'sk-' not in text:continue
        if method=='all_literals' and not any(marker in text for marker in MARKERS[name]):continue
        if pattern.search(text):found.append(name)
    return found


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    plan=json.loads((repo/'experiments/runs/repository-click-v1/plan.json').read_text())
    source=repo/'experiments/runs/repository-click-v1/source/click-8.5.0';texts=[]
    for item in plan['source_manifest']:
        raw=(source/item['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256'];texts.append(raw.decode())
    # Generated inputs are temporary synthetic strings, never stored in output.
    values=['nvapi-'+'A'*64,'sk-proj-'+'B'*80,'sk-'+'C'*32,'AKIA'+'D'*16,'ASIA'+'E'*16,
            *['gh'+letter+'_'+'F'*36 for letter in 'pousr'],'github_pat_'+'G'*40,
            *['-----BEGIN '+kind+'PRIVATE KEY-----' for kind in ('','RSA ','EC ','DSA ','OPENSSH ','ENCRYPTED ')]]
    rng=random.Random(1206)
    synthetic=[]
    for value in values:
        for changed in (value,value.lower(),value.upper(),value[:10],value[1:]):
            for prefix in ('','word','./','\u2028'):
                synthetic.append(prefix+changed+'X'*rng.randrange(20))
    for text in texts+synthetic:
        expected=matches(text,'unfiltered')
        assert expected==matches(text,'openai_literal')==matches(text,'all_literals')
    rows=[]
    for trial in range(15):
        methods=['unfiltered','openai_literal','all_literals'];rng.shuffle(methods)
        for method in methods:
            start=time.perf_counter()
            for text in texts:assert not matches(text,method)
            rows.append({'trial':trial,'method':method,'ms':1000*(time.perf_counter()-start)})
    per_pattern={}
    for name,pattern in PATTERNS:
        times=[]
        for _ in range(5):
            start=time.perf_counter()
            for text in texts:assert not pattern.search(text)
            times.append(1000*(time.perf_counter()-start))
        per_pattern[name]=statistics.median(times)
    result={'evidence_mode':'LOCAL','generative_calls':0,'source_manifest':plan['source_manifest'],
            'source_chars':sum(map(len,texts)),'synthetic_differential_cases':len(synthetic),'rows':rows,
            'per_pattern_median_ms':per_pattern,
            'median_ms':{m:statistics.median(r['ms'] for r in rows if r['method']==m) for m in methods},
            'code_sha256':{p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (Path(__file__),repo/'npk/pack/source_policy.py')},
            'limitations':['Pinned source already in RAM; measures screening CPU, not total compilation or disk IO',
                           'Finite generated differential cases supplement inspection; not a proof of detecting arbitrary secrets',
                           'One machine; LIVE answer IO ran concurrently, endpoint latency is observational']}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print({k:result[k] for k in ('synthetic_differential_cases','median_ms','per_pattern_median_ms')})


if __name__=='__main__':main()

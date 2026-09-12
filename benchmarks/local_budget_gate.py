"""Check the product cache against captured exact outputs and measure its cost."""
import argparse
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import statistics
import sys
import time

from npk.pack import LocalTokenizer, PackSelector


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def run(experiment,asset,output):
    if output.exists():raise ValueError('Fresh product gate output required')
    output.mkdir(parents=True)
    plan=read(experiment/'plan.json');data=read(experiment/'results.json')
    assert data['plan_sha256']==sha((experiment/'plan.json').read_bytes())
    assert plan['asset_sha256']==sha(asset.read_bytes())
    pack=experiment/'compiled.npk';assert sha(pack.read_bytes())==plan['pack_sha256']
    repo=Path(__file__).resolve().parents[1]
    sources={p.relative_to(repo).as_posix():p.read_bytes().decode() for folder in ('npk','benchmarks','tests')
             for p in (repo/folder).rglob('*.py')}
    capture=gzip.compress(json.dumps(sources).encode(),mtime=0)
    (output/'sources.json.gz').write_bytes(capture)
    import psutil
    process=psutil.Process();before_rss=process.memory_info().rss
    start=time.perf_counter_ns();counter=LocalTokenizer(asset)
    init_ms=(time.perf_counter_ns()-start)/1e6;after_rss=process.memory_info().rss
    checked=set()
    for row in data['rows']:
        digest=row['context_sha256']
        if digest in checked:continue
        body=(experiment/'contexts'/(digest+'.txt')).read_bytes();assert sha(body)==digest
        assert counter.count(body.decode())==row['actual_tokens'];checked.add(digest)
    print({'phase':'saved_contexts','checked':len(checked)},flush=True)
    plain=PackSelector(pack);exact=PackSelector(pack,tokenizer=counter)
    rows={(r['query'],r['budget'],r['arm']):r for r in data['rows']}
    questions=sorted({r['query'] for r in data['rows']});budgets=plan['budgets']
    estimate_checks=0
    for query in questions:
        for budget in budgets:
            selection=plain.select(query,budget_tokens=budget)
            assert sha(selection.context_text().encode())==rows[query,budget,'estimated']['context_sha256']
            estimate_checks+=1
    chosen=sorted(questions,key=lambda q:sha(q.encode()))[:12];profile=[];rng=random.Random(2868)
    for trial in range(3):
        jobs=[(q,b) for q in chosen for b in budgets];rng.shuffle(jobs)
        for query,budget in jobs:
            counter.clear_cache()
            for state in ('cold_count_cache','immediate_repeat'):
                start=time.perf_counter_ns();cpu=time.process_time_ns()
                selected=exact.select(query,budget_tokens=budget)
                cpu=(time.process_time_ns()-cpu)/1e6;wall=(time.perf_counter_ns()-start)/1e6
                assert sha(selected.context_text().encode())==rows[query,budget,'exact']['context_sha256']
                assert selected.total_tokens==rows[query,budget,'exact']['actual_tokens']<=budget
                assert selected.query==query and not selected.used_generative_llm
                profile.append({'query':query,'budget':budget,'trial':trial,'state':state,'wall_ms':wall,'cpu_ms':cpu,
                                'actual_tokens':selected.total_tokens,'cache':counter.cache_info()})
        print({'phase':'product_profile','trial':trial,'observations':len(profile)},flush=True)
    report={'status':'PASSED','evidence_mode':'LOCAL','generative_calls':0,'new_api_calls':0,
            'parent_plan_sha256':data['plan_sha256'],'sources_sha256':sha(capture),
            'python':sys.version,'tokenizers_version':importlib.metadata.version('tokenizers'),
            'saved_context_counts_checked':len(checked),'unchanged_default_selections':estimate_checks,
            'matched_exact_selections':len(profile),'tokenizer_initialization_ms':init_ms,
            'rss_before_tokenizer':before_rss,'rss_after_tokenizer':after_rss,'profile':profile,
            'summary':[{'budget':b,**{s+'_median_ms':statistics.median(r['wall_ms'] for r in profile if
                        (r['budget'],r['state'])==(b,s)) for s in ('cold_count_cache','immediate_repeat')}} for b in budgets],
            'limitations':['12 deterministically sampled inspected questions; three shuffled repetitions',
                           'Immediate repeated requests do not model arbitrary unseen queries',
                           'Query timings exclude tokenizer construction; construction is measured once separately',
                           'RSS snapshots describe this process, not causal peak allocation or a universal memory cap',
                           'Host load is uncontrolled; no overlapping benchmark, tests or LIVE work by this agent']}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({k:v for k,v in report.items() if k not in ('profile','limitations')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('experiment','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.experiment,a.asset,a.output)

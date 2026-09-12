"""Compare exact local counting, a bounded count cache and additive packing.

The additive challenger is an approximation followed by exact reconciliation.
It has no additivity guarantee and is not a runtime promotion. All quality
metrics are source retention on already inspected CRISP development tasks.
"""
from collections import OrderedDict, defaultdict
from dataclasses import asdict
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

from benchmarks.rival_reproduction import attributed_context, retention
from npk.pack import LocalTokenizer, PackSelector, compile_pack
from npk.pack.format import load_blocks, open_pack


def sha(body): return hashlib.sha256(body).hexdigest()


class CachedTokenizer(LocalTokenizer):
    """Experiment: exact string keys, per-instance LRU, bounded retained size."""
    def __init__(self, path, max_bytes=4*1024*1024, max_entries=4096):
        super().__init__(path, cache_bytes=0)
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.cache = OrderedDict()
        self.retained_bytes = self.hits = self.misses = 0

    def clear(self):
        self.cache.clear()
        self.retained_bytes = self.hits = self.misses = 0

    def count(self, text):
        if text in self.cache:
            self.hits += 1
            self.cache.move_to_end(text)
            return self.cache[text][0]
        self.misses += 1
        count = super().count(text)
        size = sys.getsizeof(text) + 256  # text + conservative entry allowance
        if size <= self.max_bytes and self.max_entries > 0:
            while self.cache and (self.retained_bytes+size > self.max_bytes
                                  or len(self.cache) >= self.max_entries):
                _, (_, dropped) = self.cache.popitem(last=False)
                self.retained_bytes -= dropped
            self.cache[text] = (count, size)
            self.retained_bytes += size
        return count


class AdditiveSelector(PackSelector):
    """Approximate admissions; inherited final guard still counts exact bytes."""
    def _fits(self, evidence, text, budget, **kwargs):
        return (sum(self.tokenizer.count(e.text) for e in evidence)
                + self.tokenizer.count(text)
                + len(evidence)*self.tokenizer.count('\n\n')) <= budget


def run(snapshot, pack, asset, output):
    if output.exists(): raise ValueError('Fresh experiment directory required')
    output.mkdir(parents=True)
    contexts = output/'contexts'; contexts.mkdir()
    frozen = json.loads((snapshot/'snapshot.json').read_text())
    for name, metadata in frozen['files'].items():
        assert sha((snapshot/name).read_bytes()) == metadata['sha256']
    tasks = json.loads((snapshot/'work/tasks_heldout.json').read_text())
    grouped = defaultdict(list)
    for task in tasks: grouped[task['query']].append(task)
    questions = sorted(grouped)
    budgets = [512, 2048, 8192]
    # This raw backend is independent of the product wrapper and its caches.
    from tokenizers import Tokenizer
    oracle = Tokenizer.from_file(str(asset)); oracle.no_truncation(); oracle.no_padding()
    actual = lambda text: len(oracle.encode(text, add_special_tokens=False).ids)
    source = snapshot/'corpus/test_src'
    corpus = {p.relative_to(source).as_posix(): p.read_bytes().decode().replace('\r\n','\n').replace('\r','\n')
              for p in sorted(source.rglob('*.py'))}
    compilation = None
    if pack is None:
        pack = output/'compiled.npk'
        started = time.perf_counter_ns()
        stats = compile_pack(source, pack, python_members=True)
        compilation = {'wall_ms':(time.perf_counter_ns()-started)/1e6,
                       'stats':asdict(stats),'artifact_bytes':pack.stat().st_size}
    # Audit every stored block once, including physical line provenance.
    with open_pack(pack) as con:
        for block in load_blocks(con, [r[0] for r in con.execute('SELECT id FROM blocks')]):
            _, extent = block.span.rsplit(':',1); lo,hi = map(int,extent.split('-'))
            assert block.text == '\n'.join(corpus[block.path].split('\n')[lo-1:hi])
    counters = {'exact':LocalTokenizer(asset,cache_bytes=0), 'cached':CachedTokenizer(asset),
                'additive':CachedTokenizer(asset)}
    selectors = {'estimated':PackSelector(pack)}
    selectors.update({arm:(AdditiveSelector if arm=='additive' else PackSelector)(pack,tokenizer=counter)
                      for arm,counter in counters.items()})
    repo = Path(__file__).resolve().parents[1]
    code = {p.relative_to(repo).as_posix():p.read_bytes().decode() for directory in ('npk','benchmarks','tests')
            for p in (repo/directory).rglob('*.py')}
    captured = gzip.compress(json.dumps(code).encode(),mtime=0)
    (output/'execution-sources.json.gz').write_bytes(captured)
    plan = {'evidence_mode':'LOCAL','generative_calls':0,'snapshot_sha256':sha((snapshot/'snapshot.json').read_bytes()),
            'pack_sha256':sha(pack.read_bytes()),'asset_sha256':sha(asset.read_bytes()),
            'execution_sources_sha256':sha(captured),'tasks':tasks,'budgets':budgets,'arms':list(selectors),
            'python':sys.version,'versions':{k:importlib.metadata.version(k) for k in ('tokenizers','pytest')},
            'compilation':compilation,
            'corpus_tokens':actual('\n\n'.join(corpus.values())), 'unique_queries':len(questions),
            'available_tokens':actual('\n\n'.join(corpus.values())),
            'limits':['Context and separators only; query and caller framing excluded',
                      'Inspected source-retention development tasks, not answer accuracy',
                      '4 MiB cache bound is retained text plus entry allowance, not whole-process RSS',
                      'Host load is uncontrolled; only this agent avoids concurrent compute',
                      'Product ranking and whole member blocks are unchanged in every arm']}
    (output/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    rows=[]; rng=random.Random(2861)
    jobs=[(q,b,a) for q in questions for b in budgets for a in selectors];rng.shuffle(jobs)
    for i,(query,budget,arm) in enumerate(jobs):
        counter=counters.get(arm)
        if isinstance(counter,CachedTokenizer): counter.clear()
        started=time.perf_counter_ns()
        selection=selectors[arm].select(query,budget_tokens=budget)
        elapsed=(time.perf_counter_ns()-started)/1e6
        context=selection.context_text(); digest=sha(context.encode()); (contexts/(digest+'.txt')).write_bytes(context.encode())
        count=actual(context)
        if arm!='estimated': assert count==selection.total_tokens<=budget
        assert selection.query==query and not selection.used_generative_llm
        items=[asdict(e) for e in selection.evidence]
        rows.append({'query':query,'budget':budget,'arm':arm,'context_sha256':digest,'actual_tokens':count,
                     'reported_tokens':selection.total_tokens,'wall_ms':elapsed,'fallback':selection.seed_failed,
                     'items':items,'notes':selection.notes,
                     'hits':{t['task_id']:retention(attributed_context(items,t),t['needles'])['strict_hit']
                             for t in grouped[query]}})
        if (i+1)%200==0:
            (output/'partial.json').write_text(json.dumps(rows),encoding='utf-8')
            print({'phase':'quality','done':i+1,'planned':len(jobs)},flush=True)
    lookup={(r['query'],r['budget'],r['arm']):r for r in rows}
    assert all(lookup[q,b,'exact']['context_sha256']==lookup[q,b,'cached']['context_sha256']
               for q in questions for b in budgets)
    # Warm measurement is an immediate identical request after a cold request.
    # It is explicitly not a claim about arbitrary new questions or server load.
    chosen=sorted(questions,key=lambda q:sha(q.encode()))[:12]
    profile=[]
    for trial in range(3):
        jobs=[(q,b,a) for q in chosen for b in budgets for a in selectors]; rng.shuffle(jobs)
        for query,budget,arm in jobs:
            counter=counters.get(arm)
            if isinstance(counter,CachedTokenizer): counter.clear()
            for state in ('cold_count_cache','immediate_repeat'):
                start=time.perf_counter_ns(); before=time.process_time_ns()
                selected=selectors[arm].select(query,budget_tokens=budget)
                cpu=(time.process_time_ns()-before)/1e6; wall=(time.perf_counter_ns()-start)/1e6
                assert sha(selected.context_text().encode())==lookup[query,budget,arm]['context_sha256']
                profile.append({'query':query,'budget':budget,'arm':arm,'trial':trial,'state':state,'wall_ms':wall,'cpu_ms':cpu,
                                'cache_retained_bytes':getattr(counter,'retained_bytes',0),
                                'cache_entries':len(counter.cache) if isinstance(counter,CachedTokenizer) else 0})
        print({'phase':'profile','trial':trial,'observations':len(profile)},flush=True)
    summary=[]
    for arm in selectors:
        for budget in budgets:
            group=[r for r in rows if (r['arm'],r['budget'])==(arm,budget)]
            summary.append({'arm':arm,'budget':budget,'tasks':len(tasks),'unique_queries':len(group),
                            'attributed_needle_hits':sum(sum(r['hits'].values()) for r in group),
                            'query_budget_overruns':sum(r['actual_tokens']>budget for r in group),
                            'mean_actual_tokens':statistics.mean(r['actual_tokens'] for r in group),
                            'contexts_changed_from_exact':sum(r['context_sha256']!=lookup[r['query'],budget,'exact']['context_sha256'] for r in group),
                            **{state+'_median_ms':statistics.median(r['wall_ms'] for r in profile if
                               (r['arm'],r['budget'],r['state'])==(arm,budget,state))
                               for state in ('cold_count_cache','immediate_repeat')}})
    result={'plan_sha256':sha((output/'plan.json').read_bytes()),'rows':rows,'profile':profile,'summary':summary}
    (output/'results.json').write_text(json.dumps(result),encoding='utf-8')
    print({'status':'COMPLETE','selections':len(rows),'profile_observations':len(profile),'summary':summary},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--pack',type=Path,help='Omit to freshly compile the frozen corpus')
    args=p.parse_args();run(args.snapshot,args.pack,args.asset,args.output)

"""Matched-evidence CPU comparison of bounded speculative tokenizer batches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import time

from npk.pack import LocalTokenizer, PackSelector
from benchmarks.fast_tokenizer_eval import FastCount
from benchmarks.batch_tokenizer import BatchCount, BatchSelector


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run(a):
    import tokenizers
    if os.environ.get('RAYON_NUM_THREADS') != str(a.threads): raise ValueError('Set Rayon threads before launch')
    if os.environ.get('TOKENIZERS_PARALLELISM') != 'true': raise ValueError('Explicit parallelism required')
    if a.output.exists(): raise ValueError('Fresh batch experiment required')
    repo = Path(__file__).resolve().parents[1]; a.output.mkdir(parents=True)
    paths = [*sorted((repo/'npk').rglob('*.py')), Path(__file__),
             repo/'benchmarks/batch_tokenizer.py', repo/'benchmarks/fast_tokenizer_eval.py']
    sources = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in paths}
    plan = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'seed': 2915,
            'asset_sha256': sha(a.asset.read_bytes()), 'pack_sha256': sha(a.pack.read_bytes()),
            'tasks_sha256': sha(a.tasks.read_bytes()), 'source_sha256': sources,
            'python': platform.python_version(), 'tokenizers': tokenizers.__version__,
            'logical_cpu_count': os.cpu_count(), 'rayon_threads': a.threads,
            'budgets': [512, 2048, 8192], 'repeats': 3, 'batch_characters': 128*1024,
            'arms': ['ordinary', 'no_offsets', 'batch4', 'batch8', 'batch16'],
            'hypothesis': 'Bounded speculative exact counts reduce rejection-heavy packing wall time',
            'limits': ['One CPU host with uncontrolled background load',
                       'Loaded tokenizers; outer and speculative caches cleared before every query',
                       'Speculative work can increase CPU time even when wall time improves',
                       'All statements of the public selector except its iterator are preserved',
                       'No source-retrieval or answer-quality improvement is claimed from batching']}
    write(a.output/'plan.json', plan)
    for name in sources:
        copy = a.output/'source'/name; copy.parent.mkdir(parents=True, exist_ok=True); copy.write_bytes((repo/name).read_bytes())
    codec = tokenizers.Tokenizer.from_file(str(a.asset)); codec.no_padding(); codec.no_truncation()
    counters = {'ordinary': LocalTokenizer(a.asset), 'no_offsets': FastCount(a.asset),
                **{'batch'+str(n): BatchCount(a.asset) for n in (4, 8, 16)}}
    selectors = {name: (BatchSelector(a.pack, tokenizer=c, batch_size=int(name[5:]),
                                     batch_characters=plan['batch_characters']) if name.startswith('batch')
                       else PackSelector(a.pack, tokenizer=c)) for name, c in counters.items()}
    rng = random.Random(plan['seed']); rows = []; signatures = {}; tasks = read(a.tasks)['tasks']
    for task in tasks:
        for budget in plan['budgets']:
            expected = None
            for repeat in range(plan['repeats']):
                order = list(counters); rng.shuffle(order)
                for name in order:
                    counter = counters[name]; counter.clear_cache()
                    started = time.perf_counter(); cpu = time.process_time()
                    selected = selectors[name].select(task['query'], budget_tokens=budget)
                    wall = 1000*(time.perf_counter()-started); processor = 1000*(time.process_time()-cpu)
                    exact = len(codec.encode(selected.context_text(), add_special_tokens=False).ids)
                    assert exact == selected.total_tokens <= budget
                    assert selected.query == task['query'] and not selected.used_generative_llm
                    record = selected.as_dict(); record.pop('latency_ms')
                    if expected is None: expected = record
                    else: assert expected == record, 'Speculative batch changed public selection'
                    rows.append({'task': task['task_id'], 'budget': budget, 'repeat': repeat, 'arm': name,
                                 'tokens': exact, 'context_sha256': sha(selected.context_text().encode()),
                                 'wall_ms': wall, 'cpu_ms': processor, 'fallback': selected.seed_failed,
                                 'batch': counter.batch_info() if isinstance(counter, BatchCount) else None})
            signatures[task['task_id']+':'+str(budget)] = expected
            write(a.output/'partial.json', rows)
        print({'phase': 'profile', 'task': task['task_id'], 'rows': len(rows)}, flush=True)
    for name, digest in sources.items(): assert sha((repo/name).read_bytes()) == digest
    summary = [{'arm': name, 'budget': budget,
                'median_wall_ms': statistics.median(r['wall_ms'] for r in rows if r['arm'] == name and r['budget'] == budget),
                'median_cpu_ms': statistics.median(r['cpu_ms'] for r in rows if r['arm'] == name and r['budget'] == budget)}
               for name in counters for budget in plan['budgets']]
    write(a.output/'selections.json', signatures)
    report = {'status': 'COMPLETE', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'plan_sha256': sha((a.output/'plan.json').read_bytes()), 'rows': rows, 'summary': summary}
    write(a.output/'report.json', report)
    print({'status': 'COMPLETE', 'rows': len(rows), 'summary': summary}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('pack', 'tasks', 'asset', 'output'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--threads', type=int, required=True)
    run(p.parse_args())

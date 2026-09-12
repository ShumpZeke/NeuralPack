"""Declared local comparison of ordinary, no-offset and guarded piece counts."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import time

from npk.pack import LocalTokenizer, PackSelector
from npk.pack.format import open_pack
from benchmarks.fast_tokenizer_eval import FastCount
from benchmarks.piece_tokenizer import PieceCount


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run(a):
    import tokenizers
    if a.output.exists(): raise ValueError('Fresh piece-count experiment required')
    a.output.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]
    code_files = [*sorted((repo/'npk').rglob('*.py')), Path(__file__),
                  repo/'benchmarks/piece_tokenizer.py', repo/'benchmarks/fast_tokenizer_eval.py']
    sources = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in code_files}
    plan = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'seed': 2913,
            'asset_sha256': sha(a.asset.read_bytes()), 'pack_sha256': sha(a.pack.read_bytes()),
            'tasks_sha256': sha(a.tasks.read_bytes()), 'source_sha256': sources,
            'python': platform.python_version(), 'tokenizers': tokenizers.__version__,
            'budgets': [512, 2048, 8192], 'repeats': 3,
            'arms': ['ordinary', 'no_offsets', 'pieces_no_cache', 'pieces_cached'],
            'hypothesis': 'Reuse BPE counts after whole-assembly pre-tokenization without changing selected evidence',
            'limits': ['Inspected questions and one tokenizer asset; no general equivalence theorem',
                       'Tokenizers are loaded; every profiled query clears outer and piece caches',
                       'Whole assembled text is pre-tokenized afresh, not independent passage token sums',
                       'One CPU host with uncontrolled background load',
                       'Large-context timings below are counting-only, not query latency']}
    write(a.output/'plan.json', plan)
    for name in sources:
        copy = a.output/'source'/name; copy.parent.mkdir(parents=True, exist_ok=True); copy.write_bytes((repo/name).read_bytes())
    codec = tokenizers.Tokenizer.from_file(str(a.asset)); codec.no_padding(); codec.no_truncation()
    cfg = read(a.asset); probe = PieceCount(a.asset, cache_bytes=0)
    cases = {}; origins = {}
    for path in sorted((a.seed/'contexts').glob('*.txt')):
        body = path.read_bytes(); assert sha(body) == path.stem
        cases[path.stem] = body.decode(); origins[path.stem] = 'frozen_seed_context'
    rng = random.Random(plan['seed'])
    generated = ['', ' ', '\r\n\r\n', 'ab', 'a\n\nb', '\x00界😀', 'x\u200d\u0301\u2028\u2029y']
    for token in cfg.get('added_tokens', []):
        generated.extend([token['content'], 'x '+token['content']+' y', '\n'+token['content']+'\n'])
    for _ in range(500):
        generated.append(''.join(rng.choice(['a', '界', '\u0301', '\r\n', '\n\n', ' ', '😀', '/', '42', '\x00'])
                                 for _ in range(rng.randrange(1, 90))))
    write(a.output/'generated-cases.json', generated)
    for text in generated:
        digest = sha(text.encode()); cases[digest] = text; origins[digest] = 'generated'
    checked = []
    for digest, text in cases.items():
        expected = codec.encode(text, add_special_tokens=False).ids
        assert probe.differential_ids(text) == expected, 'Piece decomposition token IDs differ'
        assert probe.count(text) == len(expected), 'Cached piece count differs'
        checked.append({'sha256': digest, 'tokens': len(expected), 'origin': origins[digest],
                        'fallback': bool(probe._needs_fallback(text))})
        if len(checked) % 1000 == 0: print({'phase': 'differential', 'cases': len(checked)}, flush=True)
    write(a.output/'differential.json', checked)
    del cases
    counters = {'ordinary': LocalTokenizer(a.asset), 'no_offsets': FastCount(a.asset),
                'pieces_no_cache': PieceCount(a.asset, piece_bytes=0), 'pieces_cached': PieceCount(a.asset)}
    selectors = {name: PackSelector(a.pack, tokenizer=counter) for name, counter in counters.items()}
    rows = []; tasks = read(a.tasks)['tasks']
    for task in tasks:
        for budget in plan['budgets']:
            expected = None
            for repeat in range(plan['repeats']):
                order = list(counters); rng.shuffle(order)
                for name in order:
                    counter = counters[name]; counter.clear_cache()
                    start = time.perf_counter(); cpu = time.process_time()
                    result = selectors[name].select(task['query'], budget_tokens=budget)
                    wall = 1000*(time.perf_counter()-start); processor = 1000*(time.process_time()-cpu)
                    body = result.context_text(); exact = len(codec.encode(body, add_special_tokens=False).ids)
                    assert exact == result.total_tokens <= budget
                    assert result.query == task['query'] and not result.used_generative_llm
                    record = result.as_dict(); record.pop('latency_ms')
                    if expected is None: expected = record
                    else: assert expected == record, 'Public selection semantics differ'
                    rows.append({'task': task['task_id'], 'budget': budget, 'repeat': repeat, 'arm': name,
                                 'tokens': exact, 'context_sha256': sha(body.encode()), 'wall_ms': wall,
                                 'cpu_ms': processor, 'fallback': result.seed_failed,
                                 'cache': counter.cache_info(),
                                 'pieces': counter.piece_info() if isinstance(counter, PieceCount) else None})
            write(a.output/'partial.json', rows)
        print({'phase': 'profile', 'task': task['task_id'], 'rows': len(rows)}, flush=True)
    # A separate exact-count scale diagnostic using literal compiled source.
    # Report measured tokens, not the requested size labels as achieved sizes.
    with open_pack(a.pack) as con:
        whole = '\n\n'.join(r['text'] for r in con.execute('SELECT text FROM blocks ORDER BY id'))
    total = len(codec.encode(whole, add_special_tokens=False).ids)
    scale = []
    for requested in (2000, 25000, 50000, 100000, 250000):
        text = whole[:round(len(whole)*min(requested/total, 1))]
        exact = len(codec.encode(text, add_special_tokens=False).ids)
        for repeat in range(plan['repeats']):
            order = list(counters); rng.shuffle(order)
            for name in order:
                counter = counters[name]; counter.clear_cache()
                start = time.perf_counter(); cpu = time.process_time(); actual = counter.count(text)
                wall = 1000*(time.perf_counter()-start); processor = 1000*(time.process_time()-cpu)
                assert actual == exact
                scale.append({'requested_size': requested, 'actual_tokens': exact, 'characters': len(text),
                              'context_sha256': sha(text.encode()), 'arm': name, 'repeat': repeat,
                              'wall_ms': wall, 'cpu_ms': processor})
    for name, digest in sources.items(): assert sha((repo/name).read_bytes()) == digest
    summary = [{'arm': name, 'budget': budget,
                'median_wall_ms': statistics.median(r['wall_ms'] for r in rows if r['arm'] == name and r['budget'] == budget)}
               for name in counters for budget in plan['budgets']]
    report = {'status': 'COMPLETE', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'plan_sha256': sha((a.output/'plan.json').read_bytes()), 'differential_cases': len(checked),
              'fallback_cases': sum(c['fallback'] for c in checked), 'selection_rows': rows,
              'summary': summary, 'count_only_scale': scale}
    write(a.output/'report.json', report)
    print({k: v for k, v in report.items() if k not in ('selection_rows', 'count_only_scale')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('pack', 'tasks', 'asset', 'seed', 'output'): p.add_argument('--'+name, type=Path, required=True)
    run(p.parse_args())

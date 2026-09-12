"""Reproduce CRISP's source-line benchmark, including exact-cost NPK controls.

No answer model is used. This is source retention on inspected rival tasks.
The exact-cost control changes packing cost only, keeping NPK's lexical rank,
candidate limit and whole blocks. It is not a production selector promotion.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import re
import statistics
import sys
import time

from npk.pack.compile import compile_pack
from npk.pack.format import load_blocks, open_pack
from npk.pack.select import PackSelector, _lexical_channel


BUDGETS = (512, 1024, 2048, 4096, 8192)
ARMS = ('npk_default', 'npk_members', 'npk_exact', 'npk_members_exact',
        'crisp', 'crisp_bm25', 'crisp_bm25_struct')


def sha(body):
    return hashlib.sha256(body).hexdigest()


def norm(text):
    return ' '.join(text.split())


def retention(context, needles):
    flat = norm(context)
    found = sum(n in flat for n in needles)
    return {'strict_hit': bool(needles) and found == len(needles),
            'line_recall': found / len(needles) if needles else None}


def attributed_context(items, task):
    # Require the correct path and intersecting physical source span in addition
    # to emitted text. This is still a diagnostic, not semantic sufficiency.
    _, span = task['span'].rsplit(':', 1)
    start, end = map(int, span.split('-'))
    texts = []
    for item in items:
        _, extent = item['span'].rsplit(':', 1)
        lo, hi = map(int, extent.split('-'))
        if item['path'] == task['path'] and lo <= end and hi >= start:
            texts.append(item['text'])
    return '\n\n'.join(texts)


def exact_pack(con, query, budget, tok, limit=60):
    ids = _lexical_channel(con, query, limit)
    blocks = {b.id: b for b in load_blocks(con, ids)}
    selected = []
    for bid in ids:
        block = blocks[bid]
        trial = '\n\n'.join([e['text'] for e in selected] + [block.text])
        if tok.count(trial) <= budget:
            selected.append({'path': block.path, 'span': block.span, 'text': block.text,
                             'block_id': bid})
    if not selected and limit == 60:
        return exact_pack(con, query, budget, tok, limit=240)
    return selected


def run(snapshot, output, resume=False, max_jobs=None):
    if output.exists() and not resume:
        raise ValueError('New experiment output required')
    frozen = json.loads((snapshot / 'snapshot.json').read_text())
    for name, metadata in frozen['files'].items():
        if sha((snapshot / name).read_bytes()) != metadata['sha256']:
            raise ValueError('Frozen rival source changed')
    sys.path.insert(0, str(snapshot.resolve()))
    from crisp.index import build
    from crisp.select import Selector
    from crisp.tokens import Tokenizer
    from bench.run_crisp import Base, arm_bm25_topk

    tok = Tokenizer('cl100k_base')
    if not tok.exact:
        raise RuntimeError('Real cl100k_base is required; no calibrated fallback')
    output.mkdir(parents=True, exist_ok=resume)
    (output / 'contexts').mkdir(exist_ok=resume)
    tasks = json.loads((snapshot / 'work/tasks_heldout.json').read_text())
    assert len(tasks) == 246 and len({t['task_id'] for t in tasks}) == 246
    source = snapshot / 'corpus/test_src'
    source_files = {p.relative_to(source).as_posix(): p.read_bytes()
                    for p in sorted(source.rglob('*.py'))}
    # Validate all expected line strings against the declared target span.
    for task in tasks:
        _, span = task['span'].rsplit(':', 1)
        start, end = map(int, span.split('-'))
        text = source_files[task['path']].decode().replace('\r\n', '\n').replace('\r', '\n')
        literal = '\n'.join(text.split('\n')[start-1:end])
        assert retention(literal, task['needles'])['strict_hit']
    raw_source = '\n\n'.join(b.decode().replace('\r\n', '\n').replace('\r', '\n') for b in source_files.values())
    manifest = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'snapshot_sha256': sha((snapshot / 'snapshot.json').read_bytes()),
                'tasks': tasks, 'arms': ARMS, 'budgets': BUDGETS, 'shuffle_seed': 28029,
                'source_files': {n: {'sha256': sha(b), 'bytes': len(b)} for n, b in source_files.items()},
                'corpus_tokens_cl100k': tok.count(raw_source), 'unique_questions': len({t['query'] for t in tasks}),
                'query_multiplicities': dict(Counter(t['query'] for t in tasks)),
                'limitations': ['Frozen current task file has 246 tasks; this is not the historical 300-task headline reproduction',
                                'All rival tasks are inspected development data for this project',
                                'Source-line retention is not target answer accuracy',
                                'cl100k_base caps cover context and separators only; query and wrappers excluded for every arm',
                                'cl100k_base is not the configured NIM target tokenizer',
                                'Default NPK arms use estimated caps; exact-cost controls use actual assembled counts',
                                'Single shuffled pass with tokenizer cache cleared per observation; latency is diagnostic, not an isolated performance claim',
                                'Attribution requires path, overlapping span and literal output; it is not a complete line-map proof']}
    manifest['versions'] = {'python': sys.version, 'tiktoken': importlib.metadata.version('tiktoken')}
    repo = Path(__file__).resolve().parents[1]
    code = {p.relative_to(repo).as_posix(): {'sha256': sha(p.read_bytes()), 'text': p.read_bytes().decode()}
            for folder in ('npk', 'benchmarks') for p in (repo/folder).rglob('*.py')}
    if resume:
        saved = json.loads((output/'plan.json').read_text())
        assert all(saved[k] == json.loads(json.dumps(manifest[k])) for k in
                   ('snapshot_sha256', 'tasks', 'arms', 'budgets', 'source_files', 'versions'))
        manifest = saved
        continuation = gzip.compress(json.dumps(code).encode(), mtime=0)
        (output/('continuation-sources-'+sha(continuation)+'.json.gz')).write_bytes(continuation)
    else:
        (output/'execution-sources.json.gz').write_bytes(gzip.compress(json.dumps(code).encode(), mtime=0))
        manifest['execution_sources_sha256'] = sha((output/'execution-sources.json.gz').read_bytes())
        (output / 'plan.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    builds = {}
    for name, members in (('npk_default', False), ('npk_members', True)):
        if resume: continue
        start = time.perf_counter()
        stats = compile_pack(source, output / (name + '.npk'), python_members=members)
        builds[name] = {'stats': asdict(stats), 'wall_ms': (time.perf_counter()-start)*1000}
    if not resume:
        start = time.perf_counter()
        builds['crisp'] = {'stats': build(source, output / 'rival.crisp'),
                           'wall_ms': (time.perf_counter()-start)*1000}
        (output / 'compilation.json').write_text(json.dumps(builds, indent=2), encoding='utf-8')
        (output/'artifact-hashes.json').write_text(json.dumps({p.name: sha(p.read_bytes()) for p in output.iterdir()
                                                            if p.suffix in ('.npk', '.crisp')}), encoding='utf-8')
    else:
        # Older interrupted runs predate this file; keep them immutable and use
        # a fresh run for checkpointed measurements.
        for name, expected in json.loads((output/'artifact-hashes.json').read_text()).items():
            assert sha((output/name).read_bytes()) == expected
    print(json.dumps({'phase': 'compiled', 'source_files': len(source_files),
                      'corpus_tokens': manifest['corpus_tokens_cl100k'],
                      'unique_questions': manifest['unique_questions']}), flush=True)
    selectors = {name: PackSelector(output/(name+'.npk')) for name in ('npk_default', 'npk_members')}
    stack = ExitStack()
    connections = {name: stack.enter_context(open_pack(output/(name+'.npk'))) for name in selectors}
    rival = Selector(str(output/'rival.crisp'))
    bases = {'crisp_bm25': Base(str(output/'rival.crisp')),
             'crisp_bm25_struct': Base(str(output/'rival.crisp'), structural=True)}
    jobs = [(t, b, arm) for t in tasks for b in BUDGETS for arm in ARMS]
    random.Random(28029).shuffle(jobs)
    rows = []
    import psutil
    process = psutil.Process()
    rss_samples = []
    done = set()
    tasks_by_id = {t['task_id']: t for t in tasks}
    records = output/'records'
    records.mkdir(exist_ok=True)
    for path in sorted(records.glob('*.json')):
        row = json.loads(path.read_text()); task = tasks_by_id[row['task']]
        key = (row['task'], row['budget'], row['arm'])
        assert key not in done
        context = (output/'contexts'/(row['context_sha256']+'.txt')).read_text(encoding='utf-8')
        assert sha(context.encode()) == row['context_sha256']
        assert tok.count(context) == row['tokens_cl100k']
        assert all(row[k] == v for k, v in retention(context, task['needles']).items())
        done.add(key); rows.append({k: v for k, v in row.items() if k != 'items'})
        tok._count_cached.cache_clear()
    pending = [(t,b,a) for t,b,a in jobs if (t['task_id'],b,a) not in done]
    if max_jobs is not None: pending = pending[:max_jobs]
    try:
        with (output/'batch-progress.jsonl').open('a', encoding='utf-8') as log:
            for i, (task, budget, arm) in enumerate(pending):
                started = time.perf_counter()
                items = None
                if arm in selectors:
                    result = selectors[arm].select(task['query'], budget_tokens=budget)
                    items = [asdict(e) for e in result.evidence]
                    context = result.context_text()
                    abstained = result.seed_failed or not result.evidence
                elif arm in ('npk_exact', 'npk_members_exact'):
                    original = 'npk_default' if arm == 'npk_exact' else 'npk_members'
                    items = exact_pack(connections[original], task['query'], budget, tok)
                    context = '\n\n'.join(e['text'] for e in items)
                    abstained = not items
                elif arm == 'crisp':
                    result = rival.select(task['query'], budget)
                    items = [asdict(e) for e in result.items]
                    context = result.context_text()
                    abstained = result.abstained
                else:
                    context, _, count = arm_bm25_topk(bases[arm], task['query'], budget)
                    abstained = not context
                elapsed = (time.perf_counter()-started)*1000
                digest = sha(context.encode())
                (output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
                actual = tok.count(context)
                row = {'task': task['task_id'], 'family': task['family'], 'arm': arm,
                       'budget': budget, 'tokens_cl100k': actual, 'budget_exceeded': actual > budget,
                       'latency_ms': elapsed, 'abstained': abstained, 'context_sha256': digest,
                       'items': items, **retention(context, task['needles']),
                       'body_coverage': sum(n in norm(context) for n in task['body'])/len(task['body']) if task['body'] else None,
                       'attributed_strict_hit': retention(attributed_context(items, task), task['needles'])['strict_hit'] if items is not None else None}
                rows.append({k: v for k, v in row.items() if k != 'items'})
                key = sha(json.dumps([row['task'],budget,arm]).encode())
                temporary = records/(key+'.pending')
                temporary.write_text(json.dumps(row), encoding='utf-8')
                temporary.replace(records/(key+'.json'))
                # CRISP's 200k-entry cache retains whole assembled contexts.
                # Bound this experiment's memory without changing any counts.
                tok._count_cached.cache_clear()
                if (i+1) % 250 == 0:
                    log.flush()
                    rss = process.memory_info().rss
                    rss_samples.append({'done': i+1, 'rss_bytes': rss})
                    log.write(json.dumps(rss_samples[-1])+'\n')
                    print(json.dumps({'phase': 'query', 'done': i+1, 'total': len(jobs), 'rss_bytes': rss}), flush=True)
    finally:
        stack.close()
        rival.close()
        for base in bases.values(): base.con.close()
    if len(rows) != len(jobs):
        print(json.dumps({'status': 'CHECKPOINT', 'completed': len(rows), 'planned': len(jobs)}), flush=True)
        return
    summaries = []
    for arm in ARMS:
        for budget in BUDGETS:
            group = [r for r in rows if r['arm']==arm and r['budget']==budget]
            summaries.append({'arm': arm, 'budget': budget, 'tasks': len(group),
                              'strict_hits': sum(r['strict_hit'] for r in group),
                              'attributed_hits': sum(r['attributed_strict_hit'] for r in group) if arm not in bases else None,
                              'mean_tokens_cl100k': statistics.mean(r['tokens_cl100k'] for r in group),
                              'body_coverage': statistics.mean(r['body_coverage'] for r in group),
                              'budget_overruns': sum(r['budget_exceeded'] for r in group),
                              'abstentions': sum(r['abstained'] for r in group),
                              'median_ms': statistics.median(r['latency_ms'] for r in group)})
    report = {'status': 'COMPLETE', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'rows': len(rows), 'summaries': summaries, 'rss_samples': rss_samples,
              'limitations': manifest['limitations'] + ['Sampled RSS is not peak memory']}
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-jobs', type=int)
    args = parser.parse_args()
    run(args.snapshot, args.output, args.resume, args.max_jobs)

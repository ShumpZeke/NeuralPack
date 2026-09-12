"""Independent source/count/ordering checks of frozen packing experiments."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import statistics

from benchmarks.library_selection_audit import load_blocks, check_source_item
from benchmarks.library_failure_analysis import PRIMARY, definitions

sha = lambda b: hashlib.sha256(b).hexdigest()
read = lambda p: json.loads(p.read_bytes())


def expected_pool(ranks, seed, policy):
    if not policy.startswith('fuse'): return ranks[seed]
    weight = {'fuse1': 1, 'fuse2': 2}[policy]; scores = {}
    for ids, coefficient in ((ranks[seed], weight), (ranks['body'], 1)):
        assert len(ids) == len(set(ids))
        for index, bid in enumerate(ids): scores[bid] = scores.get(bid, 0.0)+coefficient/(index+60)
    return sorted(scores, key=lambda bid: -scores[bid])


def replay(pool, blocks, budget, policy, count):
    """Slow reference: choose from all remaining candidates after each attempt.

Unlike the candidate this uses no heap, queues, mutable generator feedback,
AST adaptation, public selector or candidate ordering implementation.
"""
    left = list(pool); chosen = []; accepted_groups = Counter()
    def group(bid):
        b = blocks[bid]
        if policy == 'file': return 'file', b['path']
        if policy == 'leaf': return ('leaf', b['name'].rsplit('.', 1)[-1]) if b['name'] else ('anonymous', bid)
        return 'unique', bid
    while left:
        i = min(range(len(left)), key=lambda i: accepted_groups[group(left[i])]) if policy in ('leaf', 'file') else 0
        bid = left.pop(i)
        joined = '\n\n'.join(blocks[b]['text'] for b in [*chosen, bid])
        if count(joined) <= budget:
            chosen.append(bid); accepted_groups[group(bid)] += 1
    return chosen


def hit(items, task):
    span = task['span'].rsplit(':', 1)[1]; lo, hi = map(int, span.split('-'))
    evidence = []
    for e in items:
        path, extent = e['span'].rsplit(':', 1); first, last = map(int, extent.split('-'))
        assert path == e['path']
        if path == task['path'] and first <= hi and lo <= last: evidence.append(e['text'])
    text = ' '.join('\n\n'.join(evidence).split())
    return bool(task['needles']) and all(part in text for part in task['needles'])


def audit(a):
    if a.output.exists(): raise ValueError('Fresh audit output required')
    raw = (a.run/'plan.json').read_bytes(); plan = json.loads(raw)
    assert sha(raw) == (a.run/'plan.sha256').read_text().strip()
    assert plan['pack_sha256'] == sha(a.pack.read_bytes()) and plan['tokenizer_sha256'] == sha(a.asset.read_bytes())
    assert plan['needle_plan_sha256'] == sha((a.needles/'plan.json').read_bytes())
    assert plan['behavior_report_sha256'] == sha((a.behavior/'report.json').read_bytes())
    for name, digest in plan['source_sha256'].items(): assert sha((a.run/'sources'/name).read_bytes()) == digest
    for name, digest in plan['input_record_sha256'].items():
        kind, file = name.split('/', 1)
        path = a.needles/'records'/file if kind == 'needle' else a.behavior/'ranks'/file
        assert sha(path.read_bytes()) == digest
    snapshot = read(a.snapshot/'snapshot.json')
    for name, meta in snapshot['files'].items(): assert sha((a.snapshot/name).read_bytes()) == meta['sha256']
    src = a.snapshot/'corpus/test_src'
    source = {p.relative_to(src).as_posix(): p.read_bytes().decode().replace('\r\n', '\n').replace('\r', '\n')
              for p in src.rglob('*.py')}
    con, blocks = load_blocks(a.pack, source)
    from tokenizers import Tokenizer
    codec = Tokenizer.from_file(str(a.asset)); codec.no_padding(); codec.no_truncation()
    @lru_cache(maxsize=4096)
    def count(text): return len(codec.encode(text, add_special_tokens=False))
    corpus = count('\n\n'.join(source[path] for path in sorted(source)))
    examples = {e['id']: e for e in plan['examples']}; assert len(examples) == len(plan['examples'])
    needles = defaultdict(list)
    for task in read(a.needles/'plan.json')['tasks']: needles[task['query']].append(task)
    behavior_queries = {t['task_id']: t['query'] for t in read(a.behavior/'plan.json')['tasks']}
    for e in examples.values():
        if e['workload'] == 'needle': assert e['annotations'] == needles[e['query']]
        else: assert e['annotations'] == [] and e['query'] == behavior_queries[e['id']]
    required = {tid: [definitions(source[path])[name][2] for path, name in refs] for tid, refs in PRIMARY.items()}
    expected = {(e, cap, seed, policy) for e in examples for cap in plan['budgets'] for seed, policy in plan['methods']}
    seen = set(); rows = []; checked_items = 0; replayed = 0; snapshot_records = {}
    files = sorted((a.run/'records').glob('*.json'))
    # Each record is checked independently. Visit related queries together so
    # whole-string counts can be reused; no admission or integrity check is
    # skipped, including the final immutable-directory comparison.
    files.sort(key=lambda path: read(path)['key'])
    if not a.allow_partial: assert len(files) == len(expected)
    try:
        for i, path in enumerate(files):
            record = path.read_bytes(); row = json.loads(record); key = tuple(row['key'])
            assert key in expected and key not in seen; seen.add(key)
            assert path.stem == sha(json.dumps(list(key)).encode())
            snapshot_records[path.name] = sha(record)
            eid, cap, seed, policy = key; example = examples[eid]
            assert row['query'] == example['query'] and row['workload'] == example['workload']
            assert (row['budget'], row['seed'], row['policy']) == (cap, seed, policy)
            pool = expected_pool(example['by_budget'][str(cap)]['ranks'], seed, policy)
            assert row['candidate_ids'] == pool and len(set(pool)) == len(pool)
            body = (a.run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
            assert sha(body) == row['context_sha256']; text = body.decode()
            assert text == '\n\n'.join(e['text'] for e in row['items'])
            assert count(text) == row['selected_tokens'] <= cap
            assert type(row['fallback']) is bool and row['fallback'] == (not row['items'])
            assert row['risk_band'].startswith('uncalibrated:')
            ids = [e['block_id'] for e in row['items']]; assert len(ids) == len(set(ids))
            for item in row['items']:
                b = blocks[item['block_id']]; check_source_item(item, b, b['text'])
                assert item['tokens'] == count(b['text'])
                assert item['score'] == 1/(60+pool.index(item['block_id'])) and item['channels'] == ['lexical']
                checked_items += 1
            if a.replay_order:
                assert replay(pool, blocks, cap, policy, count) == ids, 'admission replay'
                replayed += 1
            if policy == 'rank':
                old = example['by_budget'][str(cap)]['controls'][seed]
                assert (ids, row['selected_tokens'], row['context_sha256'], row['fallback']) == (old['ids'], old['tokens'], old['context_sha256'], old['fallback'])
            hits = {t['task_id']: hit(row['items'], t) for t in example['annotations']}
            assert row['hits'] == hits
            pool_items = [{'path': blocks[bid]['path'], 'span': f"{blocks[bid]['path']}:{blocks[bid]['start_line']}-{blocks[bid]['end_line']}",
                           'text': blocks[bid]['text']} for bid in pool]
            row_out = {'key': list(key), 'workload': example['workload'], 'selected_tokens': count(text),
                       'candidate_count': len(pool), 'item_count': len(ids), 'context_sha256': row['context_sha256'],
                       'corpus_tokens': corpus, 'available_tokens': corpus, 'fallback': row['fallback'], 'hits': hits,
                       'candidate_hits': {t['task_id']: hit(pool_items, t) for t in example['annotations']}}
            if eid in required: row_out['all_primary_definitions_exposed'] = all(t in text for t in required[eid])
            rows.append(row_out)
            if (i+1) % 200 == 0: print({'phase': 'audit', 'checked': i+1, 'records': len(files)}, flush=True)
    finally: con.close()
    assert {p.name: sha(p.read_bytes()) for p in (a.run/'records').glob('*.json')} == snapshot_records, 'records changed during audit'
    groups = defaultdict(list)
    for row in rows: groups[row['workload'], *row['key'][1:]].append(row)
    summaries = []
    for (workload, cap, seed, policy), group in sorted(groups.items()):
        total_queries = sum(e['workload'] == workload for e in examples.values())
        annotations = [v for row in group for v in row['hits'].values()]
        summaries.append({'workload': workload, 'budget': cap, 'seed': seed, 'policy': policy,
                          'queries': len(group), 'planned_queries': total_queries, 'complete': len(group) == total_queries,
                          'annotated_hits': sum(annotations), 'annotations': len(annotations),
                          'all_primary_definitions_exposed': sum(r.get('all_primary_definitions_exposed', False) for r in group) if workload == 'behavior' else None,
                          'mean_selected_tokens': statistics.mean(r['selected_tokens'] for r in group),
                          'mean_candidates': statistics.mean(r['candidate_count'] for r in group),
                          'fallbacks': sum(r['fallback'] for r in group)})
    result = {'status': 'AUDITED' if seen == expected else 'PARTIAL_AUDIT', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'plan_sha256': sha(raw), 'auditor_sha256': sha(Path(__file__).read_bytes()), 'selections': len(seen),
              'planned_selections': len(expected), 'independently_replayed_orders': replayed,
              'checked_source_items': checked_items, 'corpus_tokens_per_request': corpus,
              'record_visit_order': 'query, budget, seed, policy', 'count_cache_entries': 4096,
              'record_sha256': snapshot_records, 'summaries': summaries, 'rows': rows,
              'limits': ['No answer-quality or sufficiency claim from source retention/exposure',
                         'Source-informed development tasks; no sealed evaluation',
                         'Partial cohorts must not be ranked as completed experiments',
                         'Ordering replay is explicit; output checks alone do not prove the decision policy',
                         'No target prompt or live call is made by this auditor']}
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({k: result[k] for k in ('status', 'selections', 'independently_replayed_orders', 'checked_source_items')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'pack', 'asset', 'needles', 'behavior', 'snapshot', 'output'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--allow-partial', action='store_true'); p.add_argument('--replay-order', action='store_true')
    audit(p.parse_args())

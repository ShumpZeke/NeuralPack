"""Audit source identity, exact budgets and packing independently of guards.

This does not certify a semantic interpretation of natural-language intent.
Guard semantics are limited surface rules covered by separate regression tests.
"""
import argparse
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from benchmarks.library_selection_audit import load_blocks, check_source_item
from benchmarks.library_failure_analysis import PRIMARY, definitions
from benchmarks.packing_audit import replay, hit

sha = lambda b: hashlib.sha256(b).hexdigest()
read = lambda p: json.loads(p.read_bytes())


def audit(a):
    if a.output.exists(): raise ValueError('Fresh intent audit required')
    raw = (a.run/'plan.json').read_bytes(); plan = json.loads(raw)
    assert sha(raw) == (a.run/'plan.sha256').read_text().strip()
    assert sha(a.pack.read_bytes()) == plan['pack_sha256']
    assert sha(a.asset.read_bytes()) == plan['tokenizer_sha256']
    parent_raw = (a.run/'parent-plan.json').read_bytes()
    assert sha(parent_raw) == plan['parent_plan_sha256']
    parent = {e['id']: e for e in json.loads(parent_raw)['examples']}
    for name, digest in plan['source_sha256'].items(): assert sha((a.run/'sources'/name).read_bytes()) == digest
    assert sha((a.snapshot/'snapshot.json').read_bytes()) == plan['snapshot_sha256']
    for name, info in read(a.snapshot/'snapshot.json')['files'].items(): assert sha((a.snapshot/name).read_bytes()) == info['sha256']
    src = a.snapshot/'corpus/test_src'
    source = {p.relative_to(src).as_posix(): p.read_bytes().decode().replace('\r\n', '\n').replace('\r', '\n') for p in src.rglob('*.py')}
    con, blocks = load_blocks(a.pack, source)
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(a.asset)); tokenizer.no_padding(); tokenizer.no_truncation()
    @lru_cache(maxsize=512)
    def count(text): return len(tokenizer.encode(text, add_special_tokens=False))
    corpus = count('\n\n'.join(source[p] for p in sorted(source)))
    required = {tid: [definitions(source[path])[name][2] for path, name in refs] for tid, refs in PRIMARY.items()}
    seen = {}; results = []; items_checked = 0; orders = 0; unique_rows = 0
    try:
        for index, e in enumerate(plan['examples']):
            prior = parent[e['id']]
            assert all(e[k] == prior[k] for k in ('id', 'query', 'workload', 'annotations'))
            assert e['original_plan']['raw'] == e['query']
            replays = {}
            for cap in plan['budgets']:
                assert [b for b, _ in e['ranks']['original']] == prior['by_budget'][str(cap)]['ranks']['crisp']
                assert e['controls'][str(cap)] == prior['by_budget'][str(cap)]['controls']['crisp']
                for mode in plan['modes']:
                    key = [e['id'], cap, mode]; name = sha(json.dumps(key).encode())+'.json'
                    data = (a.run/'records'/name).read_bytes(); row = json.loads(data)
                    assert name not in seen; seen[name] = sha(data)
                    assert row['key'] == key and row['query'] == e['query']
                    assert row['budget'] == cap and row['mode'] == mode
                    pool = [bid for bid, _ in e['ranks'][mode]]; assert len(pool) == len(set(pool))
                    signature = (cap, tuple(pool))
                    body = (a.run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
                    assert sha(body) == row['context_sha256']; text = body.decode()
                    assert text == '\n\n'.join(i['text'] for i in row['items'])
                    assert count(text) == row['selected_tokens'] <= cap
                    assert type(row['fallback']) is bool and row['fallback'] == (not row['items'])
                    assert row['risk_band'].startswith('uncalibrated:')
                    ids = [i['block_id'] for i in row['items']]; assert len(ids) == len(set(ids))
                    for item in row['items']:
                        b = blocks[item['block_id']]; check_source_item(item, b, b['text'])
                        assert item['tokens'] == count(b['text'])
                        assert item['score'] == 1/(60+pool.index(item['block_id'])) and item['channels'] == ['lexical']
                        items_checked += 1
                    if signature not in replays:
                        replays[signature] = replay(pool, blocks, cap, 'rank', count); orders += 1
                    assert ids == replays[signature]
                    if mode == 'original':
                        c = e['controls'][str(cap)]
                        assert (ids, row['context_sha256'], row['selected_tokens'], row['fallback']) == (c['ids'], c['context_sha256'], c['tokens'], c['fallback'])
                    if row['equivalent_local_record'] is not None:
                        origin_name = row['equivalent_local_record']; assert origin_name in seen
                        origin = read(a.run/'records'/origin_name)
                        assert origin['equivalent_local_record'] is None
                        excluded = {'mode', 'key', 'equivalent_local_record'}
                        assert {k: v for k, v in row.items() if k not in excluded} == {k: v for k, v in origin.items() if k not in excluded}
                    else: unique_rows += 1
                    out = {'key': key, 'workload': e['workload'], 'selected_tokens': count(text),
                           'corpus_tokens': corpus, 'available_tokens': corpus, 'fallback': row['fallback'],
                           'hits': {t['task_id']: hit(row['items'], t) for t in e['annotations']}}
                    if e['id'] in required: out['all_primary_definitions_exposed'] = all(t in text for t in required[e['id']])
                    results.append(out)
            if (index+1) % 30 == 0: print({'phase': 'audit', 'queries': index+1, 'records': len(results)}, flush=True)
    finally: con.close()
    assert {p.name: sha(p.read_bytes()) for p in (a.run/'records').glob('*.json')} == seen
    groups = defaultdict(list)
    for row in results: groups[row['workload'], row['key'][1], row['key'][2]].append(row)
    summaries = []
    for (workload, cap, mode), group in sorted(groups.items()):
        annotations = [v for row in group for v in row['hits'].values()]
        summaries.append({'workload': workload, 'budget': cap, 'mode': mode, 'queries': len(group),
                          'annotated_hits': sum(annotations), 'annotations': len(annotations),
                          'all_primary_definitions_exposed': sum(r.get('all_primary_definitions_exposed', False) for r in group) if workload == 'behavior' else None,
                          'mean_selected_tokens': sum(r['selected_tokens'] for r in group)/len(group)})
    result = {'status': 'AUDITED', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'plan_sha256': sha(raw), 'auditor_sha256': sha(Path(__file__).read_bytes()),
              'observations': len(results), 'unique_local_selections': unique_rows,
              'independently_replayed_orders': orders, 'checked_source_items': items_checked,
              'record_sha256': seen, 'rows': results, 'summaries': summaries,
              'limits': ['No semantic-intent correctness certificate, answer accuracy or sufficiency claim',
                         'Source-informed questions; no sealed generalization test',
                         'Original frozen ranks and controls are checked, not independently reimplemented BM25',
                         'Different modes with identical query/rank/budget reuse the same independent order replay']}
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({k: result[k] for k in ('status', 'observations', 'unique_local_selections', 'independently_replayed_orders', 'checked_source_items')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'pack', 'asset', 'snapshot', 'output'): p.add_argument('--'+name, type=Path, required=True)
    audit(p.parse_args())

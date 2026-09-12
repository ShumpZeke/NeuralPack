"""Freeze intent-only ablations, then run exact-budget public selection.

The rank control must reproduce the already frozen packing plan. Identical
query/rank/budget selections share an actual local computation, explicitly
recorded. This is an evidence diagnostic, not a query latency benchmark.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

from benchmarks.structural_intent import MODES, guarded_plan
from npk.pack import LocalTokenizer, PackSelector
from npk.pack.format import load_blocks, open_pack

sha = lambda b: hashlib.sha256(b).hexdigest()
read = lambda p: json.loads(p.read_bytes())


def save(path, value):
    tmp = path.with_suffix(path.suffix+'.pending')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(path)


def prepare(a):
    if a.output.exists(): raise ValueError('Fresh intent study required')
    parent_bytes = (a.parent/'plan.json').read_bytes(); parent = json.loads(parent_bytes)
    assert sha(parent_bytes) == (a.parent/'plan.sha256').read_text().strip()
    seed = read(a.seed/'plan.json')
    assert sha(a.side.read_bytes()) == seed['side_sha256']
    assert sha(a.pack.read_bytes()) == parent['pack_sha256'] == seed['pack_sha256']
    frozen = read(a.snapshot/'snapshot.json')
    for name, info in frozen['files'].items(): assert sha((a.snapshot/name).read_bytes()) == info['sha256']
    sys.path.insert(0, str(a.snapshot.resolve()))
    from crisp.score import Scorer
    con = sqlite3.connect(a.side.resolve().as_uri()+'?mode=ro', uri=True)
    examples = []
    try:
        scorer = Scorer(con)
        for e in parent['examples']:
            qp = scorer.plan(e['query']); ranks = {}; decisions = {}
            for mode in MODES:
                guarded, decision = guarded_plan(qp, mode)
                assert guarded.raw == e['query'] and guarded.facets == qp.facets
                ranks[mode] = scorer.candidates(guarded, 160)
                decisions[mode] = asdict(decision)
            for cap in parent['budgets']:
                assert [bid for bid, _ in ranks['original']] == e['by_budget'][str(cap)]['ranks']['crisp']
            examples.append({'id': e['id'], 'query': e['query'], 'workload': e['workload'],
                             'annotations': e['annotations'], 'original_plan': asdict(qp),
                             'ranks': ranks, 'decisions': decisions,
                             'controls': {str(cap): e['by_budget'][str(cap)]['controls']['crisp'] for cap in parent['budgets']}})
    finally: con.close()
    repo = Path(__file__).resolve().parents[1]
    paths = [*sorted((repo/'npk').rglob('*.py')), Path(__file__).resolve(), repo/'benchmarks/structural_intent.py']
    sources = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in paths}
    plan = {'parent_plan_sha256': sha(parent_bytes), 'seed_plan_sha256': sha((a.seed/'plan.json').read_bytes()),
            'side_sha256': seed['side_sha256'], 'pack_sha256': parent['pack_sha256'],
            'tokenizer_sha256': parent['tokenizer_sha256'], 'modes': MODES, 'budgets': parent['budgets'],
            'snapshot_sha256': sha((a.snapshot/'snapshot.json').read_bytes()), 'source_sha256': sources,
            'examples': examples, 'evidence_mode': 'LOCAL', 'generative_calls': 0,
            'limits': ['Inspected public-source questions; no sealed generalization or answer-accuracy claim',
                       'Only inferred raises bonuses change; original lexical facets and partial-identifier behavior remain',
                       'Conservative global negation/catching guard can suppress valid positive clauses',
                       'No relation bonus is proof of sufficient evidence or calibrated probability',
                       'Identical query/rank/budget cells reuse explicitly identified local selections',
                       'Context caps exclude the original question and caller wrappers; exact pinned NIM tokenizer',
                       'No latency or economic claim from this cached differential study']}
    a.output.mkdir(parents=True)
    for name in ('sources', 'records', 'contexts'): (a.output/name).mkdir()
    for name in sources:
        p = a.output/'sources'/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes((repo/name).read_bytes())
    (a.output/'parent-plan.json').write_bytes(parent_bytes)
    save(a.output/'plan.json', plan)
    (a.output/'plan.sha256').write_text(sha((a.output/'plan.json').read_bytes()), encoding='ascii')
    print({'status': 'PREPARED', 'queries': len(examples), 'planned_cells': len(examples)*len(MODES)*len(plan['budgets']),
           'changed_rank_queries': {mode: sum(e['ranks'][mode] != e['ranks']['original'] for e in examples) for mode in MODES},
           'plan_sha256': sha((a.output/'plan.json').read_bytes())}, flush=True)


def run(a):
    plan = read(a.output/'plan.json'); repo = Path(__file__).resolve().parents[1]
    assert sha((a.output/'plan.json').read_bytes()) == (a.output/'plan.sha256').read_text().strip()
    for name, digest in plan['source_sha256'].items(): assert sha((repo/name).read_bytes()) == digest
    assert sha(a.pack.read_bytes()) == plan['pack_sha256'] and sha(a.asset.read_bytes()) == plan['tokenizer_sha256']
    with open_pack(a.pack) as con: blocks = {b.id: b for b in load_blocks(con)}
    codec = LocalTokenizer(a.asset, cache_bytes=16*1024*1024)
    selector = PackSelector(a.pack, tokenizer=codec, candidate_limit=160)
    total = 0; unique_calls = 0
    for example in plan['examples']:
        reuse = {}
        for cap in plan['budgets']:
            for mode in plan['modes']:
                pool = [bid for bid, _ in example['ranks'][mode]]
                key = [example['id'], cap, mode]; filename = sha(json.dumps(key).encode())+'.json'
                dest = a.output/'records'/filename; signature = (cap, tuple(pool))
                if dest.exists():
                    row = read(dest); assert row['key'] == key
                    assert sha((a.output/'contexts'/(row['context_sha256']+'.txt')).read_bytes()) == row['context_sha256']
                elif signature in reuse:
                    prior_name, prior = reuse[signature]
                    row = {**prior, 'key': key, 'mode': mode, 'equivalent_local_record': prior_name}
                    save(dest, row)
                else:
                    def seed(con, query, limit):
                        assert query == example['query'] and limit == 160
                        return pool
                    with patch('npk.pack.select._lexical_channel', seed), patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
                        selected = selector.select(example['query'], budget_tokens=cap, allow_escalation=False)
                    context = selected.context_text(); items = [asdict(e) for e in selected.evidence]
                    assert selected.query == example['query'] and not selected.used_generative_llm
                    assert codec.count(context) == selected.total_tokens <= cap
                    assert selected.seed_failed == (not items)
                    for e in selected.evidence:
                        b = blocks[e.block_id]; assert (e.path, e.span, e.name, e.text) == (b.path, b.span, b.name, b.text)
                    digest = sha(context.encode()); (a.output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
                    row = {'key': key, 'query': example['query'], 'budget': cap, 'mode': mode,
                           'context_sha256': digest, 'selected_tokens': selected.total_tokens,
                           'items': items, 'fallback': selected.seed_failed, 'risk_band': selected.risk_band,
                           'equivalent_local_record': None}
                    save(dest, row)
                if mode == 'original':
                    ctrl = example['controls'][str(cap)]
                    assert ([e['block_id'] for e in row['items']], row['context_sha256'], row['selected_tokens'], row['fallback']) == (ctrl['ids'], ctrl['context_sha256'], ctrl['tokens'], ctrl['fallback'])
                if row['equivalent_local_record'] is None: unique_calls += 1
                reuse.setdefault(signature, (filename, row)); total += 1
        if total % 120 == 0: print({'phase': 'selection', 'observations': total, 'unique_local_selections': unique_calls}, flush=True)
    for name, digest in plan['source_sha256'].items(): assert sha((repo/name).read_bytes()) == digest
    state = {'status': 'COMPLETE', 'observations': total, 'unique_local_selections': unique_calls, 'generative_calls': 0}
    save(a.output/'state.json', state); print(state, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('phase', choices=('prepare', 'run'))
    for name in ('output', 'pack', 'asset'): p.add_argument('--'+name, type=Path, required=True)
    for name in ('parent', 'seed', 'side', 'snapshot'): p.add_argument('--'+name, type=Path)
    a = p.parse_args(); (prepare if a.phase == 'prepare' else run)(a)

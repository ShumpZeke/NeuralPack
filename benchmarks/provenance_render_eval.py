"""Matched-budget source-identity rendering with frozen, audited seed rankings."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import time
from unittest.mock import patch

from npk.pack import LocalTokenizer, PackSelector
from npk.pack.format import load_blocks, open_pack
from benchmarks.provenance_renderer import ProvenanceSelector, render


SEEDS = {'npk_bm25_60': ('body', 60), 'fields160': ('fields', 160), 'crisp_shared_raises160': ('crisp', 160)}
BUDGETS = (512, 2048, 8192)
def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def save(path, value):
    pending = path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8'); pending.replace(path)


def run(a):
    if a.output.exists(): raise ValueError('Fresh rendering experiment required')
    repo = Path(__file__).resolve().parents[1]
    baseline = read(a.baseline/'report.json'); source_plan = read(a.baseline/'plan.json')
    assert baseline['status'] == 'COMPLETE'
    assert baseline['plan_sha256'] == sha((a.baseline/'plan.json').read_bytes())
    assert source_plan['pack_sha256'] == sha(a.pack.read_bytes())
    assert source_plan['tokenizer_sha256'] == sha(a.asset.read_bytes())
    assert source_plan['tasks_sha256'] == sha(a.tasks.read_bytes())
    tasks = read(a.tasks)['tasks']
    original = {(r['task_id'], r['arm'], r['budget']): r for r in baseline['rows']}
    paths = [*sorted((repo/'npk').rglob('*.py')), Path(__file__), repo/'benchmarks/provenance_renderer.py']
    sources = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in paths}
    rankings = {}
    for task in tasks:
        path = a.baseline/'ranks'/(task['task_id']+'.json'); rank = read(path)
        assert rank['query'] == task['query']
        for seed in SEEDS:
            assert original[task['task_id'], seed, 2048]['ranking_sha256'] == sha(path.read_bytes())
        rankings[task['task_id']] = rank
    plan = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'seeds': SEEDS, 'budgets': BUDGETS,
            'formats': ['raw', 'source_headers'], 'seed': 2916, 'tasks': tasks,
            'source_sha256': sources, 'pack_sha256': sha(a.pack.read_bytes()),
            'tokenizer_sha256': sha(a.asset.read_bytes()), 'task_plan_sha256': sha(a.tasks.read_bytes()),
            'parent_selection_report_sha256': sha((a.baseline/'report.json').read_bytes()),
            'hypothesis': 'Preserving qualified source identity in the consumer text improves interpretability at an explicit token cost',
            'limits': ['Frozen audited rankings isolate rendering and admission; no seed lookup latency claim',
                       'Source-informed development questions and one tokenizer; not sealed validation',
                       'Headers preserve location and qualified names, not all lexical environment or dynamic state',
                       'Raw competent baselines use the full same budget cap',
                       'Additional paired-raw controls use exactly the header-selected bodies, explicitly leaving their saved header tokens unused',
                       'Selection timings use a shared count cache and are diagnostic, not clean query latency']}
    a.output.mkdir(parents=True)
    for name in ('contexts', 'records', 'ranks'): (a.output/name).mkdir()
    save(a.output/'plan.json', plan)
    for name in sources:
        dest = a.output/'source'/name; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes((repo/name).read_bytes())
    with open_pack(a.pack) as con: blocks = {b.id: b for b in load_blocks(con)}
    counter = LocalTokenizer(a.asset, cache_bytes=16*1024*1024)
    rows = []
    for qi, task in enumerate(tasks):
        ranking = rankings[task['task_id']]; save(a.output/'ranks'/(task['task_id']+'.json'), ranking)
        cells = [(seed, fmt, cap) for seed in SEEDS for fmt in plan['formats'] for cap in BUDGETS]
        random.Random(plan['seed']+qi).shuffle(cells)
        for seed, fmt, budget in cells:
            channel, limit = SEEDS[seed]; ordered = ranking['ranks'][channel][:limit]
            def lexical(con, query, count):
                assert query == task['query'] and count == limit
                return ordered
            cls = PackSelector if fmt == 'raw' else ProvenanceSelector
            selector = cls(a.pack, tokenizer=counter, candidate_limit=limit)
            started = time.perf_counter()
            with patch('socket.socket.connect', side_effect=AssertionError('Renderer attempted a network call')), patch('npk.pack.select._lexical_channel', lexical):
                selected = selector.select(task['query'], budget_tokens=budget, allow_escalation=False)
            latency = 1000*(time.perf_counter()-started)
            context = selected.context_text(); raw = '\n\n'.join(e.text for e in selected.evidence)
            assert selected.query == task['query'] and not selected.used_generative_llm
            assert counter.count(context) == selected.total_tokens <= budget
            assert bool(selected.evidence) != selected.seed_failed
            for item in selected.evidence:
                block = blocks[item.block_id]
                assert (item.path, item.span, item.name, item.text) == (block.path, block.span, block.name, block.text)
            if fmt == 'raw':
                assert sha(context.encode()) == original[task['task_id'], seed, budget]['context_sha256']
                assert [e.block_id for e in selected.evidence] == [e['block_id'] for e in original[task['task_id'], seed, budget]['items']]
            else: assert context == render(selected.evidence)
            digest = sha(context.encode()); raw_digest = sha(raw.encode())
            (a.output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
            (a.output/'contexts'/(raw_digest+'.txt')).write_bytes(raw.encode())
            raw_tokens = counter.count(raw)
            assert raw_tokens <= budget, 'Paired raw control exceeded the common cap'
            row = {'task_id': task['task_id'], 'query': task['query'], 'seed': seed, 'format': fmt,
                   'budget': budget, 'selected_tokens': selected.total_tokens, 'raw_body_tokens': raw_tokens,
                   'net_render_token_delta': selected.total_tokens-raw_tokens, 'context_sha256': digest,
                   'paired_raw_sha256': raw_digest, 'items': [asdict(e) for e in selected.evidence],
                   'fallback_required': selected.seed_failed, 'risk_band': selected.risk_band,
                   'notes': selected.notes, 'diagnostic_selection_ms': latency}
            save(a.output/'records'/(sha(json.dumps([task['task_id'], seed, fmt, budget]).encode())+'.json'), row)
            rows.append(row)
        print({'phase': 'selection', 'task': task['task_id'], 'rows': len(rows)}, flush=True)
    assert len(rows) == len(tasks)*len(SEEDS)*2*len(BUDGETS)
    for name, digest in sources.items(): assert sha((repo/name).read_bytes()) == digest
    save(a.output/'report.json', {'status': 'COMPLETE', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
                                 'plan_sha256': sha((a.output/'plan.json').read_bytes()), 'rows': rows})
    print({'status': 'COMPLETE', 'selections': len(rows)}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('pack', 'asset', 'tasks', 'baseline', 'output'): p.add_argument('--'+name, type=Path, required=True)
    run(p.parse_args())

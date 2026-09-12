"""Frozen, zero-generation behavior selections with actual local neural baselines.

Research channels feed the public PackSelector. Models are optional research
dependencies, not runtime requirements. Precomputed document and query vectors
are separately timed; reuse across budget cells is not free query encoding.
"""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import time
from unittest.mock import patch

from benchmarks import seed_metadata
from npk.pack import LocalTokenizer, PackSelector
from npk.pack.format import load_blocks, open_pack
from npk.pack.select import RRF_K, _lexical_channel, _symbol_channel

ARMS = ('npk_bm25_60', 'fields160', 'crisp_shared_raises160',
        'hybrid_minilm_body160', 'hybrid_minilm_fields160',
        'hybrid_qwen_fields160', 'rerank_qwen_fields160')
BUDGETS = (512, 2048, 8192)


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def save(path, value):
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(path)


def fuse(channels):
    """Public selector's rank-zero RRF and insertion-order tie policy."""
    scores = {}
    for ids in channels:
        for rank, bid in enumerate(ids):
            scores[bid] = scores.get(bid, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda bid: -scores[bid])


def load_encoder(root, pack_digest, tasks_digest, blocks, tasks):
    import numpy as np
    plan = read(root / 'plan.json'); report = read(root / 'report.json')
    assert report['status'] == 'COMPLETE'
    assert report['plan_sha256'] == sha((root / 'plan.json').read_bytes())
    assert plan['pack_sha256'] == pack_digest and plan['task_plan_sha256'] == tasks_digest
    assert plan['blocks'] == [{'id': b.id, 'path': b.path, 'span': b.span, 'name': b.name,
                              'sha256': sha(b.text.encode())} for b in blocks]
    assert plan['queries'] == [{'task_id': t['task_id'], 'query': t['query']} for t in tasks]
    arrays = {}
    for name, rows in [('documents', len(blocks)), ('queries', len(tasks))]:
        path = root / (name + '.npy')
        assert sha(path.read_bytes()) == report['matrix_files'][path.name]['sha256']
        values = np.load(path, allow_pickle=False)
        assert values.ndim == 2 and values.shape[0] == rows and np.isfinite(values).all()
        assert np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-4)
        arrays[name] = values
    assert arrays['documents'].shape[1] == arrays['queries'].shape[1]
    return plan, report, arrays


def run(a):
    import numpy as np
    import torch
    repo = Path(__file__).resolve().parents[1]
    if a.output.exists() and not a.resume: raise ValueError('Fresh selection output required')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    torch.set_num_threads(2)
    frozen = read(a.snapshot / 'snapshot.json')
    for name, info in frozen['files'].items():
        assert sha((a.snapshot / name).read_bytes()) == info['sha256']
    sys.path.insert(0, str(a.snapshot.resolve()))
    from crisp.score import Scorer
    from benchmarks.repository_rerank import LocalReranker, MODEL_ID, REVISION
    tasks = read(a.tasks)['tasks']
    pack_digest = sha(a.pack.read_bytes()); tasks_digest = sha(a.tasks.read_bytes())
    with open_pack(a.pack) as parent:
        blocks = sorted(load_blocks(parent), key=lambda b: (b.path, b.ordinal))
    by_id = {b.id: b for b in blocks}; ids = [b.id for b in blocks]
    encoders = {name: load_encoder(root, pack_digest, tasks_digest, blocks, tasks)
                for name, root in [('minilm', a.minilm), ('qwen', a.qwen)]}
    paths = [*sorted((repo / 'npk').rglob('*.py')), Path(__file__),
             repo / 'benchmarks/seed_metadata.py', repo / 'benchmarks/repository_rerank.py']
    code = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in paths}
    model_root = (repo / 'experiments/models/hf_cache/models--cross-encoder--ms-marco-MiniLM-L-6-v2'
                  / 'snapshots' / REVISION)
    # Record actual installed model/tokenizer bytes as well as the requested revision.
    model_files = {p.relative_to(model_root).as_posix(): sha(p.read_bytes())
                   for p in sorted(model_root.rglob('*')) if p.is_file()}
    assert 'model.safetensors' in model_files
    plan = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'pack_sha256': pack_digest,
            'tasks_sha256': tasks_digest, 'snapshot_sha256': sha((a.snapshot / 'snapshot.json').read_bytes()),
            'side_sha256': sha(a.side.read_bytes()), 'tokenizer_sha256': sha(a.asset.read_bytes()),
            'arms': ARMS, 'budgets': BUDGETS, 'candidate_limit': 160, 'tasks': tasks,
            'encoder_reports': {name: sha((root / 'report.json').read_bytes())
                                for name, root in [('minilm', a.minilm), ('qwen', a.qwen)]},
            'reranker': {'model': MODEL_ID, 'revision': REVISION, 'files_sha256': model_files,
                         'device': 'cpu', 'batch_size': 16, 'max_length': 512, 'pool_limit': 160},
            'code_sha256': code, 'python': sys.version, 'sqlite': sqlite3.sqlite_version,
            'versions': {n: importlib.metadata.version(n) for n in ('torch', 'numpy', 'transformers', 'tokenizers')},
            'limits': ['Source-informed developer behavior tasks; no held-out or accuracy claim from selection',
                       'Public exact-budget packing; research ranking channels are explicit substitutions',
                       'Hybrid uses symbol/lexical/dense RRF; no absolute dense cutoff, no sufficiency claim',
                       'Reranker sees top 160 fused Qwen/fields/symbol candidates, unmodified body text',
                       'No graph, conflict deletion, or adaptive widening in this fixed candidate comparison',
                       'Reused query vectors carry separately measured encoding cost, excluding model loading',
                       'Selection timings include shared token caches and are diagnostic, not clean latency',
                       'No incremental vector or auxiliary-index update is implemented']}
    # JSON normalization makes resume compare the exact declared structure.
    plan = json.loads(json.dumps(plan))
    a.output.mkdir(parents=True, exist_ok=a.resume)
    if a.resume: assert read(a.output / 'plan.json') == plan
    else:
        save(a.output / 'plan.json', plan)
        (a.output / 'sources.json.gz').write_bytes(gzip.compress(
            json.dumps({p: (repo / p).read_text(encoding='utf-8') for p in code}).encode(), mtime=0))
    for name in ('records', 'contexts', 'ranks'): (a.output / name).mkdir(exist_ok=True)
    counter = LocalTokenizer(a.asset, cache_bytes=16*1024*1024)
    side = sqlite3.connect(a.side.resolve().as_uri() + '?mode=ro', uri=True); side.row_factory = sqlite3.Row
    with open_pack(a.pack) as parent: seed_metadata.require_parent(side, parent)
    scorer = Scorer(side)
    with patch('socket.socket.connect', side_effect=AssertionError('LOCAL selector attempted network')):
        start = time.perf_counter(); cpu = time.process_time()
        reranker = LocalReranker(repo / 'experiments/models/hf_cache')
        assert reranker.model.config._commit_hash == REVISION
        load = {'wall_ms': 1000*(time.perf_counter()-start), 'cpu_ms': 1000*(time.process_time()-cpu),
                'num_hidden_layers': reranker.model.config.num_hidden_layers, 'torch_threads': torch.get_num_threads()}
        if not (a.output / 'reranker-load.json').exists(): save(a.output / 'reranker-load.json', load)
        for qi, task in enumerate(tasks):
            query = task['query']; rank_file = a.output / 'ranks' / (task['task_id'] + '.json')
            if rank_file.exists(): ranking = read(rank_file)
            else:
                rank = {}; metrics = {}
                with open_pack(a.pack) as parent:
                    for name, action in [('body', lambda: _lexical_channel(parent, query, 160)),
                                         ('symbol', lambda: _symbol_channel(parent, query, 160)),
                                         ('fields', lambda: seed_metadata.field_rank(side, query, 160, mode='fields')),
                                         ('crisp', lambda: [bid for bid, score in scorer.candidates(scorer.plan(query), 160)])]:
                        start = time.perf_counter(); rank[name] = action()
                        metrics[name] = {'lookup_wall_ms': 1000*(time.perf_counter()-start)}
                for name, (_, report, arrays) in encoders.items():
                    start = time.perf_counter(); similarities = arrays['documents'] @ arrays['queries'][qi]
                    ordered = sorted(range(len(ids)), key=lambda i: (-float(similarities[i]), i))[:160]
                    rank[name] = [ids[i] for i in ordered]
                    metrics[name] = {'lookup_wall_ms': 1000*(time.perf_counter()-start),
                                     'similarities': [float(similarities[i]) for i in ordered],
                                     'query_encoding': report['query_metrics'][qi]}
                    assert metrics[name]['query_encoding']['task_id'] == task['task_id']
                pool = fuse([rank['symbol'], rank['fields'], rank['qwen']])[:160]
                start = time.perf_counter(); cpu = time.process_time()
                ranked, scores = reranker.rank(query, [by_id[bid] for bid in pool])
                rank['rerank'] = [b.id for b in ranked]
                metrics['rerank'] = {'wall_ms': 1000*(time.perf_counter()-start),
                                     'cpu_ms': 1000*(time.process_time()-cpu), 'pool': pool, 'scores': scores}
                ranking = {'task_id': task['task_id'], 'query': query, 'ranks': rank, 'metrics': metrics}
                save(rank_file, ranking)
            assert ranking['query'] == query and ranking['task_id'] == task['task_id']
            ranks = ranking['ranks']
            cells = [(arm, budget) for arm in ARMS for budget in BUDGETS]
            random.Random(2910 + qi).shuffle(cells)
            for arm, budget in cells:
                dest = a.output / 'records' / (sha(json.dumps([task['task_id'], arm, budget]).encode()) + '.json')
                if dest.exists(): continue
                hybrid = arm.startswith('hybrid_')
                lex_name = 'body' if arm in ('npk_bm25_60', 'hybrid_minilm_body160') else 'fields'
                if arm == 'crisp_shared_raises160': lex_name = 'crisp'
                if arm == 'rerank_qwen_fields160': lex_name = 'rerank'
                dense_name = 'qwen' if 'qwen' in arm else 'minilm'
                limit = 60 if arm == 'npk_bm25_60' else 160
                selector = PackSelector(a.pack, tokenizer=counter, candidate_limit=limit,
                                        retrieval='hybrid' if hybrid else 'lexical', dense_floor=-1.0)
                def lex(con, q, k):
                    assert q == query and k == limit
                    return ranks[lex_name][:k]
                def dense(con, q, k, manifest):
                    assert q == query and k == limit
                    return ranks[dense_name][:k], ranking['metrics'][dense_name]['similarities'][0]
                start = time.perf_counter()
                with patch('npk.pack.select._lexical_channel', lex), patch('npk.pack.select._embedding_channel', dense):
                    selected = selector.select(query, budget_tokens=budget, allow_escalation=False)
                wall = 1000*(time.perf_counter()-start)
                context = selected.context_text(); digest = sha(context.encode())
                assert selected.query == query and not selected.used_generative_llm
                assert counter.count(context) == selected.total_tokens <= budget
                assert bool(selected.evidence) != selected.seed_failed
                (a.output / 'contexts' / (digest + '.txt')).write_bytes(context.encode())
                save(dest, {'task_id': task['task_id'], 'query': query, 'arm': arm, 'budget': budget,
                            'selected_tokens': selected.total_tokens, 'context_sha256': digest,
                            'items': [asdict(e) for e in selected.evidence], 'fallback_required': selected.seed_failed,
                            'risk_band': selected.risk_band, 'notes': selected.notes, 'diagnostic_selection_ms': wall,
                            'ranking_file': rank_file.name, 'ranking_sha256': sha(rank_file.read_bytes()),
                            'lexical_ranking': lex_name, 'dense_ranking': dense_name if hybrid else None})
            print({'phase': 'behavior_selection', 'task': task['task_id'],
                   'records': len(list((a.output / 'records').glob('*.json')))}, flush=True)
    side.close()
    assert all(sha((repo / p).read_bytes()) == digest for p, digest in code.items())
    rows = [read(p) for p in sorted((a.output / 'records').glob('*.json'))]
    assert len(rows) == len(tasks)*len(ARMS)*len(BUDGETS)
    save(a.output / 'report.json', {'status': 'COMPLETE', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
                                   'plan_sha256': sha((a.output / 'plan.json').read_bytes()), 'rows': rows})
    print({'status': 'COMPLETE', 'selections': len(rows)}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('pack', 'tasks', 'snapshot', 'side', 'asset', 'minilm', 'qwen', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    run(p.parse_args())

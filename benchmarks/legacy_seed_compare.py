"""Paired legacy seed diagnostics using frozen source and real LOCAL encoder scores.

This is not an answer-quality benchmark. All selections share blocks and the
legacy chars/3.8 estimator; old cap violations are reported, never rewarded.
Encoder scores are computed once and replayed identically into both snapshots.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import zipfile


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p, value): p.write_text(json.dumps(value, indent=2), encoding='utf-8')


def worker(a):
    sys.path.insert(0, str(a.package.resolve()))
    import socket
    def denied(*args, **kwargs): raise AssertionError('LOCAL test attempted network')
    socket.socket.connect = denied
    from npk.context.info_gain import InformationGainSelector
    from npk.context.embedding import get_backend
    from npk.context.analyzer import estimate_tokens
    data = json.loads((a.root/'inputs.json').read_text())
    scores = json.loads((a.root/'dense.json').read_text())
    blocks = data['blocks']; rows = []
    for task in data['tasks']:
        dense = scores['scores'][task['id']]
        def replay(texts, query):
            assert texts == [b['text'] for b in blocks] and query == task['question']
            return dense
        get_backend().score_blocks = replay
        for mode in ('default', 'lexical', 'embedding'):
            opts = {} if mode == 'default' else {'enable_escalation': mode == 'embedding'}
            for budget in data['budgets']:
                start = time.perf_counter()
                out = InformationGainSelector(**opts).select(blocks, task['question'], {}, budget)
                wall = (time.perf_counter()-start)*1000
                kept = [blocks[i] for i in out.kept_indices]
                text = '\n\n'.join(b['text'] for b in kept)
                covered = {}
                for b in kept:
                    covered.setdefault(b['path'], set()).update(range(b['start'], b['end']+1))
                hits = [set(range(r['span'][0], r['span'][1]+1)) <= covered.get(r['path'], set()) for r in task['required']]
                within = estimate_tokens(text) <= budget
                row = {'arm': a.arm, 'mode': mode, 'task': task['id'], 'cohort': task['cohort'], 'budget': budget,
                       'available_tokens': estimate_tokens('\n\n'.join(b['text'] for b in blocks)),
                       'corpus_tokens': sum(estimate_tokens(b['text']) for b in blocks),
                       'selected_tokens': estimate_tokens(text), 'reported_tokens': out.selected_tokens,
                       'within_budget': within, 'seed_failed': out.seed_failed,
                       'selected_indices': out.kept_indices, 'context_sha256': hashlib.sha256(text.encode()).hexdigest(),
                       'required_span_fraction': statistics.mean(hits), 'all_required_spans': all(hits),
                       'eligible_required_span_fraction': statistics.mean(hits) if within and not out.seed_failed else None,
                       'selection_ms_excluding_encoder': wall, 'reason': out.reason,
                       'encoder_scores_used': out.stats.get('escalated', False)}
                rows.append(row)
        print({'arm': a.arm, 'task': task['id'], 'rows': len(rows)}, flush=True)
    dump(a.root/(a.arm+'.json'), rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True); p.add_argument('--worker', action='store_true')
    p.add_argument('--package', type=Path); p.add_argument('--arm')
    a = p.parse_args(); a.root = a.root.resolve()
    if a.worker: return worker(a)
    if a.root.exists(): raise ValueError('new run directory required')
    a.root.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]
    prior = repo/'experiments/runs/packs/cycle15-hierarchy-v1/results.json'
    parent = repo/'experiments/runs/packs/cycle14-seeds-v1'
    from npk.pack import verify
    from npk.pack.format import open_pack, load_blocks
    from benchmarks.evidence_diagnostics import from_evidence, validate_pieces
    data = json.loads(prior.read_text())
    assert verify(parent/'expanded.npk')['ok']
    for item in data['source_manifest']:
        assert sha(parent/'expanded-source'/item['path']) == item['sha256']
    with open_pack(parent/'expanded.npk') as con: blocks = load_blocks(con)
    validate_pieces(parent/'expanded-source', [from_evidence(b) for b in blocks])
    inputs = {'tasks': data['tasks'], 'budgets': [512, 2048, 8192],
              'prior_result_sha256': sha(prior), 'pack_sha256': sha(parent/'expanded.npk'),
              'source_manifest': data['source_manifest'],
              'blocks': [dict(name=b.name or '', text=b.text, path=b.path,
                              start=from_evidence(b).start, end=from_evidence(b).end) for b in blocks]}
    dump(a.root/'inputs.json', inputs)
    baseline = a.root/'baseline'; baseline.mkdir()
    raw = subprocess.run(['git', 'archive', '--format=zip', '5a22535', 'npk'], check=True, capture_output=True).stdout
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if not (baseline/name).resolve().is_relative_to(baseline): raise ValueError('invalid snapshot path')
        z.extractall(baseline)
    current = {f.relative_to(repo).as_posix(): sha(f) for f in (repo/'npk').rglob('*.py')}
    dump(a.root/'manifest.json', {'status': 'PREPARED', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
                                'champion': '5a22535', 'candidate_source_sha256': current,
                                'input_sha256': sha(a.root/'inputs.json')})
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['NPK_ENABLE_EMBEDDINGS'] = '1'
    import socket
    def denied(*args, **kwargs): raise AssertionError('LOCAL encoder attempted network')
    socket.socket.connect = denied
    from npk.context.embedding import get_backend
    start = time.perf_counter(); backend = get_backend(); identity = backend.identity()
    if identity is None: raise ValueError('real pinned local encoder is unavailable')
    load_ms = (time.perf_counter()-start)*1000
    scores = {}; timings = []
    for task in inputs['tasks']:
        start = time.perf_counter()
        score = backend.score_blocks([b.text for b in blocks], task['question'])
        if score is None or len(score) != len(blocks): raise ValueError('incomplete encoder evidence')
        scores[task['id']] = score
        timings.append({'task': task['id'], 'score_ms': (time.perf_counter()-start)*1000})
        print({'LOCAL_encoder': task['id'], 'complete': True}, flush=True)
    dump(a.root/'dense.json', {'evidence_mode': 'LOCAL', 'identity': identity, 'load_ms': load_ms,
                             'scores': scores, 'timings': timings, 'limit': 'First score includes uncached document encoding; later calls reuse document vectors'})
    # Selection workers have separate memory accounting. The parent retains its
    # idle model and recorded scores; timings exclude encoder calls and model load.
    for arm, package in [('before', baseline), ('after', repo)]:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', '--root', str(a.root),
                        '--package', str(package), '--arm', arm], check=True)
    rows = json.loads((a.root/'before.json').read_text()) + json.loads((a.root/'after.json').read_text())
    assert current == {f.relative_to(repo).as_posix(): sha(f) for f in (repo/'npk').rglob('*.py')}
    assert all(r['within_budget'] and r['reported_tokens'] == r['selected_tokens'] for r in rows if r['arm'] == 'after')
    summary = []
    for arm in ('before', 'after'):
        for mode in ('default', 'lexical', 'embedding'):
            for budget in inputs['budgets']:
                group = [r for r in rows if (r['arm'],r['mode'],r['budget']) == (arm,mode,budget)]
                summary.append({'arm':arm, 'mode':mode, 'budget':budget, 'tasks':len(group),
                                'cap_violations':sum(not r['within_budget'] for r in group),
                                'fallbacks':sum(r['seed_failed'] for r in group),
                                'all_required_spans_within_cap':sum(r['all_required_spans'] and r['within_budget'] for r in group),
                                'mean_required_span_fraction_counting_invalid_as_zero':statistics.mean(
                                    r['required_span_fraction'] if r['within_budget'] else 0 for r in group)})
    dump(a.root/'results.json', {'status':'COMPLETE', 'evidence_mode':'LOCAL', 'generative_calls':0,
                                'candidate_source_sha256':current, 'summary':summary, 'rows':rows,
                                'inputs_sha256':sha(a.root/'inputs.json'), 'dense_sha256':sha(a.root/'dense.json'),
                                'limits':['28 known correlated developer-authored tasks; not sealed or answer success',
                                          '2183 compiled source blocks fed to legacy selector, with graph edges empty',
                                          'All arms same legacy chars/3.8 estimate and budgets; not target tokenizer counts',
                                          'Real local MiniLM scores replayed identically; per-selection timings exclude encoder costs',
                                          'Encoder weights loaded once, document vectors reused, OS activity uncontrolled',
                                          'No superiority claim over compiled BM25 or modern hybrid retrieval']})
    print({'COMPLETE':True, 'rows':len(rows), 'summary':summary}, flush=True)


if __name__ == '__main__': main()

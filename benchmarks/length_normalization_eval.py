"""Freeze five length penalties before matched-budget public selection.

The original control is unchanged. All five challengers use the conservative
intent guard, fixed k1=1.2 and identical source blocks/postings/query facets.
The existing selection runner and independent auditor accept this plan schema.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

from benchmarks.length_normalization import rank
from benchmarks.structural_intent import guarded_plan
from benchmarks.structural_intent_eval import save

VALUES = {'b000': 0.0, 'b025': .25, 'b050': .5, 'b075': .75, 'b100': 1.0}
sha = lambda body: hashlib.sha256(body).hexdigest()
read = lambda path: json.loads(path.read_bytes())


def prepare(a):
    if a.output.exists(): raise ValueError('Fresh length study required')
    raw = (a.parent/'plan.json').read_bytes(); old = json.loads(raw)
    assert sha(raw) == (a.parent/'plan.sha256').read_text().strip()
    assert read(a.parent/'state.json')['status'] == 'COMPLETE'
    assert old['pack_sha256'] == sha(a.pack.read_bytes())
    assert old['side_sha256'] == sha(a.side.read_bytes())
    frozen = read(a.snapshot/'snapshot.json')
    assert sha((a.snapshot/'snapshot.json').read_bytes()) == old['snapshot_sha256']
    for name, info in frozen['files'].items(): assert sha((a.snapshot/name).read_bytes()) == info['sha256']
    sys.path.insert(0, str(a.snapshot.resolve()))
    from crisp.score import Scorer
    con = sqlite3.connect(a.side.resolve().as_uri()+'?mode=ro', uri=True)
    examples = []
    try:
        scorer = Scorer(con)
        for example in old['examples']:
            qp = scorer.plan(example['query'])
            assert json.loads(json.dumps(asdict(qp))) == example['original_plan']
            guarded, decision = guarded_plan(qp, 'conservative')
            with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
                original = scorer.candidates(qp, 160)
                assert json.loads(json.dumps(original)) == example['ranks']['original']
                candidates = {mode: rank(scorer, guarded, 160, length_normalization=b) for mode, b in VALUES.items()}
            assert json.loads(json.dumps(candidates['b075'])) == example['ranks']['conservative']
            assert json.loads(json.dumps(asdict(qp))) == example['original_plan'] and guarded.raw == qp.raw
            examples.append({**example, 'ranks': {'original': original, **candidates},
                             'decisions': {'original': example['decisions']['original'],
                                           **{mode: asdict(decision) for mode in VALUES}}})
    finally: con.close()
    repo = Path(__file__).resolve().parents[1]
    paths = [*sorted((repo/'npk').rglob('*.py')),
             *(repo/'benchmarks'/name for name in ('length_normalization.py', 'length_normalization_eval.py',
                                                  'structural_intent.py', 'structural_intent_eval.py'))]
    sources = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in paths}
    plan = {**old, 'experiment': 'bm25_length_penalty', 'intent_parent_plan_sha256': sha(raw),
            'modes': ['original', *VALUES], 'length_normalization': VALUES, 'k1': 1.2,
            'source_sha256': sources, 'examples': examples,
            'limits': [*old['limits'],
                       'Five fixed b values, k1 fixed at 1.2; original scorer and guarded b=.75 exact controls',
                       'Length normalization uses the original cl100k document lengths; all output caps use the pinned NIM tokenizer',
                       'The candidate function runs with a private globals mapping; no process-global parameter patch',
                       'No b value is chosen from partial outcomes; all declared cells must finish before comparison',
                       'Original raw control uses original intent; compare b arms against b075 to isolate length effects',
                       'Changes in structural-bonus magnitude induced by BM25 normalization are part of this existing scorer',
                       'No minimum sufficient context, answer-quality, clean timing or generalization claim']}
    a.output.mkdir(parents=True)
    for name in ('records', 'contexts', 'sources'): (a.output/name).mkdir()
    for name in sources:
        p = a.output/'sources'/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes((repo/name).read_bytes())
    parent_bytes = (a.parent/'parent-plan.json').read_bytes(); assert sha(parent_bytes) == old['parent_plan_sha256']
    (a.output/'parent-plan.json').write_bytes(parent_bytes)
    (a.output/'intent-parent-plan.json').write_bytes(raw)
    save(a.output/'plan.json', plan)
    (a.output/'plan.sha256').write_text(sha((a.output/'plan.json').read_bytes()), encoding='ascii')
    print({'status': 'PREPARED', 'queries': len(examples), 'planned_observations': len(examples)*len(plan['modes'])*len(plan['budgets']),
           'rank_changed_queries_vs_b075': {mode: sum([b for b, _ in e['ranks'][mode]] != [b for b, _ in e['ranks']['b075']] for e in examples) for mode in VALUES},
           'plan_sha256': sha((a.output/'plan.json').read_bytes())}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'pack', 'side', 'snapshot', 'output'): p.add_argument('--'+name, type=Path, required=True)
    prepare(p.parse_args())

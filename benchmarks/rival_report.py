"""Audit frozen outputs and report retention at task and distinct-query levels."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import sys

from npk.pack.format import open_pack


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def normalize(text): return ' '.join(text.split())


def interval(differences, seed=28209, repetitions=2000):
    rng = random.Random(seed)
    values = list(differences)
    sampled = sorted(statistics.mean(rng.choices(values, k=len(values)))
                     for _ in range(repetitions))
    return {'mean_difference': statistics.mean(values),
            'interval_95': [sampled[int(.025*repetitions)], sampled[int(.975*repetitions)]],
            'query_groups': len(values), 'resamples': repetitions}


def report(run, snapshot, output):
    data = read(run/'report.json'); plan = read(run/'plan.json')
    assert data['status'] == 'COMPLETE' and data['rows'] == 8610
    assert sha((snapshot/'snapshot.json').read_bytes()) == plan['snapshot_sha256']
    for name, metadata in read(snapshot/'snapshot.json')['files'].items():
        assert sha((snapshot/name).read_bytes()) == metadata['sha256']
    for name, expected in read(run/'artifact-hashes.json').items():
        assert sha((run/name).read_bytes()) == expected
    sys.path.insert(0, str(snapshot.resolve()))
    from crisp.tokens import Tokenizer
    from crisp.score import Scorer
    from crisp.views import render
    from bench.run_crisp import Base, arm_bm25_topk
    tok = Tokenizer('cl100k_base'); assert tok.exact
    tasks = {t['task_id']: t for t in plan['tasks']}
    rows = []; seen = set(); checked_items = 0
    source = {n: (snapshot/'corpus/test_src'/n).read_text(encoding='utf-8').split('\n') for n in plan['source_files']}
    with ExitStack() as stack:
        normal = stack.enter_context(open_pack(run/'npk_default.npk'))
        members = stack.enter_context(open_pack(run/'npk_members.npk'))
        rival = sqlite3.connect(f'file:{(run/"rival.crisp").resolve().as_posix()}?mode=ro', uri=True)
        stack.callback(rival.close); rival.row_factory = sqlite3.Row
        scorer = Scorer(rival)
        bases = {'crisp_bm25': Base(str(run/'rival.crisp')),
                 'crisp_bm25_struct': Base(str(run/'rival.crisp'), structural=True)}
        for base in bases.values(): stack.callback(base.con.close)
        for i, path in enumerate(sorted((run/'records').glob('*.json'))):
            row = read(path); task = tasks[row['task']]
            key = row['task'], row['budget'], row['arm']
            assert key not in seen; seen.add(key)
            context = (run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
            assert sha(context) == row['context_sha256']; context = context.decode()
            count = tok.count(context)
            assert count == row['tokens_cl100k'] and (count > row['budget']) == row['budget_exceeded']
            flat = normalize(context)
            found = sum(n in flat for n in task['needles'])
            assert row['strict_hit'] == (bool(task['needles']) and found == len(task['needles']))
            assert row['line_recall'] == found/len(task['needles'])
            assert row['body_coverage'] == sum(n in flat for n in task['body'])/len(task['body'])
            if row['items'] is not None:
                assert '\n\n'.join(e['text'] for e in row['items']) == context
                for item in row['items']:
                    con = rival if row['arm'] == 'crisp' else members if 'members' in row['arm'] else normal
                    block = con.execute('SELECT b.*,f.path FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id=?',
                                        (item['block_id'],)).fetchone()
                    assert item['path'] == block['path']
                    assert item['span'] == f'{block["path"]}:{block["start_line"]}-{block["end_line"]}'
                    literal = '\n'.join(source[item['path']][block['start_line']-1:block['end_line']])
                    assert block['text'] == literal
                    if row['arm'] == 'crisp':
                        terms = [f.term for f in scorer.plan(task['query']).facets]
                        expected = render(literal, block['sig_lines'], block['doc_lines'], item['level'], terms)
                    else: expected = literal
                    assert item['text'] == expected
                    checked_items += 1
            else:
                expected, expected_count, _ = arm_bm25_topk(bases[row['arm']], task['query'], row['budget'])
                assert context == expected and count == expected_count
            _, extent = task['span'].rsplit(':', 1); lo, hi = map(int, extent.split('-'))
            if row['items'] is not None:
                texts = []
                for item in row['items']:
                    _, span = item['span'].rsplit(':', 1); start, end = map(int, span.split('-'))
                    if item['path'] == task['path'] and start <= hi and end >= lo: texts.append(item['text'])
                attributed = normalize('\n\n'.join(texts))
                assert row['attributed_strict_hit'] == all(n in attributed for n in task['needles'])
            rows.append({k:v for k,v in row.items() if k != 'items'})
            tok._count_cached.cache_clear()
            if (i+1) % 500 == 0: print({'audited': i+1, 'source_items': checked_items}, flush=True)
    assert seen == {(t,b,a) for t in tasks for b in plan['budgets'] for a in plan['arms']}
    groups = defaultdict(list)
    for row in rows: groups[row['arm'],row['budget'],tasks[row['task']]['query']].append(row)
    summaries = []
    query_scores = {}
    for arm in plan['arms']:
        for budget in plan['budgets']:
            cells = {q:g for (a,b,q),g in groups.items() if (a,b)==(arm,budget)}
            values = {q:statistics.mean(r['strict_hit'] and not r['budget_exceeded'] for r in g) for q,g in cells.items()}
            query_scores[arm,budget] = values
            flat = [r for g in cells.values() for r in g]
            summaries.append({'arm': arm, 'budget': budget, 'task_rows': len(flat), 'query_groups': len(cells),
                              'strict_hits': sum(r['strict_hit'] for r in flat),
                              'valid_budget_hits': sum(r['strict_hit'] and not r['budget_exceeded'] for r in flat),
                              'budget_overruns': sum(r['budget_exceeded'] for r in flat),
                              'mean_tokens_cl100k': statistics.mean(r['tokens_cl100k'] for r in flat),
                              'body_coverage': statistics.mean(r['body_coverage'] for r in flat),
                              'query_macro_valid_retention': statistics.mean(values.values()),
                              'query_any_target_retention': statistics.mean(any(r['strict_hit'] for r in g) for g in cells.values()),
                              'query_all_targets_retention': statistics.mean(all(r['strict_hit'] for r in g) for g in cells.values())})
    comparisons = []
    for baseline in ('npk_default', 'npk_exact', 'npk_members_exact', 'crisp_bm25', 'crisp_bm25_struct'):
        for budget in plan['budgets']:
            first, second = query_scores['crisp',budget], query_scores[baseline,budget]
            assert first.keys() == second.keys()
            comparisons.append({'challenger':'crisp', 'baseline':baseline, 'budget':budget,
                                **interval(first[q]-second[q] for q in sorted(first))})
    result = {'status':'AUDITED', 'evidence_mode':'LOCAL', 'generative_calls':0,
              'plan_sha256':sha((run/'plan.json').read_bytes()), 'audited_rows':len(rows),
              'source_items_checked':checked_items, 'summaries':summaries, 'query_group_comparisons':comparisons,
              'limitations': plan['limitations'] + ['Intervals resample distinct questions, not correlated target-method rows',
                  'Any-target and all-target metrics bound the mechanical label ambiguity; neither measures answer correctness',
                  'Repeated retention on inspected tasks cannot establish superiority on unseen behavior questions']}
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print({'status':'AUDITED','rows':len(rows),'source_items':checked_items}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run','snapshot','output'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); report(args.run, args.snapshot, args.output)

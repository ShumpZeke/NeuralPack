"""Independent source reconstruction and tokenizer checks before LIVE answers.

This checks saved contexts and their attribution, not whether they are sufficient
to answer. Reduced CRISP views are deterministic reconstructions, not literal
full source spans. No generator, model download, or credential is used.
"""
import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def check_context(row, body, query, count):
    assert row['query'] == query, 'query preservation'
    assert sha(body) == row['context_sha256'], 'context digest'
    text = body.decode('utf-8')
    assert text == '\n\n'.join(item['text'] for item in row['items']), 'context assembly'
    assert count(text) == row['selected_tokens'] <= row['budget'], 'exact token budget'
    assert type(row['fallback_required']) is bool
    assert row['fallback_required'] == (not row['items']), 'fallback status'
    assert all(item['text'].strip() for item in row['items']), 'empty passage'
    assert len({item['block_id'] for item in row['items']}) == len(row['items']), 'duplicate passage'


def check_source_item(item, block, expected):
    assert item['path'] == block['path'], 'source path'
    assert item['span'] == f"{block['path']}:{block['start_line']}-{block['end_line']}", 'source span'
    assert item['text'] == expected, 'source text'
    for name in ('kind', 'name'):
        if name in item: assert item[name] == block[name], 'source metadata'


def load_blocks(path, source):
    con = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True); con.row_factory = sqlite3.Row
    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    blocks = {}
    for row in con.execute('SELECT b.*,f.path FROM blocks b JOIN files f ON f.id=b.file_id'):
        b = dict(row); lines = source[b['path']].split('\n')
        assert 1 <= b['start_line'] <= b['end_line'] <= len(lines)
        assert b['text'] == '\n'.join(lines[b['start_line']-1:b['end_line']]), 'compiled source span'
        blocks[b['id']] = b
    return con, blocks


def audit(a):
    if a.output.exists(): raise ValueError('Fresh audit output required')
    snapshot = read(a.snapshot/'snapshot.json')
    for name, info in snapshot['files'].items():
        assert sha((a.snapshot/name).read_bytes()) == info['sha256']
    task_plan = read(a.tasks); tasks = {t['task_id']: t for t in task_plan['tasks']}
    assert task_plan['snapshot_sha256'] == sha((a.snapshot/'snapshot.json').read_bytes())
    source_root = a.snapshot/'corpus/test_src'
    source = {p.relative_to(source_root).as_posix(): p.read_bytes().decode().replace('\r\n', '\n').replace('\r', '\n')
              for p in source_root.rglob('*.py')}
    from tokenizers import Tokenizer
    codec = Tokenizer.from_file(str(a.asset)); codec.no_truncation(); codec.no_padding()
    @lru_cache(maxsize=256)
    def count(text): return len(codec.encode(text, add_special_tokens=False).ids)
    corpus_tokens = count('\n\n'.join(source[path] for path in sorted(source)))
    sys.path.insert(0, str(a.snapshot.resolve()))
    from crisp.score import Scorer
    from crisp.views import build_views, L_FULL, LEVEL_NAME
    class CounterAdapter:
        def count(self, text): return count(text)
    outputs = {}; checked = 0; views = Counter()
    for label, run in [('crisp', a.crisp), ('npk', a.npk)]:
        if run is None: continue
        plan = read(run/'plan.json')
        assert plan['tokenizer_sha256'] == sha(a.asset.read_bytes())
        assert plan['snapshot_sha256'] == sha((a.snapshot/'snapshot.json').read_bytes())
        assert plan['tasks'] == task_plan['tasks']
        report_path = run/('results.json' if label == 'crisp' else 'report.json')
        report = read(report_path)
        assert report['status'] == 'COMPLETE' and report['generative_calls'] == 0
        assert report['plan_sha256'] == sha((run/'plan.json').read_bytes())
        pack = run/'native.crisp' if label == 'crisp' else a.pack
        expected_digest = report['compilation']['sha256'] if label == 'crisp' else plan['pack_sha256']
        assert sha(pack.read_bytes()) == expected_digest
        con, blocks = load_blocks(pack, source)
        scorer = Scorer(con) if label == 'crisp' else None
        seen = set(); row_manifest = []
        try:
            for row in report['rows']:
                key = row['task_id'], row['arm'], row['budget']
                assert key not in seen; seen.add(key)
                assert row['arm'] in plan['arms'] and row['budget'] in plan['budgets']
                query = tasks[row['task_id']]['query']
                body = (run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
                check_context(row, body, query, count)
                facets = [f.term for f in scorer.plan(query).facets] if scorer else None
                collections = [row['items']]
                if 'raw_items' in row:
                    raw = '\n\n'.join(item['text'] for item in row['raw_items'])
                    assert count(raw) == row['raw_tokens']
                    assert row['raw_budget_exceeded'] == (count(raw) > row['budget'])
                    guarded = list(row['raw_items']); dropped = []
                    while guarded and count('\n\n'.join(item['text'] for item in guarded)) > row['budget']:
                        loser = min(range(len(guarded)), key=lambda i: (guarded[i]['relevance'], -i))
                        dropped.append(guarded.pop(loser)['block_id'])
                    assert guarded == row['items'] and dropped == row['guard_dropped']
                    collections.append(row['raw_items'])
                for items in collections:
                    for item in items:
                        b = blocks[item['block_id']]; expected = b['text']
                        if label == 'crisp':
                            level = item['level']; assert item['level_name'] == LEVEL_NAME[level]
                            ladder = build_views(b, facets, CounterAdapter(), levels=(level,))
                            assert len(ladder) == 1 and ladder[0].level == level
                            expected = ladder[0].text; views[item['level_name']] += 1
                        check_source_item(item, b, expected)
                        if 'tokens' in item: assert item['tokens'] == count(expected), 'item token count'
                        checked += 1
                if label == 'crisp' and row['arm'] == 'crisp_native_bm25_raises_exact':
                    candidates = scorer.candidates(scorer.plan(query), 160); chosen = []
                    for bid, _ in candidates:
                        text = '\n\n'.join(blocks[i]['text'] for i in [*chosen, bid])
                        if count(text) <= row['budget']: chosen.append(bid)
                    assert [item['block_id'] for item in row['items']] == chosen, 'baseline ranking/packing'
                    assert all(item['level'] == L_FULL for item in row['items'])
                if label == 'npk':
                    ranks_file = run/'ranks'/row['ranking_file']
                    assert sha(ranks_file.read_bytes()) == row['ranking_sha256']
                    ranked = read(ranks_file)
                    assert ranked['query'] == query and ranked['task_id'] == row['task_id']
                    assert row['risk_band'].startswith('uncalibrated:')
                    ranks = ranked['ranks']; limit = 60 if row['arm'] == 'npk_bm25_60' else 160
                    channels = {'lexical': ranks[row['lexical_ranking']][:limit]}
                    if row['dense_ranking']:
                        channels = {'symbol': ranks['symbol'][:limit], **channels,
                                    'embedding': ranks[row['dense_ranking']][:limit]}
                    scores = {}; membership = {}
                    for channel, ordered in channels.items():
                        assert len(set(ordered)) == len(ordered) <= limit
                        for rank, bid in enumerate(ordered):
                            assert bid in blocks
                            scores[bid] = scores.get(bid, 0.0) + 1.0/(60+rank)
                            membership.setdefault(bid, []).append(channel)
                    chosen = []
                    for bid in sorted(scores, key=lambda bid: -scores[bid]):
                        if count('\n\n'.join(blocks[i]['text'] for i in [*chosen, bid])) <= row['budget']:
                            chosen.append(bid)
                    # The product rechecks complete bytes after all selection edits.
                    while chosen and count('\n\n'.join(blocks[i]['text'] for i in chosen)) > row['budget']:
                        chosen.pop()
                    assert chosen == [item['block_id'] for item in row['items']], 'public packing replay'
                    for item in row['items']:
                        assert item['score'] == scores[item['block_id']]
                        assert item['channels'] == membership[item['block_id']]
                row_manifest.append({k: row[k] for k in ('task_id', 'arm', 'budget', 'context_sha256', 'selected_tokens', 'fallback_required')})
        finally: con.close()
        assert seen == {(tid, arm, budget) for tid in tasks for arm in plan['arms'] for budget in plan['budgets']}
        outputs[label] = {'run': str(run), 'plan_sha256': sha((run/'plan.json').read_bytes()),
                          'report_sha256': sha(report_path.read_bytes()), 'rows': row_manifest,
                          'blocks_checked': len(blocks), 'selections': len(seen)}
    result = {'status': 'AUDITED', 'evidence_mode': 'LOCAL', 'generative_calls': 0, 'new_api_calls': 0,
              'auditor_sha256': sha(Path(__file__).read_bytes()), 'outputs': outputs,
              'source_files': len(source), 'corpus_tokens_per_request': corpus_tokens,
              'source_items_checked_including_raw': checked, 'crisp_views_including_raw': dict(views),
              'limits': ['Source reconstruction and token accounting do not establish answer sufficiency',
                         'Native reduced views include declared synthetic elision markers and docstring closure',
                         'NPK RRF packing is independently replayed; neural relevance scores are not independently certified',
                         'No target prompt is dispatched or graded by this auditor']}
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({k: result[k] for k in ('status', 'source_files', 'corpus_tokens_per_request', 'source_items_checked_including_raw')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot', 'tasks', 'asset', 'output'): p.add_argument('--'+name, type=Path, required=True)
    for name in ('crisp', 'npk', 'pack'): p.add_argument('--'+name, type=Path)
    audit(p.parse_args())

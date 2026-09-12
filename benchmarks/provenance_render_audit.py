"""Independent parsing, source reconstruction and packing replay for render trials.

Does not import the candidate renderer or selector. Source exposure is a separate
post-hoc diagnostic, never a proof that an answer can be determined.
"""
import argparse
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import statistics

from benchmarks.library_selection_audit import load_blocks, check_source_item
from benchmarks.library_failure_analysis import PRIMARY, definitions


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def verify_rendered(text, items, labeled):
    """Consume exact body lengths: apparent source headers inside code are data."""
    offset = 0
    for index, item in enumerate(items):
        if index:
            assert text[offset:offset+2] == '\n\n', 'source separator'
            offset += 2
        if labeled:
            end = text.index('\n', offset)
            line = text[offset:end]
            assert line.startswith('# source '), 'source header marker'
            meta = json.loads(line[9:])
            assert meta == [item['span'], item['name']], 'source header identity'
            assert line.isascii(), 'metadata control characters must be escaped'
            offset = end+1
        body = item['text']
        assert body.strip(), 'empty source body'
        assert text[offset:offset+len(body)] == body, 'source body bytes'
        offset += len(body)
    assert offset == len(text), 'unattributed consumer text'


def independent_text(blocks, ids, labeled):
    parts = []
    for bid in ids:
        block = blocks[bid]
        if labeled:
            metadata = [f"{block['path']}:{block['start_line']}-{block['end_line']}", block['name']]
            parts.append('# source '+json.dumps(metadata, ensure_ascii=True, separators=(',', ':'))+'\n'+block['text'])
        else: parts.append(block['text'])
    return '\n\n'.join(parts)


def audit(a):
    if a.output.exists(): raise ValueError('Fresh render audit output required')
    plan = read(a.run/'plan.json'); report = read(a.run/'report.json')
    assert report['status'] == 'COMPLETE' and report['generative_calls'] == 0
    assert report['plan_sha256'] == sha((a.run/'plan.json').read_bytes())
    assert plan['pack_sha256'] == sha(a.pack.read_bytes())
    assert plan['tokenizer_sha256'] == sha(a.asset.read_bytes())
    assert plan['parent_selection_report_sha256'] == sha((a.baseline/'report.json').read_bytes())
    for name, digest in plan['source_sha256'].items():
        assert sha((a.run/'source'/name).read_bytes()) == digest
    snapshot = read(a.snapshot/'snapshot.json')
    for name, info in snapshot['files'].items():
        assert sha((a.snapshot/name).read_bytes()) == info['sha256']
    source_root = a.snapshot/'corpus/test_src'
    source = {p.relative_to(source_root).as_posix(): p.read_bytes().decode().replace('\r\n', '\n').replace('\r', '\n')
              for p in source_root.rglob('*.py')}
    from tokenizers import Tokenizer
    codec = Tokenizer.from_file(str(a.asset)); codec.no_padding(); codec.no_truncation()
    @lru_cache(maxsize=512)
    def count(text): return len(codec.encode(text, add_special_tokens=False))
    con, blocks = load_blocks(a.pack, source)
    baseline = {(r['task_id'], r['arm'], r['budget']): r for r in read(a.baseline/'report.json')['rows']}
    tasks = {t['task_id']: t for t in plan['tasks']}
    expected = {(tid, seed, fmt, cap) for tid in tasks for seed in plan['seeds']
                for fmt in plan['formats'] for cap in plan['budgets']}
    seen = set(); checked_items = 0; summary_rows = []; contexts = {}
    primary = {tid: [definitions(source[path])[name][2] for path, name in PRIMARY[tid]] for tid in tasks}
    try:
        for row in report['rows']:
            tid, seed, fmt, cap = key = row['task_id'], row['seed'], row['format'], row['budget']
            assert key in expected and key not in seen; seen.add(key)
            record = a.run/'records'/(sha(json.dumps(list(key)).encode())+'.json')
            assert read(record) == row
            assert row['query'] == tasks[tid]['query']
            assert type(row['fallback_required']) is bool
            assert row['fallback_required'] == (not row['items'])
            assert row['risk_band'].startswith('uncalibrated:')
            body = (a.run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
            assert sha(body) == row['context_sha256']; text = body.decode()
            contexts[key] = text
            verify_rendered(text, row['items'], fmt == 'source_headers')
            assert count(text) == row['selected_tokens'] <= cap
            ids = [item['block_id'] for item in row['items']]
            assert len(ids) == len(set(ids))
            rank_path = a.run/'ranks'/(tid+'.json')
            assert rank_path.read_bytes() == (a.baseline/'ranks'/(tid+'.json')).read_bytes()
            ranking = read(rank_path); assert ranking['query'] == row['query']
            channel, limit = plan['seeds'][seed]; candidates = ranking['ranks'][channel][:limit]
            assert len(set(candidates)) == len(candidates)
            chosen = []
            for bid in candidates:
                if count(independent_text(blocks, [*chosen, bid], fmt == 'source_headers')) <= cap:
                    chosen.append(bid)
            assert ids == chosen, 'independent greedy admission differs'
            for item in row['items']:
                b = blocks[item['block_id']]
                check_source_item(item, b, b['text'])
                assert item['tokens'] == count(b['text'])
                assert item['score'] == 1/(60+candidates.index(item['block_id']))
                assert item['channels'] == ['lexical']
                checked_items += 1
            raw_bytes = (a.run/'contexts'/(row['paired_raw_sha256']+'.txt')).read_bytes()
            assert sha(raw_bytes) == row['paired_raw_sha256']
            raw = raw_bytes.decode(); verify_rendered(raw, row['items'], False)
            assert count(raw) == row['raw_body_tokens'] <= cap
            assert row['net_render_token_delta'] == count(text)-count(raw)
            if fmt == 'raw':
                old = baseline[tid, seed, cap]
                assert row['context_sha256'] == old['context_sha256']
                assert ids == [e['block_id'] for e in old['items']]
            summary_rows.append({'task': tid, 'seed': seed, 'format': fmt, 'budget': cap,
                                 'selected_tokens': count(text), 'body_tokens': count(raw),
                                 'net_header_tokens': count(text)-count(raw), 'blocks': len(ids),
                                 'primary_exposed': [definition in raw for definition in primary[tid]],
                                 'all_primary_exposed': all(definition in raw for definition in primary[tid])})
    finally: con.close()
    assert seen == expected
    assert len(list((a.run/'records').glob('*.json'))) == len(expected)
    groups = defaultdict(list)
    for row in summary_rows: groups[row['seed'], row['format'], row['budget']].append(row)
    summaries = []
    for (seed, fmt, cap), group in sorted(groups.items()):
        other = groups[seed, 'raw', cap]
        by_task = {r['task']: r for r in other}
        summaries.append({'seed': seed, 'format': fmt, 'budget': cap, 'tasks': len(group),
                          'mean_selected_tokens': statistics.mean(r['selected_tokens'] for r in group),
                          'mean_body_tokens': statistics.mean(r['body_tokens'] for r in group),
                          'median_net_header_tokens': statistics.median(r['net_header_tokens'] for r in group),
                          'all_primary_exposed': sum(r['all_primary_exposed'] for r in group),
                          'exposure_gained': [r['task'] for r in group if r['all_primary_exposed'] and not by_task[r['task']]['all_primary_exposed']],
                          'exposure_lost': [r['task'] for r in group if not r['all_primary_exposed'] and by_task[r['task']]['all_primary_exposed']]})
    result = {'status': 'AUDITED', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'plan_sha256': report['plan_sha256'], 'report_sha256': sha((a.run/'report.json').read_bytes()),
              'auditor_sha256': sha(Path(__file__).read_bytes()), 'selections': len(seen),
              'source_files': len(source), 'source_blocks': len(blocks), 'source_items_checked': checked_items,
              'whole_context_budget_violations': 0, 'raw_controls_reproduced': len(seen)//2,
              'paired_same_body_controls': len(seen)//2, 'summaries': summaries, 'rows': summary_rows,
              'limits': ['No answer-quality or latency claim from these selections',
                         'Primary function exposure is post-hoc, source-informed, and neither necessary nor sufficient',
                         'Labels carry location and qualified names; source bodies remain unmodified',
                         'Equal-evidence raw controls intentionally leave saved header tokens unused']}
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({k: result[k] for k in ('status', 'selections', 'source_items_checked', 'whole_context_budget_violations')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'baseline', 'pack', 'asset', 'snapshot', 'output'): p.add_argument('--'+name, type=Path, required=True)
    audit(p.parse_args())

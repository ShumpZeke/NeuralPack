"""Freeze and compare local fusion/grouping on existing inspected questions.

Raw public selector controls must reproduce the prior frozen evidence. Only
seed order / candidate union and admission-aware group order may change.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import time
from unittest.mock import patch
import zipfile

from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount
from benchmarks.packing_challengers import GroupedSelector, fuse_body, prepared_pack
from benchmarks.seed_metadata_report import attributed_hit
from npk.pack import LocalTokenizer, PackSelector
from npk.pack.format import load_blocks, open_pack

SEEDS = ('body', 'fields', 'crisp')
POLICIES = ('rank', 'leaf', 'file', 'fuse1', 'fuse2')
METHODS = [(seed, policy) for seed in SEEDS for policy in POLICIES
           if seed != 'body' or not policy.startswith('fuse')]
BUDGETS = (512, 2048, 8192)
sha = lambda b: hashlib.sha256(b).hexdigest()
read = lambda p: json.loads(p.read_bytes())


def file_sha(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, value):
    pending = path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    pending.replace(path)


def code_paths(repo):
    return [*sorted((repo/'npk').rglob('*.py')), Path(__file__).resolve(),
            repo/'benchmarks/packing_challengers.py', repo/'benchmarks/seed_metadata_report.py']


def prepare(a):
    if a.output.exists(): raise ValueError('Fresh packing plan required')
    repo = Path(__file__).resolve().parents[1]
    needle_plan = read(a.needles/'plan.json'); behavior = read(a.behavior/'report.json')
    assert read(a.needles/'state.json')['status'] == behavior['status'] == 'COMPLETE'
    assert needle_plan['pack_sha256'] == read(a.behavior/'plan.json')['pack_sha256'] == sha(a.pack.read_bytes())
    assert needle_plan['asset_sha256'] == read(a.behavior/'plan.json')['tokenizer_sha256'] == sha(a.asset.read_bytes())
    groups = defaultdict(list)
    for task in needle_plan['tasks']: groups[task['query']].append(task)
    examples = []; captured = {}; widened = 0
    for index, (query, tasks) in enumerate(sorted(groups.items())):
        example = {'id': 'needle-'+sha(query.encode())[:16], 'workload': 'needle', 'query': query,
                   'annotations': tasks, 'by_budget': {}}
        for cap in BUDGETS:
            ranks = {}; controls = {}
            for seed, old in zip(SEEDS, ('body60', 'fields', 'crisp_shared_raises')):
                name = sha(json.dumps([query, cap, old], ensure_ascii=False).encode())+'.json'
                path = a.needles/'records'/name; raw = path.read_bytes(); row = json.loads(raw)
                assert (row['query'], row['budget'], row['arm']) == (query, cap, old)
                assert all(e['channels'] == ['lexical'] for e in row['items'])
                captured['needle/'+name] = sha(raw)
                calls = row['seed_calls']; assert calls
                ranks[seed] = calls[-1]['ids']; widened += len(calls) > 1
                controls[seed] = {'ids': [e['block_id'] for e in row['items']], 'tokens': row['selected_tokens'],
                                  'context_sha256': row['context_sha256'], 'fallback': row['fallback'],
                                  'source_record': name, 'source_record_sha256': sha(raw),
                                  'captured_seed_calls': calls}
            example['by_budget'][str(cap)] = {'ranks': ranks, 'controls': controls}
        examples.append(example)
        if index % 40 == 0: print({'phase': 'prepare_needle_controls', 'queries': index+1}, flush=True)
    old_behavior = {(r['task_id'], r['arm'], r['budget']): r for r in behavior['rows']}
    for task in read(a.behavior/'plan.json')['tasks']:
        tid = task['task_id']; rank_path = a.behavior/'ranks'/(tid+'.json')
        rank_raw = rank_path.read_bytes(); rank = json.loads(rank_raw)
        assert rank['query'] == task['query']
        captured['behavior/'+tid+'.json'] = sha(rank_raw)
        example = {'id': tid, 'workload': 'behavior', 'query': task['query'], 'annotations': [], 'by_budget': {}}
        for cap in BUDGETS:
            ranks = {}; controls = {}
            for seed, old in zip(SEEDS, ('npk_bm25_60', 'fields160', 'crisp_shared_raises160')):
                row = old_behavior[tid, old, cap]
                assert row['ranking_sha256'] == sha(rank_raw)
                ranks[seed] = rank['ranks'][seed][:60 if seed == 'body' else 160]
                controls[seed] = {'ids': [e['block_id'] for e in row['items']], 'tokens': row['selected_tokens'],
                                  'context_sha256': row['context_sha256'], 'fallback': row['fallback_required']}
            example['by_budget'][str(cap)] = {'ranks': ranks, 'controls': controls}
        examples.append(example)
    sources = {p.relative_to(repo).as_posix(): sha(p.read_bytes()) for p in code_paths(repo)}
    plan = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'methods': METHODS, 'budgets': BUDGETS,
            'shuffle_seed': 2918, 'examples': examples, 'pack_sha256': sha(a.pack.read_bytes()),
            'tokenizer_sha256': sha(a.asset.read_bytes()), 'source_sha256': sources,
            'needle_plan_sha256': sha((a.needles/'plan.json').read_bytes()),
            'behavior_report_sha256': sha((a.behavior/'report.json').read_bytes()),
            'input_record_sha256': captured, 'captured_widened_seed_cells': widened,
            'hypotheses': ['Plain body BM25 can rescue different failures than metadata/raise search',
                           'Grouping by accepted leaf names or files can limit repeated-match dominance'],
            'limits': ['Inspected development questions; no independent generalization or answer-quality claim',
                       'Frozen seed lookups exclude retrieval latency; these are selection diagnostics',
                       'Parent final seed pools are captured per budget, including any original widening',
                       'Fusion increases candidate union size; it is not an isolated same-pool packing comparison',
                       'Rank-zero RRF with k=60; strong-channel weights 1 and 2 are declared challengers',
                       'Grouping uses only accepted items; rejected candidates do not consume a group turn',
                       'Whole raw-body assembled contexts use exact NIM caps; no labels or caller wrappers added',
                       '16 MiB shared count cache; timings are not clean cold/warm query benchmarks',
                       'Target-profile LIVE and canonical rerun remain pending; no new API attempt is made here']}
    a.output.mkdir(parents=True)
    for name in ('records', 'contexts', 'sources'): (a.output/name).mkdir()
    for name in sources:
        dest = a.output/'sources'/name; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes((repo/name).read_bytes())
    save(a.output/'plan.json', plan)
    (a.output/'plan.sha256').write_text(sha((a.output/'plan.json').read_bytes()), encoding='ascii')
    print({'phase': 'prepared', 'queries': len(examples), 'methods': len(METHODS),
           'cells': len(examples)*len(METHODS)*len(BUDGETS), 'captured_widened_cells': widened}, flush=True)


def run(a):
    repo = Path(__file__).resolve().parents[1]; plan = read(a.output/'plan.json')
    assert sha((a.output/'plan.json').read_bytes()) == (a.output/'plan.sha256').read_text().strip()
    for name, digest in plan['source_sha256'].items(): assert sha((repo/name).read_bytes()) == digest
    assert sha(a.pack.read_bytes()) == plan['pack_sha256'] and sha(a.asset.read_bytes()) == plan['tokenizer_sha256']
    with open_pack(a.pack) as con: blocks = {b.id: b for b in load_blocks(con)}
    counter = LocalTokenizer(a.asset, cache_bytes=16*1024*1024)
    examples = list(plan['examples']); random.Random(plan['shuffle_seed']).shuffle(examples)
    jobs = []
    for index, example in enumerate(examples):
        cells = [(cap, seed, policy) for cap in BUDGETS for seed, policy in METHODS]
        random.Random(plan['shuffle_seed']+index).shuffle(cells)
        jobs.extend((example, *cell) for cell in cells)
    done = 0; newly_done = 0
    for example, cap, seed, policy in jobs:
        key = [example['id'], cap, seed, policy]
        dest = a.output/'records'/(sha(json.dumps(key).encode())+'.json')
        if dest.exists():
            row = read(dest); assert row['key'] == key
            assert sha((a.output/'contexts'/(row['context_sha256']+'.txt')).read_bytes()) == row['context_sha256']
            done += 1; continue
        if a.max_jobs is not None and newly_done >= a.max_jobs: continue
        cell = example['by_budget'][str(cap)]; pool = cell['ranks'][seed]
        if policy.startswith('fuse'): pool = fuse_body(pool, cell['ranks']['body'], int(policy[-1]))
        assert len(pool) == len(set(pool)) and all(bid in blocks for bid in pool)
        limit = max(1, len(pool))
        def lexical(con, query, count):
            assert query == example['query'] and count == limit
            return pool
        cls = GroupedSelector if policy in ('leaf', 'file') else PackSelector
        kw = {'group_mode': policy} if cls is GroupedSelector else {}
        selector = cls(a.pack, tokenizer=counter, candidate_limit=limit, **kw)
        started = time.perf_counter()
        with patch('npk.pack.select._lexical_channel', lexical), patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
            selected = selector.select(example['query'], budget_tokens=cap, allow_escalation=False)
        elapsed = (time.perf_counter()-started)*1000
        context = selected.context_text(); ids = [e.block_id for e in selected.evidence]
        assert selected.query == example['query'] and not selected.used_generative_llm
        assert selected.seed_failed == (not ids) and counter.count(context) == selected.total_tokens <= cap
        items = [asdict(e) for e in selected.evidence]
        for e in selected.evidence:
            b = blocks[e.block_id]; assert (e.path, e.span, e.name, e.text) == (b.path, b.span, b.name, b.text)
        if policy == 'rank':
            control = cell['controls'][seed]
            assert ids == control['ids'] and sha(context.encode()) == control['context_sha256']
            assert selected.total_tokens == control['tokens'] and selected.seed_failed == control['fallback']
        digest = sha(context.encode()); (a.output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
        row = {'key': key, 'query': selected.query, 'workload': example['workload'], 'budget': cap,
               'seed': seed, 'policy': policy, 'candidate_ids': pool, 'selected_tokens': selected.total_tokens,
               'context_sha256': digest, 'items': items, 'fallback': selected.seed_failed,
               'risk_band': selected.risk_band, 'diagnostic_selection_ms': elapsed,
               'hits': {t['task_id']: attributed_hit(items, t) for t in example['annotations']}}
        save(dest, row); done += 1; newly_done += 1
        if newly_done % 50 == 0: print({'phase': 'selection', 'done': done, 'planned': len(jobs)}, flush=True)
    for name, digest in plan['source_sha256'].items(): assert sha((repo/name).read_bytes()) == digest
    state = {'status': 'COMPLETE' if done == len(jobs) else 'CHECKPOINT', 'completed': done, 'planned': len(jobs),
             'newly_completed': newly_done, 'evidence_mode': 'LOCAL', 'generative_calls': 0}
    save(a.output/'state.json', state); print(state, flush=True)


def replay_archive(a):
    """Replay every archived packing cell through the partial evaluator.

    The historical artifact is intentionally opened only as a source-row
    database: its format version is no longer a supported product input. Every
    generated context is compared with the context hash and exact token count
    recorded by the then-current public selector.
    """
    if a.output.exists(): raise ValueError('Fresh replay output required')
    if a.archive is None: raise ValueError('--archive is required for replay')
    prefix=a.archive_prefix.rstrip('/')+'/'
    expected={};archived_ms=0.0
    with zipfile.ZipFile(a.archive) as z:
        plan_bytes=z.read(prefix+'plan.json');plan=json.loads(plan_bytes)
        for name in z.namelist():
            if not (name.startswith(prefix+'records/') and name.endswith('.json')):continue
            raw=z.read(name);row=json.loads(raw);key=tuple(row['key'])
            if key in expected:raise ValueError('Duplicate archived cell key')
            expected[key]=(row['context_sha256'],row['selected_tokens'])
            archived_ms+=row['diagnostic_selection_ms']
    assert sha(a.pack.read_bytes())==plan['pack_sha256']
    assert sha(a.asset.read_bytes())==plan['tokenizer_sha256']
    with open_pack(a.pack) as con:blocks={b.id:b for b in load_blocks(con)}
    counter=CompactBoundaryCount(a.asset,prepared_bytes=128*1024*1024)
    started=time.perf_counter();counter.prepare([b.text for b in blocks.values()])
    prepare_seconds=time.perf_counter()-started
    if counter.prepared_info()['entries']!=len({b.text for b in blocks.values()}):
        raise ValueError('Not every source block has a retained prepared count record')

    # The proposed one-prefix evaluator is invalid when selections are not
    # nested. Measure that failure directly before running independent states.
    selected_by_group=defaultdict(dict)
    with zipfile.ZipFile(a.archive) as z:
        for name in z.namelist():
            if not (name.startswith(prefix+'records/') and name.endswith('.json')):continue
            row=json.loads(z.read(name));key=row['key']
            selected_by_group[(key[0],key[2],key[3])][key[1]]=[i['block_id'] for i in row['items']]
    nonnested=sum(not (set(v[BUDGETS[0]])<=set(v[BUDGETS[1]])<=set(v[BUDGETS[2]]))
                  for v in selected_by_group.values())

    transition_cache={}
    started=time.perf_counter();mismatches=[];cells=0;incremental=fallback=0
    for index,example in enumerate(plan['examples']):
        reference=example['by_budget'][str(BUDGETS[0])]
        for seed,policy in map(tuple,plan['methods']):
            ranks=[example['by_budget'][str(cap)]['ranks'][seed] for cap in BUDGETS]
            if not all(rank==ranks[0] for rank in ranks[1:]):
                raise ValueError('Archived candidate ranking changes across budgets')
            pool=ranks[0]
            if policy.startswith('fuse'):
                pool=fuse_body(pool,reference['ranks']['body'],int(policy[-1]))
            for cap in BUDGETS:
                packed=prepared_pack(pool,blocks,cap,counter,
                                     policy if policy in ('leaf','file') else 'rank',
                                     transition_cache=transition_cache)
                context='\n\n'.join(blocks[bid].text for bid in packed.ids)
                actual=(sha(context.encode()),packed.total_tokens)
                key=(example['id'],cap,seed,policy);want=expected.get(key)
                if actual!=want:mismatches.append({'key':key,'actual':actual,'expected':want})
                incremental+=packed.incremental_attempts;fallback+=packed.fallback_attempts;cells+=1
        if (index+1)%40==0:
            print({'phase':'archive_replay','examples':index+1,'cells':cells},flush=True)
    elapsed=time.perf_counter()-started
    sources=[Path(__file__).resolve(),Path(__file__).with_name('packing_challengers.py'),
             Path(__file__).with_name('compact_boundary_tokenizer.py')]
    report={'status':'COMPLETE' if not mismatches and cells==len(expected) else 'FAILED',
            'evidence_mode':'LOCAL','generative_calls':0,'archive_sha256':file_sha(a.archive),
            'plan_sha256':sha(plan_bytes),'pack_sha256':sha(a.pack.read_bytes()),
            'tokenizer_sha256':sha(a.asset.read_bytes()),'cells':cells,
            'archived_cells':len(expected),'context_or_count_mismatches':len(mismatches),
            'mismatch_examples':mismatches[:20],
            'selection_groups':len(selected_by_group),'nonnested_groups':nonnested,
            'nonnested_rate':nonnested/len(selected_by_group),
            'count_preparation_seconds':prepare_seconds,'partial_evaluation_seconds':elapsed,
            'archived_recorded_selection_seconds':archived_ms/1000,
            'kernel_speedup':archived_ms/1000/elapsed,
            'speedup_including_preparation':archived_ms/1000/(elapsed+prepare_seconds),
            'incremental_attempts':incremental,'fallback_attempts':fallback,
            'transition_cache_entries':len(transition_cache),
            'counter':counter.prepared_info(),
            'source_sha256':{p.name:sha(p.read_bytes()) for p in sources},
            'finding':('One prefix sum is invalid because budgeted greedy selections are non-nested; '
                       'independent incremental boundary states preserve exact behavior.')}
    a.output.mkdir(parents=True);save(a.output/'report.json',report)
    print(json.dumps(report,indent=2),flush=True)
    if report['status']!='COMPLETE':raise SystemExit(1)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('phase', choices=('prepare', 'run','replay'))
    for name in ('pack', 'asset', 'output'): p.add_argument('--'+name, type=Path, required=True)
    for name in ('needles', 'behavior'): p.add_argument('--'+name, type=Path)
    p.add_argument('--archive',type=Path)
    p.add_argument('--archive-prefix',default='experiments/runs/packs/cycle28-packing-v1')
    p.add_argument('--max-jobs', type=int)
    a = p.parse_args(); {'prepare':prepare,'run':run,'replay':replay_archive}[a.phase](a)

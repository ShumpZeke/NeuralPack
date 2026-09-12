"""Frozen matched-budget source-view challenge; inspected development data."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch
import zipfile

from benchmarks.seed_metadata_report import attributed_hit
from benchmarks.source_views import (docstring_lines,omit_docstrings,pack_views,
                                     prepared_pack_views)
from npk.pack import LocalTokenizer
from npk.pack.format import load_blocks, open_pack
from benchmarks.lean_boundary_tokenizer import LeanCompactBoundaryCount
from benchmarks.compact_boundary_tokenizer import PreparedCostGraph

sha = lambda body: hashlib.sha256(body).hexdigest()
read = lambda path: json.loads(path.read_bytes())
POLICIES = ('raw', 'compact', 'rescue')
SEEDS = ('body', 'fields', 'crisp')


def file_sha(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, value):
    temp = path.with_suffix(path.suffix+'.pending')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(path)


def prepare(a):
    if a.output.exists(): raise ValueError('Fresh experiment required')
    if a.source is None: raise ValueError('--source is required for prepare')
    parent_bytes = (a.parent/'plan.json').read_bytes()
    parent = json.loads(parent_bytes)
    assert sha(parent_bytes) == (a.parent/'plan.sha256').read_text().strip()
    assert read(a.parent/'state.json')['status'] == 'COMPLETE'
    assert sha(a.pack.read_bytes()) == parent['pack_sha256']
    assert sha(a.asset.read_bytes()) == parent['tokenizer_sha256']
    with open_pack(a.pack) as con: blocks = {b.id: asdict(b) | {'span': b.span} for b in load_blocks(con)}
    started = time.perf_counter()
    source = {}; intervals = {}; hashes = {}
    for path in {b['path'] for b in blocks.values()}:
        body = (a.source/path).read_bytes(); hashes[path] = sha(body)
        text = body.decode().replace('\r\n', '\n').replace('\r', '\n')
        source[path] = text
        intervals[path] = docstring_lines(text)
    views = {}
    for bid, b in blocks.items():
        assert b['text'] == '\n'.join(source[b['path']].split('\n')[b['start_line']-1:b['end_line']])
        view = omit_docstrings(b['text'], b['start_line'], intervals[b['path']])
        if view: views[bid] = asdict(view)
    build_ms = (time.perf_counter()-started)*1000
    repo = Path(__file__).resolve().parents[1]
    code = [*sorted((repo/'npk').rglob('*.py')), *sorted((repo/'benchmarks').glob('*tokenizer*.py')),
            repo/'benchmarks/source_views.py', Path(__file__).resolve(), repo/'benchmarks/seed_metadata_report.py']
    plan = {'evidence_mode':'LOCAL', 'generative_calls':0, 'policies':POLICIES, 'seeds':SEEDS,
            'budgets':parent['budgets'], 'examples':parent['examples'], 'shuffle_seed':29001,
            'pack_sha256':sha(a.pack.read_bytes()), 'tokenizer_sha256':sha(a.asset.read_bytes()),
            'parent_plan_sha256':sha(parent_bytes), 'source_sha256':hashes,
            'code_sha256':{p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in code},
            'compile_view_ms':build_ms, 'blocks':len(blocks), 'potential_views':len(views),
            'hypothesis':'Explicit docstring omission can retain more implementation evidence at fixed token caps.',
            'limits':['Source-needle retention is not answer accuracy or a sufficiency claim',
                      'All 222 questions were inspected in earlier work; no heldout generalization claim',
                      'Docstrings can be runtime data or the only answer evidence; omissions are explicitly unsafe for such tasks',
                      'Raw/full block controls reproduce previous IDs, text digests and exact NIM counts',
                      'Frozen original seed lists; lookup time excluded; compact policy changes source representation',
                      'Current CRISP has not been rerun; this is the earlier frozen CRISP scorer on shared NPK blocks',
                      'Omission marker and separators are included in the cap; query/system are external and preserved',
                      'No graph, code execution, neural inference, generated summary or generative optimizer',
                      'Experimental views held in memory; no product format, incremental or economic promotion']}
    a.output.mkdir(parents=True)
    for directory in ('records', 'contexts', 'sources'): (a.output/directory).mkdir()
    save(a.output/'views.json', views)
    plan['views_sha256'] = sha((a.output/'views.json').read_bytes())
    for path in code:
        dest=a.output/'sources'/path.relative_to(repo); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
    save(a.output/'plan.json', plan)
    (a.output/'plan.sha256').write_text(sha((a.output/'plan.json').read_bytes()), encoding='ascii')
    print(json.dumps({'phase':'prepared', 'queries':len(plan['examples']), 'cells':len(plan['examples'])*27,
                      'blocks':len(blocks), 'views':len(views), 'compile_view_ms':build_ms}), flush=True)


def run(a):
    from benchmarks.source_views import View, Fragment
    if a.source is None: raise ValueError('--source is required for run')
    repo=Path(__file__).resolve().parents[1]; plan=read(a.output/'plan.json')
    assert sha((a.output/'plan.json').read_bytes()) == (a.output/'plan.sha256').read_text().strip()
    assert sha(a.pack.read_bytes()) == plan['pack_sha256'] and sha(a.asset.read_bytes()) == plan['tokenizer_sha256']
    for name, digest in plan['code_sha256'].items(): assert sha((repo/name).read_bytes()) == digest
    assert sha((a.output/'views.json').read_bytes()) == plan['views_sha256']
    views = {int(bid):View(tuple(Fragment(**f) for f in v['fragments']), tuple(tuple(x) for x in v['omitted']), v['text'])
             for bid,v in read(a.output/'views.json').items()}
    with open_pack(a.pack) as con: blocks={b.id:asdict(b) | {'span':b.span} for b in load_blocks(con)}
    counter=LeanCompactBoundaryCount(a.asset, cache_bytes=16*1024*1024)
    started=time.perf_counter()
    counter.prepare([b['text'] for b in blocks.values()]+[v.text for v in views.values()])
    preparation_ms=(time.perf_counter()-started)*1000
    compact_ids={bid for bid,view in views.items()
                 if counter.count(view.text)<counter.count(blocks[bid]['text'])}
    transition_cache={}
    # This is the same source-file representation used by preceding large-context studies.
    source={p:(a.source/p).read_bytes() for p in plan['source_sha256']}
    assert all(sha(v)==plan['source_sha256'][p] for p,v in source.items())
    source_text={p:v.decode().replace('\r\n','\n').replace('\r','\n') for p,v in source.items()}
    available=counter.count('\n\n'.join(source_text[p] for p in sorted(source_text)))
    jobs=[(e, cap, seed, policy) for e in plan['examples'] for cap in plan['budgets'] for seed in SEEDS for policy in POLICIES]
    random.Random(plan['shuffle_seed']).shuffle(jobs)
    done=0
    for e, cap, seed, policy in jobs:
        key=[e['id'], cap, seed, policy]; dest=a.output/'records'/(sha(json.dumps(key).encode())+'.json')
        if dest.exists():
            saved=read(dest); assert saved['key']==key
            assert sha((a.output/'contexts'/(saved['context_sha256']+'.txt')).read_bytes())==saved['context_sha256']
            done+=1; continue
        cell=e['by_budget'][str(cap)]; pool=cell['ranks'][seed]
        with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
            started=time.perf_counter()
            row=pack_views(e['query'], cap, pool, blocks, views, counter.count, policy=policy,
                           count_parts=counter.count_parts,state_counter=counter,
                           compact_ids=compact_ids,transition_cache=transition_cache)
            elapsed=(time.perf_counter()-started)*1000
        assert row['query']==e['query'] and not row['used_generative_llm']
        assert counter.count(row['context'])==row['tokens']<=cap
        digest=sha(row['context'].encode())
        if policy=='raw':
            control=cell['controls'][seed]
            assert [i['block_id'] for i in row['items']]==control['ids']
            assert digest==control['context_sha256'] and row['tokens']==control['tokens']
            assert row['fallback_required']==control['fallback']
        evidence=[{'text':f['text'], 'path':i['path'], 'span':i['path']+':'+str(f['start_line'])+'-'+str(f['end_line'])}
                  for i in row['items'] for f in i['fragments']]
        row.update(key=key, workload=e['workload'], seed=seed, context_sha256=digest,
                   available_source_tokens=available, source_file_tokens=available,
                   diagnostic_packing_ms=elapsed, hits={t['task_id']:attributed_hit(evidence,t) for t in e['annotations']})
        (a.output/'contexts'/(digest+'.txt')).write_bytes(row.pop('context').encode())
        save(dest,row); done+=1
        if done%300==0: print(json.dumps({'phase':'selection','done':done,'planned':len(jobs)}),flush=True)
    for name,digest in plan['code_sha256'].items(): assert sha((repo/name).read_bytes())==digest
    summary=[]
    rows=[read(p) for p in (a.output/'records').glob('*.json')]
    for seed in SEEDS:
        for cap in plan['budgets']:
            controls={r['key'][0]:r for r in rows if r['seed']==seed and r['budget']==cap and r['policy']=='raw'}
            for policy in POLICIES:
                cells=[r for r in rows if r['seed']==seed and r['budget']==cap and r['policy']==policy]
                wins=losses=0
                for r in cells:
                    old=controls[r['key'][0]]
                    for tid, hit in r['hits'].items():
                        wins+=hit and not old['hits'][tid]; losses+=old['hits'][tid] and not hit
                summary.append({'seed':seed, 'budget':cap, 'policy':policy, 'selections':len(cells),
                                'source_needle_hits':sum(sum(r['hits'].values()) for r in cells),
                                'annotations':sum(len(r['hits']) for r in cells), 'wins':wins,'losses':losses,
                                'omission_selections':sum(r['status']=='selected_with_omissions' for r in cells),
                                'mean_selected_tokens':statistics.mean(r['tokens'] for r in cells),
                                'fallbacks':sum(r['fallback_required'] for r in cells)})
    save(a.output/'report.json',{'status':'COMPLETE','evidence_mode':'LOCAL','generative_calls':0,
         'plan_sha256':sha((a.output/'plan.json').read_bytes()),'record_sha256':{p.name:sha(p.read_bytes()) for p in (a.output/'records').glob('*.json')},
         'available_source_tokens_per_request':available,'summary':summary, 'limits':plan['limits'],
         'count_preparation_ms':preparation_ms,'counter':'LeanCompactBoundaryCount; pinned NIM asset only',
         'boundary_calls':counter.boundary_calls,'fallback_count_calls':counter.fallback_calls})
    print(json.dumps({'phase':'complete','selections':done,'available_source_tokens_per_request':available,
                      'summary_2k':[s for s in summary if s['budget']==2048]}),flush=True)


def replay_archive(a):
    """Reproduce the archived 5,994 source-view cells with incremental counts."""
    from benchmarks.source_views import View,Fragment
    if a.output.exists():raise ValueError('Fresh replay output required')
    if a.archive is None:raise ValueError('--archive is required for replay')
    prefix=a.archive_prefix.rstrip('/')+'/'
    expected={};archived_ms=0.0
    with zipfile.ZipFile(a.archive) as z:
        plan_bytes=z.read(prefix+'plan.json');plan=json.loads(plan_bytes)
        views_bytes=z.read(prefix+'views.json');raw_views=json.loads(views_bytes)
        for name in z.namelist():
            if not (name.startswith(prefix+'records/') and name.endswith('.json')):continue
            row=json.loads(z.read(name));key=tuple(row['key'])
            if key in expected:raise ValueError('Duplicate archived source-view key')
            expected[key]=(row['context_sha256'],row['tokens'])
            archived_ms+=row['diagnostic_packing_ms']
    assert sha(a.pack.read_bytes())==plan['pack_sha256']
    assert sha(a.asset.read_bytes())==plan['tokenizer_sha256']
    views={int(bid):View(tuple(Fragment(**f) for f in value['fragments']),
                         tuple(tuple(x) for x in value['omitted']),value['text'])
           for bid,value in raw_views.items()}
    with open_pack(a.pack) as con:blocks={b.id:asdict(b)|{'span':b.span} for b in load_blocks(con)}
    counter=LeanCompactBoundaryCount(a.asset,cache_bytes=16*1024*1024,
                                     prepared_bytes=128*1024*1024)
    started=time.perf_counter()
    prepared_texts=[b['text'] for b in blocks.values()]+[v.text for v in views.values()]
    counter.prepare(prepared_texts)
    compact_ids={bid for bid,view in views.items()
                 if counter.count(view.text)<counter.count(blocks[bid]['text'])}
    cost_graph=PreparedCostGraph(counter,prepared_texts)
    prepare_seconds=time.perf_counter()-started
    retained=len({b['text'] for b in blocks.values()}|{v.text for v in views.values()})
    if counter.prepared_info()['entries']!=retained:
        raise ValueError('Not every source view has a retained prepared count record')
    transition_cache={}
    mismatches=[];cells=incremental=fallback=sampled=0;started=time.perf_counter()
    for example in plan['examples']:
        for seed in SEEDS:
            ranks=[example['by_budget'][str(cap)]['ranks'][seed] for cap in plan['budgets']]
            if not all(rank==ranks[0] for rank in ranks[1:]):
                raise ValueError('Archived source-view ranking changes across budgets')
            for policy in POLICIES:
                packed=prepared_pack_views(ranks[0],plan['budgets'],blocks,views,
                                           compact_ids,cost_graph,policy)
                for cap,row in packed.items():
                    context='\n\n'.join(views[bid].text if is_view else blocks[bid]['text']
                                        for bid,is_view in row.representations)
                    actual=(sha(context.encode()),row.total_tokens)
                    key=(example['id'],cap,seed,policy);want=expected.get(key)
                    if actual!=want:mismatches.append({'key':key,'actual':actual,'expected':want})
                    incremental+=row.graph_attempts;fallback+=row.fallback_attempts;cells+=1
                    # Deterministic ~1% check through the full provenance path.
                    if int(sha(json.dumps(key).encode())[:8],16)%100==0:
                        full=pack_views(example['query'],cap,ranks[0],blocks,views,
                                        counter.count,policy=policy,count_parts=counter.count_parts,
                                        state_counter=counter,compact_ids=compact_ids,
                                        transition_cache=transition_cache)
                        assert (full['context'],full['tokens'])==(context,row.total_tokens)
                        sampled+=1
    elapsed=time.perf_counter()-started
    report={'status':'COMPLETE' if not mismatches and cells==len(expected) else 'FAILED',
            'evidence_mode':'LOCAL','generative_calls':0,
            'archive_sha256':file_sha(a.archive),'plan_sha256':sha(plan_bytes),
            'views_sha256':sha(views_bytes),'pack_sha256':sha(a.pack.read_bytes()),
            'tokenizer_sha256':sha(a.asset.read_bytes()),'cells':cells,'archived_cells':len(expected),
            'context_or_count_mismatches':len(mismatches),'mismatch_examples':mismatches[:20],
            'count_preparation_seconds':prepare_seconds,'partial_evaluation_seconds':elapsed,
            'archived_recorded_packing_seconds':archived_ms/1000,
            'kernel_speedup':archived_ms/1000/elapsed,
            'speedup_including_preparation':archived_ms/1000/(elapsed+prepare_seconds),
            'incremental_attempts':incremental,'fallback_attempts':fallback,
            'transition_cache_entries':len(transition_cache),
            'cost_graph':cost_graph.info(),'sampled_full_cross_checks':sampled,
            'counter':counter.prepared_info(),
            'source_sha256':{Path(__file__).name:sha(Path(__file__).read_bytes()),
                             'source_views.py':sha(Path(__file__).with_name('source_views.py').read_bytes()),
                             'compact_boundary_tokenizer.py':sha(Path(__file__).with_name('compact_boundary_tokenizer.py').read_bytes())}}
    a.output.mkdir(parents=True);save(a.output/'report.json',report);print(json.dumps(report,indent=2),flush=True)
    if report['status']!='COMPLETE':raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('phase',choices=('prepare','run','replay'))
    for name in ('output','pack','asset'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--source',type=Path)
    p.add_argument('--parent',type=Path)
    p.add_argument('--archive',type=Path)
    p.add_argument('--archive-prefix',default='experiments/runs/packs/cycle29-source-views-v2')
    a=p.parse_args();{'prepare':prepare,'run':run,'replay':replay_archive}[a.phase](a)

"""Paired LOCAL compiled-artifact costs and evidence equivalence on frozen Click.

No generative calls. Independent worker processes, randomized arm order per
trial, same source edits and query budgets. OS caches are not controlled.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timed(operation):
    start=time.perf_counter()
    result=operation()
    return result,1000*(time.perf_counter()-start)


def worker(args):
    sys.path.insert(0,str(args.implementation.resolve()))
    from npk.pack import compile_pack,update_pack,verify,PackSelector
    import importlib
    compiler=importlib.import_module('npk.pack.compile')
    stages={}
    for name in ('scan_source','_seal','check_cached_base','_write_file_blocks','_drop_file','_available_tokens'):
        if not hasattr(compiler,name):continue
        original=getattr(compiler,name)
        def wrapped(*a,_name=name,_original=original,**kw):
            start=time.perf_counter()
            try:return _original(*a,**kw)
            finally:stages[_name]=stages.get(_name,0)+1000*(time.perf_counter()-start)
        setattr(compiler,name,wrapped)
    plan=json.loads(args.plan.read_text())
    source=args.output.parent/'source';source.mkdir()
    for item in plan['source_manifest']:
        target=source/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(args.origin/item['path'],target)
    options={'python_members':args.config!='windows','mode':'semantic' if args.config=='hybrid' else 'deterministic'}
    retrieval='hybrid' if args.config=='hybrid' else 'lexical'
    pack=args.output.parent/'base.npk'
    initial,compile_ms=timed(lambda:compile_pack(source,pack,**options))
    compile_stages=dict(stages)
    if args.config=='hybrid' and initial.embedded!=initial.blocks:
        raise AssertionError('semantic model unavailable or index incomplete')
    selector=PackSelector(pack,retrieval=retrieval)
    tasks=plan['dataset']['tasks']
    def evidence(current):
        items=[]
        for task in tasks:
            for budget in (512,2048,8192):
                selected,ms=timed(lambda:current.select(task['question'],budget_tokens=budget))
                assert selected.total_tokens<=budget
                items.append({'task':task['id'],'budget':budget,'text_sha256':hashlib.sha256(selected.context_text().encode()).hexdigest(),
                              'spans':[b.span for b in selected.evidence],'tokens':selected.total_tokens,
                              'seed_failed':selected.seed_failed,'latency_ms':ms})
        return items
    before=evidence(selector)
    warm=[row['latency_ms'] for row in evidence(selector)]
    checked,verify_ms=timed(lambda:verify(pack));assert checked['ok']
    before_bytes=digest(pack);stages.clear()
    noop,noop_ms=timed(lambda:update_pack(pack,source))
    assert digest(pack)==before_bytes and noop.files_indexed==0
    paths=sorted(item['path'] for item in plan['source_manifest'])
    random.Random(20260906).shuffle(paths)
    py=[p for p in paths if p.startswith('src/') and p.endswith('.py')]
    small=min(py,key=lambda p:(source/p).stat().st_size)
    large=max(py,key=lambda p:(source/p).stat().st_size)
    operations=[('small_file',[small]),('large_file',[large]),
                ('one_percent',paths[:math.ceil(len(paths)*.01)]),
                ('ten_percent',paths[:math.ceil(len(paths)*.10)]),
                ('delete',[small]),('rename',[small])]
    updates=[]
    for label,changed in operations:
        working=args.output.parent/(label+'.npk');shutil.copyfile(pack,working)
        original={p:(source/p).read_bytes() for p in changed}
        moved=None
        try:
            if label=='delete':(source/small).unlink()
            elif label=='rename':
                moved=(source/small).with_name('cycle11_renamed.py');(source/small).rename(moved)
            else:
                for p,body in original.items():(source/p).write_bytes(body+b'\n# incremental measurement marker\n')
            stages.clear()
            stats,elapsed=timed(lambda:update_pack(working,source))
            stage_times=dict(stages)
            checked,updated_verify_ms=timed(lambda:verify(working));assert checked['ok']
            after=evidence(PackSelector(working,retrieval=retrieval))
            # Independent fresh compilation must select exactly the same text,
            # source spans and token counts as incremental replacement.
            fresh=args.output.parent/(label+'-fresh.npk')
            compile_pack(source,fresh,**options)
            rebuilt=evidence(PackSelector(fresh,retrieval=retrieval))
            comparable=lambda rows:[{k:v for k,v in row.items() if k!='latency_ms'} for row in rows]
            assert comparable(after)==comparable(rebuilt),'incremental/fresh evidence diverged'
            updates.append({'operation':label,'changed_paths':changed,'update_ms':elapsed,'stages_ms':stage_times,
                            'verify_ms':updated_verify_ms,'stats':stats.as_dict(),'evidence':after,
                            'fresh_evidence_identical':True})
        finally:
            if moved is not None:moved.unlink()
            for p,body in original.items():(source/p).write_bytes(body)
    import psutil
    memory=psutil.Process().memory_info()._asdict()
    result={'evidence_mode':'LOCAL','generative_calls':0,'config':args.config,'compile_ms':compile_ms,
            'compile_stages_ms':compile_stages,'stats':initial.as_dict(),'disk_bytes':pack.stat().st_size,
            'verify_ms':verify_ms,'noop_ms':noop_ms,'first_sweep':before,'warm_median_ms':statistics.median(warm),
            'warm_query_ms':warm,'updates':updates,'memory_end':memory}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print({k:result[k] for k in ('config','compile_ms','verify_ms','noop_ms','warm_median_ms')},flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--implementation',type=Path)
    parser.add_argument('--origin',type=Path);parser.add_argument('--plan',type=Path)
    parser.add_argument('--config',choices=('windows','members','hybrid'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--trials',type=int,default=3)
    parser.add_argument('--champion',default='bfd3045');parser.add_argument('--run',type=Path)
    parser.add_argument('--report-evidence-changes',action='store_true',
                        help='Retain and report cross-version selection differences; incremental/fresh equality remains mandatory')
    parser.add_argument('--configs',nargs='+',choices=('windows','members','hybrid'),default=['windows','members','hybrid'])
    args=parser.parse_args()
    if args.worker:return worker(args)
    repo=Path(__file__).resolve().parents[1]
    run=(args.run or repo/'experiments/runs/packs/cycle11-cache').resolve()
    if run.exists() or args.output.exists():raise ValueError('new run/output paths required')
    run.mkdir(parents=True)
    plan_path=repo/'experiments/runs/repository-click-v1/plan.json'
    plan=json.loads(plan_path.read_text());assert digest(plan_path)==plan_path.with_suffix('.sha256').read_text().strip()
    origin=plan_path.parent/'source/click-8.5.0'
    for item in plan['source_manifest']:assert digest(origin/item['path'])==item['sha256']
    champion=subprocess.check_output(['git','rev-parse',args.champion],cwd=repo,text=True).strip()
    old=run/'champion';old.mkdir()
    with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['git','archive',champion,'npk'],cwd=repo))) as archive:
        archive.extractall(old,filter='data')
    candidate=run/'candidate';candidate.mkdir();shutil.copytree(repo/'npk',candidate/'npk',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    hashes={p.relative_to(repo).as_posix():digest(p) for p in (repo/'npk').rglob('*.py')}
    script=run/'incremental_cache_eval.py';shutil.copyfile(Path(__file__),script)
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_CACHE=str(repo/'experiments/models/hf_cache'))
    rows=[];rng=random.Random(1106)
    for trial in range(args.trials):
        configs=[config for config in args.configs if config!='hybrid' or trial==0]
        for config in configs:
            arms=[('champion',old),('candidate',candidate)];rng.shuffle(arms)
            for arm,implementation in arms:
                folder=run/f'{trial}-{config}-{arm}';folder.mkdir()
                output=folder/'result.json'
                subprocess.run([sys.executable,str(script),'--worker','--implementation',str(implementation),
                                '--origin',str(origin),'--plan',str(plan_path),'--config',config,'--output',str(output)],
                               cwd=implementation,env=env,check=True)
                row=json.loads(output.read_text());row.update(trial=trial,arm=arm);rows.append(row)
                print(arm,trial,config,flush=True)
                # Persist completed work after each independent worker.
                args.output.write_text(json.dumps({'status':'RUNNING','rows':rows},indent=2),encoding='utf-8')
    differences=[]
    comparable=lambda evidence:[{k:v for k,v in row.items() if k!='latency_ms'} for row in evidence]
    for trial in range(args.trials):
        for config in ('windows','members','hybrid'):
            pair=[r for r in rows if r['trial']==trial and r['config']==config]
            if not pair:continue
            assert len(pair)==2
            a,b=pair
            if comparable(a['first_sweep'])!=comparable(b['first_sweep']):differences.append([trial,config,'initial'])
            for x,y in zip(a['updates'],b['updates']):
                assert x['operation']==y['operation']
                if comparable(x['evidence'])!=comparable(y['evidence']):differences.append([trial,config,x['operation']])
    assert all(digest(repo/path)==sha for path,sha in hashes.items())
    report={'status':'COMPLETE','evidence_mode':'LOCAL','generative_calls':0,'champion_commit':champion,
            'candidate_hashes':hashes,'benchmark_sha256':digest(script),'plan_sha256':digest(plan_path),
            'available_tokens':plan['available_tokens'],'source_manifest':plan['source_manifest'],
            'rows':rows,'evidence_differences':differences,
            'cross_version_equality_required':not args.report_evidence_changes,
            'limitations':['One machine, uncontrolled OS cache; worker processes isolated per arm/config/trial',
                           'Semantic compile includes first model loading; later fresh compiles reuse encoder RAM cache',
                           'Source scan and FTS integrity remain proportional to corpus size',
                           'Edits append comments; delete/rename are additional invariance checks, not refactor-quality tests',
                           'Instrumentation adds timer overhead; nested stage times must not be summed',
                           'Memory is process end/peak across updates and fresh compiles, not pure query memory',
                           'No new answer-quality evidence or dollar savings inferred from identical selections']}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    if differences and not args.report_evidence_changes:raise AssertionError('candidate selection differs from champion')


if __name__=='__main__':main()

"""LOCAL challenger: amortize schema setup commits in unpublished builds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--implementation',type=Path)
    parser.add_argument('--corpus',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.worker:
        sys.path.insert(0,str(args.implementation.resolve()))
        from npk.pack import compile_pack,PackSelector,verify
        rows=[]
        for source in sorted(args.corpus.iterdir()):
            pack=args.output.parent/(source.name+'.npk')
            start=time.perf_counter();stats=compile_pack(source,pack);elapsed=1000*(time.perf_counter()-start)
            result=PackSelector(pack).select('retry command parameter',budget_tokens=2048)
            assert verify(pack)['ok']
            rows.append({'scale':source.name,'compile_ms':elapsed,'stats':stats.as_dict(),
                         'available_tokens':result.available_tokens,'disk_bytes':pack.stat().st_size,
                         'text_sha256':hashlib.sha256(result.context_text().encode()).hexdigest(),
                         'spans':[e.span for e in result.evidence]})
        args.output.write_text(json.dumps(rows,indent=2),encoding='utf-8');return
    repo=Path(__file__).resolve().parents[1]
    run=repo/'experiments/runs/packs/cycle11-transactions'
    if run.exists() or args.output.exists():raise ValueError('new paths required')
    run.mkdir();corpus=run/'corpus';corpus.mkdir()
    plan_path=repo/'experiments/runs/repository-click-v1/plan.json';plan=json.loads(plan_path.read_text())
    origin=plan_path.parent/'source/click-8.5.0'
    ordered=sorted(plan['source_manifest'],key=lambda item:(origin/item['path']).stat().st_size)
    manifest=[]
    for target in (2000,50000,300000):
        folder=corpus/f'scale-{target:06}';folder.mkdir();tokens=0
        for item in ordered:
            path=origin/item['path'];assert digest(path)==item['sha256']
            to=folder/item['path'];to.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,to)
            tokens+=len(path.read_text(encoding='utf-8'))//4
            manifest.append({'path':to.relative_to(corpus).as_posix(),'sha256':digest(to)})
            if tokens>=target:break
    variants={}
    source=(repo/'npk/pack/compile.py').read_text(encoding='utf-8')
    old='        con.executescript(SCHEMA)\n        install_tracking(con)'
    assert source.count(old)==1
    for variant,replacement in (
        ('separate_ddl',old),
        ('tracking_transaction','        con.executescript(SCHEMA)\n        con.execute("BEGIN")\n        install_tracking(con)'),
        ('all_transaction','        con.executescript("BEGIN;\\n" + SCHEMA)\n        install_tracking(con)')):
        implementation=run/variant;implementation.mkdir()
        shutil.copytree(repo/'npk',implementation/'npk',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        (implementation/'npk/pack/compile.py').write_text(source.replace(old,replacement),encoding='utf-8')
        variants[variant]=implementation
    script=run/Path(__file__).name;shutil.copyfile(Path(__file__),script)
    rows=[];rng=random.Random(1107)
    for trial in range(3):
        order=list(variants.items());rng.shuffle(order)
        for variant,implementation in order:
            folder=run/f'{trial}-{variant}';folder.mkdir();output=folder/'result.json'
            subprocess.run([sys.executable,str(script),'--worker','--implementation',str(implementation),
                            '--corpus',str(corpus),'--output',str(output)],cwd=implementation,check=True)
            values=json.loads(output.read_text());rows.append({'trial':trial,'variant':variant,'rows':values})
            print(variant,trial,[(r['available_tokens'],round(r['compile_ms'],1)) for r in values],flush=True)
    for scale in rows[0]['rows']:
        values=[r for group in rows for r in group['rows'] if r['scale']==scale['scale']]
        assert len({r['text_sha256'] for r in values})==1
        assert all(r['spans']==values[0]['spans'] for r in values)
    report={'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'source_manifest':manifest,
            'variant_hashes':{name:{p.relative_to(root).as_posix():digest(p) for p in (root/'npk').rglob('*.py')}
                              for name,root in variants.items()},'benchmark_sha256':digest(script),
            'limitations':['3 sequential trials per variant; uncontrolled filesystem caches',
                           'Real Click files selected by increasing size; available tokens recorded, not target labels',
                           'One fixed diagnostic query per scale establishes only tested selection equivalence',
                           'No semantic model or quality promotion in this experiment']}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()

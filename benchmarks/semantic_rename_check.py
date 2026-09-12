"""Focused LOCAL follow-up to a slow source-scan outlier, not a replacement run."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--implementation',type=Path)
    parser.add_argument('--baseline',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.worker:
        sys.path.insert(0,str(args.implementation.resolve()))
        from npk.pack import update_pack,verify,PackSelector
        module=importlib.import_module('npk.pack.compile')
        original=module.scan_source;scans=[]
        def scanned(*a,**kw):
            start=time.perf_counter()
            try:return original(*a,**kw)
            finally:scans.append(1000*(time.perf_counter()-start))
        module.scan_source=scanned
        source=args.output.parent/'source';shutil.copytree(args.baseline/'source',source)
        base=args.baseline/'base.npk'
        plan=json.loads((args.baseline/'result.json').read_text())
        small=plan['updates'][-1]['changed_paths'][0];path=source/small
        destination=path.with_name('cycle11_renamed.py')
        # Explicitly warm the local encoder. Loading is outside update timing.
        initial=PackSelector(base,retrieval='hybrid').select('command parameter retry')
        rows=[]
        for trial in range(5):
            pack=args.output.parent/f'{trial}.npk';shutil.copyfile(base,pack);path.rename(destination)
            try:
                start=time.perf_counter();stats=update_pack(pack,source);elapsed=1000*(time.perf_counter()-start)
                assert verify(pack)['ok'] and stats.encoder_rows_requested==0
                result=PackSelector(pack,retrieval='hybrid').select('command parameter retry')
                rows.append({'trial':trial,'update_ms':elapsed,'scan_ms':scans[-1],'stats':stats.as_dict(),
                             'text_sha256':hashlib.sha256(result.context_text().encode()).hexdigest()})
            finally:destination.rename(path)
        args.output.write_text(json.dumps(rows,indent=2),encoding='utf-8');return
    repo=Path(__file__).resolve().parents[1];base=repo/'experiments/runs/packs/cycle11-cache'
    run=repo/'experiments/runs/packs/cycle11-rename-followup';run.mkdir()
    candidate=run/'candidate';candidate.mkdir();shutil.copytree(repo/'npk',candidate/'npk',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    hashes={p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo/'npk').rglob('*.py')}
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_CACHE=str(repo/'experiments/models/hf_cache'))
    rows=[]
    for arm,implementation in (('candidate',candidate),('champion',base/'champion')):
        folder=run/arm if arm=='champion' else run/'candidate-run';folder.mkdir()
        output=folder/'result.json'
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--implementation',str(implementation),
                        '--baseline',str(base/f'0-hybrid-{arm}'),'--output',str(output)],cwd=implementation,env=env,check=True)
        values=json.loads(output.read_text());rows.append({'arm':arm,'rows':values})
        print(arm,[(round(r['update_ms'],1),round(r['scan_ms'],1)) for r in values],flush=True)
    assert len({r['text_sha256'] for group in rows for r in group['rows']})==1
    args.output.write_text(json.dumps({'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'candidate_hashes':hashes,
                                     'benchmark_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                     'limitations':['Follow-up selected after an observed outlier; original result remains in the paired report',
                                                    'Fixed candidate-first order; local encoder warm; no compilation timing',
                                                    'Five repeat renames, one machine, uncontrolled OS cache; not independent quality data']},indent=2),encoding='utf-8')


if __name__=='__main__':main()

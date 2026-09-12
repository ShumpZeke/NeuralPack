"""Acquire exact-version API manuals as an explicit corpus challenger, locally compile them."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import time
import urllib.request
from unittest.mock import patch
from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import open_pack, load_blocks


COMMIT='0cc81280367df838c4b199f8f0378837165071c2'
MANUALS=('collections','functools','contextlib')


def sha(body): return hashlib.sha256(body).hexdigest()
def dump(path, value): path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    a=p.parse_args();root=a.root.resolve();repo=Path(__file__).resolve().parents[1]
    if root.exists():raise ValueError('new corpus challenger required')
    parent=repo/'experiments/runs/packs/cycle14-seeds-v1'
    frozen=repo/'experiments/runs/packs/cycle18-clauses-v1/results.json'
    data=json.loads(frozen.read_text());assert data['status']=='COMPLETE'
    acquisition=repo/'experiments/runs/packs/cycle14-corpus-v1/acquisition.json'
    previous=json.loads(acquisition.read_text());assert previous['commit']==COMMIT
    root.mkdir(parents=True);source=root/'source';source.mkdir()
    manifest=[]
    for item in data['source_manifest']:
        body=(parent/'expanded-source'/item['path']).read_bytes();assert sha(body)==item['sha256']
        destination=(source/item['path']).resolve()
        if not destination.is_relative_to(source):raise ValueError('source path escapes corpus')
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(body)
        manifest.append(dict(item))
    def acquire(name):
        path='Doc/library/'+name+'.rst'
        url=f'https://raw.githubusercontent.com/python/cpython/{COMMIT}/{path}'
        with urllib.request.urlopen(url,timeout=30) as response:body=response.read()
        body.decode('utf-8')
        return {'path':'cpython/'+path,'sha256':sha(body),'bytes':len(body),'url':url},body
    with ThreadPoolExecutor(max_workers=3) as pool:acquired=list(pool.map(acquire,MANUALS))
    for item,body in acquired:
        path=source/item['path']
        assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        manifest.append(item)
    license_path=repo/'experiments/runs/packs/cycle14-corpus-v1/CPYTHON-LICENSE.txt'
    assert sha(license_path.read_bytes())==previous['license_sha256']
    shutil.copyfile(license_path,root/'CPYTHON-LICENSE.txt')
    record={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL',
            'generative_calls':0,'commit':COMMIT,'parent_acquisition_sha256':sha(acquisition.read_bytes()),
            'parent_results_sha256':sha(frozen.read_bytes()),'parent_pack_sha256':sha((parent/'expanded.npk').read_bytes()),
            'source_manifest':manifest,'added': [item for item,_ in acquired],
            'license_sha256':previous['license_sha256'],'question_definitions_unchanged':True,
            'hypothesis':'Exact-version API prose may supply missing semantics more effectively than extra query splitting',
            'limitations':['Three entire manuals chosen after observing current source omissions; not a sealed corpus choice',
                           'Same questions are known controls; existing required CODE spans do not measure equivalent documentation evidence',
                           'No target answers requested by this acquisition/compilation script',
                           'These are selected dependencies and manuals, not a complete Python execution environment']}
    dump(root/'acquisition.json',record)
    (root/'acquisition.sha256').write_text(sha((root/'acquisition.json').read_bytes()))
    current={f.relative_to(repo).as_posix():sha(f.read_bytes()) for f in (repo/'npk').rglob('*.py')}
    timings=[];rng=random.Random(1919);representations=[]
    with patch('socket.socket.connect', side_effect=AssertionError('LOCAL compilation attempted network')):
        for trial in range(3):
            methods=['full','incremental'];rng.shuffle(methods)
            for method in methods:
                pack=root/f'{method}-{trial}.npk'
                if method=='incremental':shutil.copyfile(parent/'expanded.npk',pack)
                started=time.perf_counter_ns();cpu=time.process_time_ns()
                stats=compile_pack(source,pack) if method=='full' else update_pack(pack,source)
                cpu_ms=(time.process_time_ns()-cpu)/1e6;wall_ms=(time.perf_counter_ns()-started)/1e6
                assert verify(pack)['ok']
                assert stats.files_indexed==(len(manifest) if method=='full' else len(MANUALS))
                if method=='incremental':assert stats.files_skipped_unchanged==len(data['source_manifest'])
                with open_pack(pack) as con:blocks=load_blocks(con)
                representation=[(b.path,b.ordinal,b.span,b.text) for b in blocks]
                representation.sort();representations.append(representation)
                assert all(r==representations[0] for r in representations)
                joined='\n\n'.join(b.text for b in blocks)
                timings.append({'trial':trial,'method':method,'wall_ms':wall_ms,'cpu_ms':cpu_ms,
                                'stats':stats.as_dict(),'pack_bytes':pack.stat().st_size,
                                'available_tokens':len(joined)//4,'blocks':len(blocks)})
                print({'trial':trial,'method':method,'wall_ms':wall_ms,'files_indexed':stats.files_indexed},flush=True)
        selectors={method:PackSelector(root/f'{method}-0.npk') for method in ('full','incremental')}
        checks=0
        for task in data['tasks']:
            for budget in data['budgets']:
                first=selectors['full'].select(task['question'],budget_tokens=budget)
                second=selectors['incremental'].select(task['question'],budget_tokens=budget)
                assert first.context_text()==second.context_text()
                assert [(e.path,e.span) for e in first.evidence]==[(e.path,e.span) for e in second.evidence]
                assert first.total_tokens==second.total_tokens<=budget
                assert first.query==second.query==task['question'];checks+=1
    assert current=={f.relative_to(repo).as_posix():sha(f.read_bytes()) for f in (repo/'npk').rglob('*.py')}
    dump(root/'compilation.json',{'evidence_mode':'LOCAL','generative_calls':0,'timings':timings,
        'candidate_source_sha256':current,'acquisition_sha256':sha((root/'acquisition.json').read_bytes()),
        'compiled_representation_checks':len(representations),'paired_query_checks':checks,
        'limitations':['Three shuffled repetitions; copy of the accepted base excluded from incremental timing',
                       'Source reads/hashes included; unchanged files skip parsing but the source scan is still linear',
                       'Full integrity checks and query equivalence measured outside compilation timings',
                       'No CPU tests or mutations overlapped; LIVE answer IO and uncontrolled host activity did',
                       'Compilation equivalence is not answer quality or evidence sufficiency']})
    print({'files':len(manifest),'new_manuals':len(MANUALS),'paired_queries':checks,'complete':True})


if __name__=='__main__':main()

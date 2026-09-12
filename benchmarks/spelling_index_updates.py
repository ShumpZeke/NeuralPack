"""Measure side-index updates separately from source compilation and copying."""
import argparse
from functools import partial
import hashlib
import importlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
import statistics
import time
from unittest.mock import patch
from benchmarks.boundary_retrieval import fixed_chars
from benchmarks.compiled_source_contract import require_compiled_sources
from benchmarks.prospective_eval import write_json
from benchmarks.spelling_index import update,open_index,normalized_rank,canonical_rank
from npk.pack import update_pack,verify
from npk.pack.compile import scan_source
from npk.pack.format import open_pack


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def equivalent(left,right):
    with sqlite3.connect(left) as a,sqlite3.connect(right) as b:
        for table in ('metadata','owners','locations','spellings','normalized'):
            n=len(a.execute('SELECT * FROM '+table+' LIMIT 0').description);order=','.join(map(str,range(1,n+1)))
            assert a.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall()==b.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--index-run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New frozen update run required')
    acquired=read(a.corpus/'acquisition.json');parent=read(a.parent/'results.json');indexed=read(a.index_run/'results.json')
    assert indexed['status']=='COMPLETE' and indexed['parent_results_sha256']==sha((a.parent/'results.json').read_bytes())
    original_pack=a.parent/'fixed2048.npk';original_index=a.index_run/'spelling.sqlite'
    assert sha(original_pack.read_bytes())==parent['corpora']['fixed2048']['pack_sha256']
    assert sha(original_index.read_bytes())==indexed['build']['index_sha256']
    files=sorted(acquired['source_manifest'],key=lambda item:item['sha256']);cases={'unchanged':0,'single_file':1,'one_percent':2,'ten_percent':16}
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,'cases':cases,'trials':3,'source_manifest':acquired['source_manifest'],
              'index_results_sha256':sha((a.index_run/'results.json').read_bytes()),
              'limitations':['Synthetic marker appended to complete public files; update-equivalence checks, not answer quality',
                             '1% and 10% rounded up to 2 and 16 of 153 files; case sets selected by source hash before timing',
                             'Source copies, core update and full validation lie outside side-index timing',
                             'Updated side index is compared to a fresh side index on the exact same updated .npk',
                             'Three shuffled repetitions; no concurrent agent benchmarks, tests, archive compression or LIVE IO; host load uncontrolled']}
    root.mkdir(parents=True);write_json(root/'manifest.json',manifest);write_json(root/'execution-sources.json',{n:(repo/n).read_bytes().decode() for n in code})
    source_manifests={};sources={}
    for case,count in cases.items():
        tree=root/case/'source';tree.mkdir(parents=True)
        for item in files:
            path=tree/item['path'];path.parent.mkdir(parents=True,exist_ok=True);body=(a.corpus/'source'/item['path']).read_bytes()
            assert sha(body)==item['sha256'];path.write_bytes(body)
        for i,item in enumerate(files[:count]):
            path=tree/item['path'];path.write_bytes(path.read_bytes()+f'\n\nCycle 26 LOCAL update fixture: ``npk_refresh_marker_{i:02d}``.\n'.encode())
        source_manifests[case]=[{'path':f.path,'sha256':f.sha256,'bytes':f.size,'language':f.language} for f in scan_source(tree)]
        sources[case]=tree
    write_json(root/'source-manifests.json',source_manifests)
    rows=[];rng=random.Random(2607);compiler=importlib.import_module('npk.pack.compile')
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL update experiment attempted network')):
        for trial in range(3):
            order=list(cases);rng.shuffle(order)
            for case in order:
                dest=root/case/str(trial);dest.mkdir();pack=dest/'project.npk';index=dest/'spelling.sqlite';fresh=dest/'fresh.sqlite'
                shutil.copyfile(original_pack,pack);shutil.copyfile(original_index,index)
                started=time.perf_counter_ns()
                with patch.object(compiler,'split_source',partial(fixed_chars,max_chars=2048)):core_stats=update_pack(pack,sources[case])
                core_ms=(time.perf_counter_ns()-started)/1e6
                assert verify(pack)['ok'];require_compiled_sources(pack,source_manifests[case])
                timings={};stats={}
                stages=['incremental','fresh'];rng.shuffle(stages)
                for stage in stages:
                    start=time.perf_counter_ns();cpu=time.process_time_ns()
                    stats[stage]=update(pack,index if stage=='incremental' else fresh,create=stage=='fresh')
                    timings[stage]={'wall_ms':(time.perf_counter_ns()-start)/1e6,'cpu_ms':(time.process_time_ns()-cpu)/1e6}
                assert stats['incremental']['files_changed']==cases[case] and stats['incremental']['files_reused']==153-cases[case]
                equivalent(index,fresh);queries=['retryBackoffMillis','HTTP status code','some other object','npkRefreshMarker00','expireOnCommit']
                checks=[]
                with open_pack(pack) as con,open_index(index,con) as left,open_index(fresh,con) as right:
                    for query in queries:
                        assert normalized_rank(left,query)==normalized_rank(right,query)
                        assert canonical_rank(left,query)==canonical_rank(right,query)
                        checks.append(query)
                row={'case':case,'trial':trial,'changed_files':cases[case],'core_update_ms':core_ms,'core_update_stats':core_stats.as_dict(),
                     'timing':timings,'stats':stats,'query_equivalence_checks':len(checks)*2,'queries':checks,
                     'pack_sha256':sha(pack.read_bytes()),'index_sha256':sha(index.read_bytes()),'fresh_sha256':sha(fresh.read_bytes()),
                     'updated_bytes':index.stat().st_size,'fresh_bytes':fresh.stat().st_size}
                rows.append(row);write_json(root/'observations.json',rows);print({'case':case,'trial':trial,'timing':timings,'files_reused':stats['incremental']['files_reused']},flush=True)
    summary=[]
    for case in cases:
        group=[r for r in rows if r['case']==case]
        summary.append({'case':case,'files_changed':cases[case],
                        'median_incremental_ms':statistics.median(r['timing']['incremental']['wall_ms'] for r in group),
                        'median_fresh_ms':statistics.median(r['timing']['fresh']['wall_ms'] for r in group),
                        'median_core_update_ms':statistics.median(r['core_update_ms'] for r in group)})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','source_manifests':source_manifests,'rows':rows,'summary':summary})
    print({'summary':summary,'paired_query_checks':sum(r['query_equivalence_checks'] for r in rows)},flush=True)


if __name__=='__main__':main()

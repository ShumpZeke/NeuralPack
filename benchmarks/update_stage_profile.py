"""LOCAL update cost breakdown on exact public source, before designing a delta API."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib
import json
import math
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.prospective_eval import write_json
from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import open_pack, load_blocks


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manuals',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1]
    root=a.output.resolve()
    if root.exists():raise ValueError('New profile directory required')
    acquisition=read(a.manuals/'acquisition.json');base=a.manuals/'full-0.npk';assert verify(base)['ok']
    sources=acquisition['source_manifest'];root.mkdir(parents=True)
    for item in sources:assert sha((a.manuals/'source'/item['path']).read_bytes())==item['sha256']
    names=sorted(x['path'] for x in sources);total=len(names)
    cases={'no_change':0,'one_file':1,'one_percent':max(1,math.ceil(total*.01)),'ten_percent':max(1,math.ceil(total*.1))}
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,
              'profiler_sha256':sha(Path(__file__).read_bytes()),'parent_acquisition_sha256':sha((a.manuals/'acquisition.json').read_bytes()),
              'base_pack_sha256':sha(base.read_bytes()),'source_manifest':sources,'cases':cases,
              'edit_suffix':'\n# NeuralPack LOCAL update-stage profile edit\n',
              'limitations':['Instrumented wall times, three shuffled repetitions on one machine',
                  'Pack/source copying and full verification are outside update timings',
                  'No CPU tests, mutations or archive compression overlap; LIVE IO and uncontrolled host activity may',
                  'No changed-path implementation is present; removing scan time is only an optimistic bound',
                  'Warm filesystem and cache effects; no cold-cache or answer-quality claim']}
    write_json(root/'manifest.json',manifest);module=importlib.import_module('npk.pack.compile')
    prepared={};queries=['ChainMap','partialmethod','ExitStack','Counter','singledispatch'];rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL profile attempted network')):
        for name,count in cases.items():
            source=root/name/'source';shutil.copytree(a.manuals/'source',source)
            for path in names[:count]:
                target=source/path;target.write_bytes(target.read_bytes()+manifest['edit_suffix'].encode())
            prepared[name]=source
            # A separate complete rebuild supplies the equivalence reference.
            reference=root/name/'reference.npk';compile_pack(source,reference);assert verify(reference)['ok']
        rng=random.Random(2109)
        for trial in range(3):
            order=list(cases);rng.shuffle(order)
            for name in order:
                path=root/name/f'update-{trial}.npk';shutil.copyfile(base,path);stage={}
                def wrapper(label,original):
                    def call(*args,**kwargs):
                        start=time.perf_counter_ns()
                        try:return original(*args,**kwargs)
                        finally:stage[label]=stage.get(label,0)+(time.perf_counter_ns()-start)/1e6
                    return call
                with ExitStack() as stack:
                    for function in ('scan_source','check_cached_base','_write_file_blocks','_available_tokens','_seal'):
                        original=getattr(module,function);stack.enter_context(patch.object(module,function,wrapper(function,original)))
                    start=time.perf_counter_ns();cpu=time.process_time_ns()
                    stats=update_pack(path,prepared[name]);cpu_ms=(time.process_time_ns()-cpu)/1e6
                    elapsed=(time.perf_counter_ns()-start)/1e6
                assert stats.files_indexed==cases[name] and stats.files_removed==0 and verify(path)['ok']
                with open_pack(path) as con:blocks=load_blocks(con)
                with open_pack(root/name/'reference.npk') as con:expected=load_blocks(con)
                representation=lambda bs:sorted((b.path,b.ordinal,b.span,b.text) for b in bs)
                assert representation(blocks)==representation(expected)
                for query in queries:
                    chosen=PackSelector(path).select(query,budget_tokens=2048)
                    reference=PackSelector(root/name/'reference.npk').select(query,budget_tokens=2048)
                    assert chosen.context_text()==reference.context_text() and chosen.total_tokens==reference.total_tokens<=2048
                    assert [(e.path,e.span) for e in chosen.evidence]==[(e.path,e.span) for e in reference.evidence]
                row={'trial':trial,'case':name,'changed_files':cases[name],'changed_file_fraction':cases[name]/total,
                     'wall_ms':elapsed,'cpu_ms':cpu_ms,'stage_ms':stage,'remainder_ms':elapsed-sum(stage.values()),
                     'available_tokens':len('\n\n'.join(b.text for b in blocks))//4,'blocks':len(blocks),
                     'pack_bytes':path.stat().st_size,'stats':stats.as_dict(),'query_equivalence_checks':len(queries)}
                rows.append(row);print({k:row[k] for k in ('case','trial','wall_ms','stage_ms')},flush=True)
    assert code=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    summary=[]
    for name in cases:
        group=[r for r in rows if r['case']==name]
        fractions=[r['stage_ms']['scan_source']/r['wall_ms'] for r in group]
        summary.append({'case':name,'median_wall_ms':statistics.median(r['wall_ms'] for r in group),
                        'median_scan_ms':statistics.median(r['stage_ms']['scan_source'] for r in group),
                        'median_scan_fraction':statistics.median(fractions),
                        'median_ideal_scan_elimination_speedup':statistics.median(1/(1-f) for f in fractions)})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'summary':summary})
    print({'complete':True,'summary':summary})


if __name__=='__main__':main()

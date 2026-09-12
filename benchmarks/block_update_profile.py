"""LOCAL cost and reusable-block counts for small edits in large public files.

Single-file artifacts isolate file-local work. This is neither a repository-scale
update benchmark nor an answer-quality test. No changed-block updater is installed.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import importlib
import json
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.prospective_eval import write_json
from npk.pack import compile_pack,update_pack,verify,PackSelector
from npk.pack.compile import split_source,TEXT_SUFFIXES
from npk.pack.format import open_pack,load_blocks


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def signature(b):return (b.kind,b.name,b.text)


def edit(body,kind,language):
    # Deliberately preserve original bytes, except the declared append/insert.
    marker=b'\n/* NeuralPack LOCAL small edit */\n' if language=='c' else b'\n# NeuralPack LOCAL small edit\n'
    if language=='rst':marker=b'\n.. NeuralPack LOCAL small edit\n'
    if kind=='append':return body+marker
    if kind=='prepend_blank':return b'\n'+body
    raise ValueError('Unknown edit')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1]
    root=a.output.resolve()
    if root.exists():raise ValueError('New profile directory required')
    acquisition=read(a.corpus/'acquisition.json');root.mkdir(parents=True)
    compiler=importlib.import_module('npk.pack.compile');conflict=importlib.import_module('npk.pack.conflict')
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,
              'profiler_sha256':sha(Path(__file__).read_bytes()),'acquisition_sha256':sha((a.corpus/'acquisition.json').read_bytes()),
              'source_manifest':acquisition['source_manifest'],'trials':3,
              'limitations':['Three selected single-file artifacts, not whole repositories',
                  'Same unchanged compiler; stage elimination is hypothetical, not a measured challenger',
                  'Some stage times are nested; write_residual subtracts split and assignment work',
                  'Fresh reference builds, source/pack copying and full verification are outside update timing',
                  'Warm filesystem, three shuffled trials on one host; no other agent CPU workload or LIVE calls overlap',
                  'Source-derived queries only verify compilation equivalence, not answer quality']}
    write_json(root/'manifest.json',manifest);cases=[];results=[]
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL profile attempted network')):
        for i,item in enumerate(acquisition['source_manifest']):
            raw=(a.corpus/'source'/item['path']).read_bytes();assert sha(raw)==item['sha256']
            filename=Path(item['path']).name;language=TEXT_SUFFIXES[Path(filename).suffix]
            case_root=root/f'file-{i}';source=case_root/'base-source';source.mkdir(parents=True)
            (source/filename).write_bytes(raw);base=case_root/'base.npk';compile_pack(source,base);assert verify(base)['ok']
            old=split_source(raw.decode(),language);old_counts=Counter(map(signature,old))
            queries=sorted({name for b in old for name,_,is_def in b.symbols if is_def})[:5]
            if not queries:queries=sorted({name for b in old for name,_,_ in b.symbols})[:5]
            assert len(queries)==5
            for kind in ('append','prepend_blank'):
                changed=edit(raw,kind,language);new=split_source(changed.decode(),language)
                new_counts=Counter(map(signature,new));reusable=sum((old_counts&new_counts).values())
                dest=case_root/kind/'source';dest.mkdir(parents=True);(dest/filename).write_bytes(changed)
                reference=case_root/kind/'reference.npk';compile_pack(dest,reference);assert verify(reference)['ok']
                with open_pack(reference) as con:blocks=load_blocks(con)
                expected=sorted((b.path,b.ordinal,b.span,b.text) for b in blocks)
                cases.append({'file':item['path'],'source':str(dest),'base':str(base),'reference':str(reference),
                              'case':kind,'queries':queries,'expected':expected,'old_blocks':len(old),'new_blocks':len(new),
                              'reusable_content_blocks':reusable,'byte_source_sha256':sha(changed),
                              'source_bytes':len(changed),'available_tokens':len('\n\n'.join(b.text for b in blocks))//4})
        rng=random.Random(2209)
        for trial in range(3):
            order=list(cases);rng.shuffle(order)
            for case in order:
                dest=Path(case['reference']).with_name(f'update-{trial}.npk');shutil.copyfile(case['base'],dest)
                stages={};calls={}
                def wrapper(label,original):
                    def call(*args,**kwargs):
                        start=time.perf_counter_ns();calls[label]=calls.get(label,0)+1
                        try:return original(*args,**kwargs)
                        finally:stages[label]=stages.get(label,0)+(time.perf_counter_ns()-start)/1e6
                    return call
                with ExitStack() as stack:
                    for module,names in ((compiler,('scan_source','check_cached_base','_drop_file','_write_file_blocks','split_source','_available_tokens','_seal')),
                                         (conflict,('extract_assignments',))):
                        for name in names:stack.enter_context(patch.object(module,name,wrapper(name,getattr(module,name))))
                    start=time.perf_counter_ns();cpu=time.process_time_ns();stats=update_pack(dest,case['source'])
                    cpu_ms=(time.process_time_ns()-cpu)/1e6;elapsed=(time.perf_counter_ns()-start)/1e6
                assert stats.files_indexed==1 and stats.files_removed==0 and verify(dest)['ok']
                with open_pack(dest) as con:blocks=load_blocks(con)
                assert sorted((b.path,b.ordinal,b.span,b.text) for b in blocks)==case['expected']
                for query in case['queries']:
                    first=PackSelector(dest).select(query,budget_tokens=2048)
                    second=PackSelector(case['reference']).select(query,budget_tokens=2048)
                    assert first.context_text()==second.context_text() and first.total_tokens==second.total_tokens<=2048
                    assert [(e.path,e.span) for e in first.evidence]==[(e.path,e.span) for e in second.evidence]
                residual=stages['_write_file_blocks']-stages['split_source']-stages['extract_assignments'];assert residual>=0
                row={k:v for k,v in case.items() if k not in ('source','base','reference','expected')}
                row.update(trial=trial,wall_ms=elapsed,cpu_ms=cpu_ms,stage_ms=stages,stage_calls=calls,
                           write_residual_ms=residual,stats=stats.as_dict(),query_equivalence_checks=len(case['queries']))
                results.append(row);print({k:row[k] for k in ('file','case','trial','wall_ms','write_residual_ms','reusable_content_blocks','new_blocks')},flush=True)
    assert code=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    summary=[]
    for case in cases:
        group=[r for r in results if r['file']==case['file'] and r['case']==case['case']]
        summary.append({'file':case['file'],'case':case['case'],'old_blocks':case['old_blocks'],'new_blocks':case['new_blocks'],
                        'reusable_content_blocks':case['reusable_content_blocks'],'available_tokens':case['available_tokens'],
                        'median_wall_ms':statistics.median(r['wall_ms'] for r in group),
                        'median_stage_ms':{name:statistics.median(r['stage_ms'][name] for r in group) for name in group[0]['stage_ms']},
                        'median_write_residual_ms':statistics.median(r['write_residual_ms'] for r in group)})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','rows':results,'summary':summary})
    print({'complete':True,'summary':summary})


if __name__=='__main__':main()

"""Matched LOCAL updates combining frozen boundaries and exact-row reuse."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.block_reuse import update_reused
from benchmarks.boundary_retrieval import methods
from benchmarks.line_anchor_gate import edit
from benchmarks.prospective_eval import write_json
from npk.pack import compile_pack,update_pack,verify,PackSelector
from npk.pack.format import open_pack,load_blocks


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def representation(pack):
    with open_pack(pack) as con:
        return [(b.path,b.ordinal,b.span,b.kind,b.name,b.text) for b in load_blocks(con)]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--retrieval',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New comparison directory required')
    parent=read(a.retrieval/'results.json');assert parent['status']=='COMPLETE'
    for name,digest in parent['code_sha256'].items():assert sha((repo/name).read_bytes())==digest
    original={item['path']:(a.source/item['path']).read_bytes() for item in parent['source_manifest']}
    for item in parent['source_manifest']:assert sha(original[item['path']])==item['sha256']
    root.mkdir(parents=True);candidates=methods();sources={};source_manifests={}
    for kind in ('prepend_blank','one_percent'):
        source=root/kind/'source';sources[kind]=source;source_manifests[kind]=[]
        for item in parent['source_manifest']:
            body=edit(original[item['path']].decode(),kind,item['language']).encode()
            path=source/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            source_manifests[kind].append({'path':item['path'],'sha256':sha(body)})
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,'trials':3,
              'parent_results_sha256':sha((a.retrieval/'results.json').read_bytes()),'methods':list(candidates),
              'updaters':['baseline','reuse'],'source_manifests':source_manifests,
              'queries':[t['question'] for t in parent['tasks']],
              'limitations':['Same five public files; both edits change all five files, not repository percentage claims',
                             'one_percent edits approximately 1% of physical lines per file',
                             'Source copy, artifact copy, reference builds and verification are outside update timing',
                             'Three shuffled trials with no overlapping agent tests, compression or LIVE calls; host load uncontrolled',
                             'Research helper patches are single-threaded, deterministic and graph-free only',
                             'Reference-query equivalence is not answer quality']}
    write_json(root/'manifest.json',manifest);compiler=importlib.import_module('npk.pack.compile');references={};rows=[];rng=random.Random(2331)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL update comparison attempted network')):
        for name,fn in candidates.items():
            assert verify(a.retrieval/f'{name}-0.npk')['ok']
            for kind,source in sources.items():
                ref=root/kind/(name+'-reference.npk')
                with patch.object(compiler,'split_source',fn):compile_pack(source,ref)
                assert verify(ref)['ok']
                reference_answers=[]
                for question in manifest['queries']:
                    sel=PackSelector(ref).select(question,budget_tokens=512)
                    reference_answers.append((sel.context_text(),sel.total_tokens,[(e.path,e.span) for e in sel.evidence]))
                references[(name,kind)]=(representation(ref),reference_answers)
        for trial in range(3):
            order=[(name,kind,updater) for name in candidates for kind in sources for updater in manifest['updaters']];rng.shuffle(order)
            for name,kind,updater in order:
                dest=root/f'{name}-{kind}-{updater}-{trial}.npk';shutil.copyfile(a.retrieval/f'{name}-0.npk',dest)
                with patch.object(compiler,'split_source',candidates[name]):
                    start=time.perf_counter_ns();cpu=time.process_time_ns()
                    if updater=='reuse':stats,counts=update_reused(dest,sources[kind])
                    else:stats=update_pack(dest,sources[kind]);counts={'reused_blocks':0,'new_blocks':stats.blocks}
                    cpu_ms=(time.process_time_ns()-cpu)/1e6;wall_ms=(time.perf_counter_ns()-start)/1e6
                assert stats.files_indexed==5 and verify(dest)['ok']
                expected,answers=references[(name,kind)];assert representation(dest)==expected
                for question,answer in zip(manifest['queries'],answers,strict=True):
                    sel=PackSelector(dest).select(question,budget_tokens=512)
                    assert (sel.context_text(),sel.total_tokens,[(e.path,e.span) for e in sel.evidence])==answer
                row={'method':name,'case':kind,'updater':updater,'trial':trial,'wall_ms':wall_ms,'cpu_ms':cpu_ms,
                     'pack_bytes':dest.stat().st_size,'stats':stats.as_dict(),'query_equivalence_checks':len(answers),**counts}
                rows.append(row)
            print({'trial':trial,'completed_updates':len(rows)},flush=True)
    assert code=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    summary=[]
    for name in candidates:
        for kind in sources:
            group=[r for r in rows if r['method']==name and r['case']==kind]
            medians={updater:statistics.median(r['wall_ms'] for r in group if r['updater']==updater) for updater in manifest['updaters']}
            summary.append({'method':name,'case':kind,'median_ms':medians,'ratio_of_medians':medians['baseline']/medians['reuse'],
                            'reused_blocks':next(r['reused_blocks'] for r in group if r['updater']=='reuse')})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'summary':summary})
    print({'complete':True,'summary':summary})


if __name__=='__main__':main()

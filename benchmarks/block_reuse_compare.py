"""Matched update comparison for a contained identical-block reuse challenger."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.block_reuse import update_reused
from benchmarks.prospective_eval import write_json
from npk.pack import update_pack,verify,PackSelector
from npk.pack.format import open_pack,load_blocks


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1]
    root=a.output.resolve()
    if root.exists():raise ValueError('New comparison directory required')
    parent=read(a.profile/'results.json');assert parent['status']=='COMPLETE';root.mkdir(parents=True)
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')};assert code==parent['code_sha256']
    adapters={name:sha((repo/'benchmarks'/name).read_bytes()) for name in ('block_reuse.py','block_reuse_compare.py')}
    cases=[]
    for i,item in enumerate(parent['source_manifest']):
        for kind in ('append','prepend_blank'):
            old=next(r for r in parent['rows'] if r['file']==item['path'] and r['case']==kind)
            folder=a.profile/f'file-{i}'/kind;source=folder/'source'
            assert sha((source/Path(item['path']).name).read_bytes())==old['byte_source_sha256']
            reference=folder/'reference.npk';assert verify(reference)['ok']
            with open_pack(reference) as con:blocks=load_blocks(con)
            cases.append({'file':item['path'],'case':kind,'base':a.profile/f'file-{i}'/'base.npk',
                          'source':source,'reference':reference,'expected':sorted((b.path,b.ordinal,b.span,b.kind,b.name,b.text) for b in blocks),
                          'queries':old['queries'],'available_tokens':old['available_tokens'],
                          'source_bytes':old['source_bytes'],'byte_source_sha256':old['byte_source_sha256']})
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,'adapter_sha256':adapters,
              'parent_results_sha256':sha((a.profile/'results.json').read_bytes()),'trials':5,
              'limitations':['Experimental single-threaded adapter, not a shipped compiler path',
                  'Only deterministic graph-free artifacts; no semantic encoder or dependency update claim',
                  'Same source, chunk boundaries and output caps for both update methods',
                  'Single-file artifacts, warm filesystem, five shuffled repetitions on one host',
                  'Copying and full validation are outside update timing; no other agent CPU work or LIVE calls overlap',
                  'Source-derived queries test equivalence, not answer quality']}
    write_json(root/'manifest.json',manifest);rng=random.Random(2299);rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL comparison attempted network')):
        for trial in range(5):
            order=[(i,method) for i in range(len(cases)) for method in ('baseline','reuse')];rng.shuffle(order)
            for i,method in order:
                case=cases[i];dest=root/f'{i}-{trial}-{method}.npk';shutil.copyfile(case['base'],dest)
                start=time.perf_counter_ns();cpu=time.process_time_ns()
                if method=='baseline':stats=update_pack(dest,case['source']);metrics={'reused_blocks':0,'new_blocks':stats.blocks}
                else:stats,metrics=update_reused(dest,case['source'])
                cpu_ms=(time.process_time_ns()-cpu)/1e6;elapsed=(time.perf_counter_ns()-start)/1e6
                assert verify(dest)['ok'] and stats.files_indexed==1 and stats.files_removed==0
                with open_pack(dest) as con:
                    blocks=load_blocks(con)
                    assert not con.execute("SELECT 1 FROM files WHERE path LIKE '__npk_research_pending_%'").fetchall()
                assert sorted((b.path,b.ordinal,b.span,b.kind,b.name,b.text) for b in blocks)==case['expected']
                for query in case['queries']:
                    first=PackSelector(dest).select(query,budget_tokens=2048)
                    second=PackSelector(case['reference']).select(query,budget_tokens=2048)
                    assert first.context_text()==second.context_text() and first.total_tokens==second.total_tokens<=2048
                    assert [(e.path,e.span) for e in first.evidence]==[(e.path,e.span) for e in second.evidence]
                row={k:v for k,v in case.items() if k not in ('base','source','reference','expected')}
                row.update(trial=trial,method=method,wall_ms=elapsed,cpu_ms=cpu_ms,stats=stats.as_dict(),
                           pack_bytes=dest.stat().st_size,query_equivalence_checks=len(case['queries']),**metrics)
                rows.append(row);print({k:row[k] for k in ('file','case','method','trial','wall_ms','reused_blocks','new_blocks')},flush=True)
    assert code=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert adapters=={name:sha((repo/'benchmarks'/name).read_bytes()) for name in adapters}
    summary=[]
    for case in cases:
        group=[r for r in rows if r['file']==case['file'] and r['case']==case['case']]
        medians={method:statistics.median(r['wall_ms'] for r in group if r['method']==method) for method in ('baseline','reuse')}
        summary.append({'file':case['file'],'case':case['case'],'available_tokens':case['available_tokens'],
                        'median_ms':medians,'ratio_of_medians':medians['baseline']/medians['reuse'],
                        'reused_blocks':next(r['reused_blocks'] for r in group if r['method']=='reuse')})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'summary':summary})
    print({'complete':True,'summary':summary})


if __name__=='__main__':main()

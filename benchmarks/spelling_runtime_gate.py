"""Verify the promoted spelling implementation and profile six real source sizes."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.prospective_eval import write_json
from benchmarks.unit_passages import select as shared_select
from benchmarks.unit_answer_plan import reconstruct
from benchmarks.compiled_source_contract import require_compiled_sources
from npk.pack import compile_pack,verify,PackSelector
from npk.pack.compile import estimate_tokens,_source_lines
from npk.pack.format import open_pack,read_manifest
from npk.pack.select import _content_terms


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--spelling',type=Path,required=True);p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New frozen implementation gate required')
    acquired=read(a.corpus/'acquisition.json');spelling=read(a.spelling/'results.json');parent=read(a.parent/'results.json')
    assert spelling['status']==parent['status']=='COMPLETE'
    assert spelling['parent_results_sha256']==sha((a.parent/'results.json').read_bytes())
    source={}
    for item in acquired['source_manifest']:
        body=(a.corpus/'source'/item['path']).read_bytes();assert sha(body)==item['sha256']
        source[item['path']]=_source_lines(body.decode())
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'code_sha256':code,'source_manifest':acquired['source_manifest'],
              'spelling_results_sha256':sha((a.spelling/'results.json').read_bytes()),'parent_results_sha256':sha((a.parent/'results.json').read_bytes()),
              'profile_sizes':[2000,25000,50000,100000,250000,528000],'profile_trials':3,
              'source_selection':'Accumulate complete source files in ascending byte-size/path order until target chars/4 estimate is reached, or exhaust all 153 files',
              'limitations':['Lookup and runtime checks, not answer quality; no new target calls',
                             'Runtime baseline disables only the new lexical-term helper; same assembly, corpus, budget and process',
                             'Compiled profile uses default block splitting at every scale; initial builds have one observation each',
                             'Full manifest verification, source copies and compilation lie outside timed queries',
                             'Host load uncontrolled; no concurrent agent tests, model calls, archive compression or CPU benchmarks']}
    root.mkdir(parents=True);write_json(root/'manifest.json',manifest)
    write_json(root/'execution-sources.json',{name:(repo/name).read_bytes().decode() for name in code})
    matched=[];behavior=[];profiles=[];rng=random.Random(2502)
    with patch('socket.socket.connect',side_effect=AssertionError('Runtime gate attempted network')):
        pack=a.parent/'fixed2048.npk';assert sha(pack.read_bytes())==spelling['artifact_hashes']['lexical']
        tasks={t['id']:t for t in spelling['tasks']}
        for row in spelling['unique']:
            if row['method']!='vocabulary_split':continue
            expected=reconstruct(row,source)[1]
            selected=shared_select(pack,tasks[row['task']]['query'],row['budget'])
            assert selected.context_text()==expected and selected.query==tasks[row['task']]['query']
            matched.append({'task':row['task'],'budget':row['budget'],'context_sha256':sha(expected.encode())})
        assert len(matched)==192
        originals={t['id']:t for t in parent['tasks']}
        for row in parent['unique']:
            if row['method']!='shared_bm25':continue
            selected=shared_select(pack,originals[row['task']]['question'],row['budget'])
            expected=reconstruct(row,source)[1]
            behavior.append({'task':row['task'],'budget':row['budget'],'unchanged':selected.context_text()==expected,
                             'old_context_sha256':row['context_sha256'],'new_context_sha256':sha(selected.context_text().encode())})
        write_json(root/'equivalence.json',{'prototype_cells':matched,'original_behavior_cells':behavior})
        queries=[('alias',q) for q in ['configureMappers','skipAutocommitRollback','comparatorFactory','selectFrom']]
        queries += [('native',q) for q in ['configure_mappers','skip_autocommit_rollback','comparator_factory','select_from']]
        queries += [('behavior',t['question']) for t in parent['tasks'][:4]]
        for size in manifest['profile_sizes']:
            case=root/str(size);tree=case/'source';tree.mkdir(parents=True);chosen=[];body_size=0
            for item in sorted(acquired['source_manifest'],key=lambda x:(x['bytes'],x['path'])):
                target=tree/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.corpus/'source'/item['path'],target)
                chosen.append(item);body_size+=len('\n'.join(source[item['path']]))+2
                if body_size//4>=size:break
            artifact=case/'project.npk';start=time.perf_counter_ns();stats=compile_pack(tree,artifact)
            compile_ms=(time.perf_counter_ns()-start)/1e6
            assert verify(artifact)['ok'];require_compiled_sources(artifact,chosen)
            with open_pack(artifact) as con:metadata=read_manifest(con)
            rows=[]
            for trial in range(3):
                cells=[(method,kind,query) for method in ('previous','vocabulary') for kind,query in queries];rng.shuffle(cells)
                for method,kind,query in cells:
                    start=time.perf_counter_ns()
                    if method=='previous':
                        with patch('npk.pack.select._lexical_terms',lambda con,q:_content_terms(q)):
                            result=PackSelector(artifact).select(query,budget_tokens=2048)
                    else:result=PackSelector(artifact).select(query,budget_tokens=2048)
                    elapsed=(time.perf_counter_ns()-start)/1e6
                    assert result.query==query and not result.used_generative_llm and result.total_tokens<=2048
                    rows.append({'trial':trial,'method':method,'kind':kind,'query':query,'latency_ms':elapsed,
                                 'selected_tokens':result.total_tokens,'fallback':result.seed_failed or not result.evidence,
                                 'context_sha256':sha(result.context_text().encode()),'available_tokens':result.available_tokens})
            profile={'requested_size':size,'corpus_tokens':body_size//4,'available_tokens':int(metadata['available_tokens']),
                     'source_manifest':chosen,'compile_ms':compile_ms,'compile_stats':stats.as_dict(),'artifact_sha256':sha(artifact.read_bytes()),
                     'artifact_bytes':artifact.stat().st_size,'rows':rows,'summary':[]}
            for kind in ('alias','native','behavior'):
                for method in ('previous','vocabulary'):
                    group=[r for r in rows if r['kind']==kind and r['method']==method]
                    profile['summary'].append({'kind':kind,'method':method,'observations':len(group),
                                               'median_ms':statistics.median(r['latency_ms'] for r in group),
                                               'fallbacks':sum(r['fallback'] for r in group)})
            profiles.append(profile);write_json(root/'profile.json',profiles)
            print({'size':size,'available':profile['available_tokens'],'compile_ms':compile_ms,'summary':profile['summary']},flush=True)
    result={**manifest,'status':'COMPLETE','prototype_cells':matched,'original_behavior_cells':behavior,'profiles':profiles}
    write_json(root/'results.json',result);print({'prototype_cells':len(matched),'unchanged_behavior_cells':sum(r['unchanged'] for r in behavior),'total_behavior_cells':len(behavior)},flush=True)


if __name__=='__main__':main()

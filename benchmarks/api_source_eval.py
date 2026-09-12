"""Frozen matched-budget corpus comparison; full original queries, no LLM optimization."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import time
from unittest.mock import patch
from benchmarks.boundary_retrieval import fixed_chars
from benchmarks.compiled_source_contract import require_compiled_sources
from benchmarks.evidence_diagnostics import Piece,render,validate_pieces,from_evidence
from benchmarks.operation_seeds import rank
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from benchmarks.unit_answer_plan import reconstruct,tokens
from benchmarks.unit_passages import select
from npk.pack import compile_pack,update_pack,verify
from npk.pack.compile import _source_lines
from npk.pack.format import open_pack,load_blocks,read_manifest


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def uniform_source(text,language,*,python_members=False):
    # Same physical-line character policy for BOTH manual and added code.
    # Reuses the established splitter, with literal symbols/provenance intact.
    return fixed_chars(text,'text',max_chars=2048)


def region_counts(pieces,docstrings):
    seen={}
    for p in pieces:seen.setdefault(p.path,set()).update(range(p.start,p.end+1))
    code_lines=sum(len(lines) for path,lines in seen.items() if path.endswith('.py'))
    docs={}
    for item in docstrings:
        path=item['path']
        if path in seen:docs.setdefault(path,set()).update(set(range(item['span'][0],item['span'][1]+1)) & seen[path])
    return {'selected_api_source_lines':code_lines,'selected_api_docstring_lines':sum(map(len,docs.values()))}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','parent-local','parent-packs','new-tasks','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--phase',choices=['build','query'],required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];root=a.output.resolve();source=a.corpus/'source';acquired=read(a.corpus/'acquisition.json')
    parent=read(a.parent_local/'results.json');original=read(a.parent_packs/'results.json');oracle=read(a.new_tasks)
    files={name.removeprefix('source/'):body for name,body in manifest_sources(source,acquired['source_manifest'],'source').items()}
    sources={name:_source_lines(body.decode()) for name,body in files.items()}
    assert acquired['parent_acquisition_sha256']==original['acquisition_sha256']
    assert sha((repo/'benchmarks/api_behavior_oracles.py').read_bytes())==oracle['oracle_source_sha256']
    tasks=[{**t,'cohort':'known_scenarios'} for t in parent['tasks'] if t['layout']=='original']
    tasks += [{**t,'id':t['id']+'-original','base_task':t['id'],'layout':'original','cohort':'new_scenarios','required':None} for t in oracle['tasks']]
    assert len(tasks)==30 and len({t['id'] for t in tasks})==30
    manual_manifest=parent['source_manifest'];all_manifest=acquired['source_manifest']
    assert all(files[r['path']] for r in manual_manifest)
    for item in manual_manifest:assert sha(files[item['path']])==item['sha256']
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    compiler=importlib.import_module('npk.pack.compile')
    if a.phase=='build':
        if root.exists():raise ValueError('New build directory required')
        root.mkdir(parents=True);(root/'contexts').mkdir()
        plan={'evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'budgets':[1024,2048,4096],'methods':['bm25','hybrid'],
              'trials':3,'code_sha256':code,'source_manifests':{'manuals':manual_manifest,'expanded':all_manifest},
              'acquisition_sha256':sha((a.corpus/'acquisition.json').read_bytes()),'oracle_sha256':sha(a.new_tasks.read_bytes()),
              'parent_results_sha256':sha((a.parent_local/'results.json').read_bytes()),'parent_compilation_sha256':sha((a.parent_packs/'compilation.json').read_bytes()),
              'splitter':'uniform_source: physical-line character windows capped at 2048 characters except indivisible lines',
              'limitations':['30 developer-authored scenarios in one known public library; ten new, not sealed independent evaluation',
                             'Identical query/ranking/assembly and character-window policy; adding source changes the candidate universe and term statistics',
                             'Old manual annotations remain source-only diagnostics; new scenarios have no completeness annotation, never automatic success for empty labels',
                             'Source docstrings are literal Python text, not executed or expanded Sphinx pages',
                             'Research selector, not shipped PackSelector; full original query and system survive',
                             'One measured build per configuration; query medians use three shuffled repetitions with uncontrolled host load',
                             'Both corpora use actual cached local MiniLM where specified; zero generative or API optimizer calls']}
        write_json(root/'manifest.json',plan);write_json(root/'execution-sources-build.json',{name:(repo/name).read_bytes().decode() for name in code})
        builds={};corpora={}
        with patch('socket.socket.connect',side_effect=AssertionError('LOCAL compilation attempted network')):
            import psutil
            for cohort in ('manuals','expanded'):
                manifest=plan['source_manifests'][cohort]
                raw='\n\n'.join(files[item['path']].decode() for item in manifest)
                for mode,parent_name in (('deterministic','fixed2048'),('semantic','semantic2048')):
                    key=cohort+'_'+mode;pack=root/(key+'.npk')
                    if cohort=='manuals':
                        src=a.parent_packs/(parent_name+'.npk');assert sha(src.read_bytes())==original['corpora'][parent_name]['pack_sha256']
                        shutil.copyfile(src,pack);builds[key]={'reused':True,'origin':original['builds'][parent_name],
                                                           'note':'Historical build measurement; no new compilation timing'}
                    else:
                        # Reuse original manual rows and embeddings; add only new source.
                        shutil.copyfile(root/('manuals_'+mode+'.npk'),pack)
                        if mode=='semantic':
                            import torch
                            torch.set_num_threads(2)
                        rss=psutil.Process().memory_info().rss;start=time.perf_counter_ns();cpu=time.process_time_ns()
                        with patch.object(compiler,'split_source',uniform_source):stats=update_pack(pack,source)
                        elapsed=(time.perf_counter_ns()-start)/1e6;cpu_ms=(time.process_time_ns()-cpu)/1e6
                        assert stats.files_indexed==acquired['added_python_files'] and stats.files_skipped_unchanged==acquired['manual_files']
                        builds[key]={'reused':False,'operation':'incremental_add_library','wall_ms':elapsed,'cpu_ms':cpu_ms,
                                     'rss_before':rss,'rss_after':psutil.Process().memory_info().rss,'stats':stats.as_dict()}
                    assert verify(pack)['ok'];require_compiled_sources(pack,manifest)
                    with open_pack(pack) as con:blocks=load_blocks(con);metadata=read_manifest(con)
                    validate_pieces(source,[from_evidence(b) for b in blocks])
                    corpora[key]={'source_files':len(manifest),'blocks':len(blocks),'corpus_tokens':tokens(raw),
                                  'available_tokens':int(metadata['available_tokens']),'pack_sha256':sha(pack.read_bytes()),'pack_bytes':pack.stat().st_size,
                                  'encoder_identity':json.loads(metadata['encoder_identity']) if metadata.get('encoder_identity') else None}
                    write_json(root/'compilation.json',{'builds':builds,'corpora':corpora})
                    print({'built':key,**builds[key],**corpora[key]},flush=True)
        assert all(sha((repo/name).read_bytes())==digest for name,digest in code.items())
        return
    plan=read(root/'manifest.json');compilation=read(root/'compilation.json')
    assert tasks==plan['tasks'] and acquired['source_manifest']==plan['source_manifests']['expanded']
    assert set(compilation['corpora'])=={c+'_'+m for c in ('manuals','expanded') for m in ('deterministic','semantic')}
    assert all(sha((repo/name).read_bytes())==digest for name,digest in plan['code_sha256'].items())
    if (root/'results.json').exists() or (root/'observations.json').exists():raise ValueError('Query run already started; inspect its handle before any new run')
    packs={k:root/(k+'.npk') for k in compilation['corpora']}
    for name,pack in packs.items():assert sha(pack.read_bytes())==compilation['corpora'][name]['pack_sha256']
    details=read(a.corpus/'source-inventory.json');full={}
    for cohort,manifest in plan['source_manifests'].items():
        full[cohort]=render([Piece(item['path'],1,len(sources[item['path']]),'\n'.join(sources[item['path']])) for item in manifest],True)
    write_json(root/'execution-sources-query.json',{name:(repo/name).read_bytes().decode() for name in code})
    rows=[];rng=random.Random(2809)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL query attempted network')):
        import torch
        from npk.context.embedding import get_backend
        torch.set_num_threads(2);backend=get_backend();assert backend.available()
        assert backend.identity()==compilation['corpora']['expanded_semantic']['encoder_identity']
        for trial in range(3):
            cells=[(t,c,m,b) for t in tasks for c in ('manuals','expanded') for m in plan['methods'] for b in plan['budgets']];rng.shuffle(cells)
            for task,corpus,method,budget in cells:
                key=corpus+('_semantic' if method=='hybrid' else '_deterministic');signals={};start=time.perf_counter_ns()
                def routed(con,query,limit):
                    ids,observed=rank(con,query,method,limit);signals.update(observed);return ids
                with patch('benchmarks.unit_passages._lexical_channel',routed):
                    result=select(packs[key],task['question'],budget,system_prompt='Preserve the caller instructions exactly.')
                elapsed=(time.perf_counter_ns()-start)/1e6;context=result.context_text()
                assert result.query==task['question'] and result.system_prompt=='Preserve the caller instructions exactly.' and not result.used_generative_llm
                coverage=source_coverage(result.pieces,task['required']) if task['required'] else {'all_required_spans':None}
                row={'task':task['id'],'cohort':task['cohort'],'corpus':corpus,'method':method,'budget':budget,'trial':trial,
                     'corpus_tokens':compilation['corpora'][key]['corpus_tokens'],'available_tokens':result.available_tokens,
                     'baseline_prompt_tokens_estimate':tokens(f'SOURCE\n{full[corpus]}\n\nQUESTION\n{task["question"]}'),
                     'selected_prompt_tokens_estimate':tokens(f'SOURCE\n{context}\n\nQUESTION\n{task["question"]}'),
                     'selected_tokens':result.selected_tokens,'context_sha256':sha(context.encode()),'status':result.status,'latency_ms':elapsed,
                     'signals':signals,'notes':result.notes,'pieces':[{'path':p.path,'start':p.start,'end':p.end,'span':p.span} for p in result.pieces],
                     **coverage,**region_counts(result.pieces,details['docstrings'])}
                assert reconstruct(row,sources)[1]==context
                (root/'contexts'/(row['context_sha256']+'.txt')).write_bytes(context.encode());rows.append(row)
            write_json(root/'observations.json',rows);print({'trial':trial,'observations':len(rows)},flush=True)
    unique=[]
    for task in tasks:
        for corpus in ('manuals','expanded'):
            for method in plan['methods']:
                for budget in plan['budgets']:
                    group=[r for r in rows if (r['task'],r['corpus'],r['method'],r['budget'])==(task['id'],corpus,method,budget)]
                    assert len(group)==3 and len({r['context_sha256'] for r in group})==1
                    unique.append({k:v for k,v in group[0].items() if k not in ('trial','latency_ms')}|{'median_ms':statistics.median(r['latency_ms'] for r in group)})
    write_json(root/'results.json',{**plan,**compilation,'status':'COMPLETE','rows':rows,'unique':unique})
    print({'status':'COMPLETE','observations':len(rows),'unique_cells':len(unique)},flush=True)


if __name__=='__main__':main()

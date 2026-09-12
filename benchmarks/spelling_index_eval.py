"""Prospective index/no-index comparison with known and new spelling probes."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import time
from unittest.mock import patch
from benchmarks.identifier_spelling import additions,components
from benchmarks.spelling_index import update,open_index,normalized_rank,canonical_rank,variant_rank,fuse
from benchmarks.compiled_source_contract import require_compiled_sources
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.unit_answer_plan import reconstruct
from benchmarks.unit_passages import select
from npk.pack import verify
from npk.pack.compile import _source_lines
from npk.pack.select import _lexical_channel


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def rank_method(index,method,con,query,limit):
    if method=='normalized_index':
        with open_index(index,con) as side:return normalized_rank(side,query,limit),{}
    baseline=_lexical_channel(con,query,limit)
    if method=='query_variants':
        other=variant_rank(con,query,limit)
        return fuse(baseline,other,limit),{'additional_seeds':len(other)}
    with open_index(index,con) as side:
        other,collisions=canonical_rank(side,query,limit,marked_only=method=='canonical_marked')
        return fuse(baseline,other,limit),{'additional_seeds':len(other),'spelling_groups':collisions}


def new_probes(source,previous):
    counts=Counter()
    for lines in source.values():counts.update(re.findall(r'\b[A-Za-z][A-Za-z0-9_]+\b','\n'.join(lines)))
    excluded={t['identifier'] for t in previous['tasks']};tasks=[]
    families={'snake':[n for n,c in counts.items() if 2<=c<=100 and re.fullmatch(r'[a-z]{3,}(?:_[a-z]{3,}){1,3}',n)],
              'camel':[n for n,c in counts.items() if 2<=c<=100 and '_' not in n and len(components(n))>1 and additions(n)]}
    for kind,candidates in families.items():
        chosen=sorted((n for n in candidates if n not in excluded),key=lambda n:sha(n.encode()))[:16]
        assert len(chosen)==16
        for name in chosen:
            alias=name.split('_')[0]+''.join(p.title() for p in name.split('_')[1:]) if kind=='snake' else ' '.join(components(name))
            for variant,query in [('native',name),('alternate',alias),('prefixed','Explain how '+(alias if kind=='snake' else name)+' behaves.')]:
                tasks.append({'id':kind+'-'+sha(name.encode())[:12]+'-'+variant,'kind':kind,'identifier':name,'variant':variant,'query':query,'source_occurrences':counts[name]})
    return tasks


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--spelling',type=Path,required=True)
    p.add_argument('--reuse-index',type=Path,help='Verified earlier index run; reuse its original compilation measurements explicitly')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New frozen index experiment required')
    acquired=read(a.corpus/'acquisition.json');parent=read(a.parent/'results.json');previous=read(a.spelling/'results.json')
    assert parent['status']==previous['status']=='COMPLETE'
    assert previous['parent_results_sha256']==sha((a.parent/'results.json').read_bytes())
    source={}
    for item in acquired['source_manifest']:
        body=(a.corpus/'source'/item['path']).read_bytes();assert sha(body)==item['sha256'];source[item['path']]=_source_lines(body.decode())
    tasks=[{**t,'cohort':'known_spelling'} for t in previous['tasks']]
    tasks +=[{**t,'cohort':'new_spelling'} for t in new_probes(source,previous)]
    tasks +=[{'id':t['id'],'query':t['question'],'required':t['required'],'cohort':'known_behavior','kind':'behavior','variant':'original'} for t in parent['tasks']]
    methods=['champion','normalized_index','canonical_all','canonical_marked','query_variants','hybrid'];budgets=[1024,4096]
    packs={name:a.parent/(name+'.npk') for name in ('fixed2048','semantic2048')}
    for name,pack in packs.items():
        assert sha(pack.read_bytes())==parent['corpora'][name]['pack_sha256'] and verify(pack)['ok']
        require_compiled_sources(pack,acquired['source_manifest'])
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    build_origin=None
    if a.reuse_index:
        old=read(a.reuse_index/'results.json')
        assert old['status']=='COMPLETE' and old['parent_results_sha256']==sha((a.parent/'results.json').read_bytes())
        assert old['tasks']==tasks and old['methods']==methods and old['budgets']==budgets
        assert all(old['code_sha256'][name]==digest for name,digest in code.items() if name.startswith('npk/'))
        assert old['code_sha256']['benchmarks/spelling_index.py']==code['benchmarks/spelling_index.py']
        build_origin={'run':str(a.reuse_index.resolve()),'results_sha256':sha((a.reuse_index/'results.json').read_bytes()),
                      'build_sha256':sha((a.reuse_index/'build.json').read_bytes()),'note':'Original completed index build reused; no new compilation timing'}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'methods':methods,'budgets':budgets,'trials':3,'code_sha256':code,'build_origin':build_origin,
              'source_manifest':acquired['source_manifest'],'parent_results_sha256':sha((a.parent/'results.json').read_bytes()),
              'spelling_results_sha256':sha((a.spelling/'results.json').read_bytes()),'corpora':parent['corpora'],
              'reference':{'url':'https://lucene.apache.org/core/10_3_1/analysis/common/org/apache/lucene/analysis/miscellaneous/WordDelimiterGraphFilter.html',
                           'checked_on':'2026-09-07','note':'Word splitting and concatenation are standard IR controls; this SQLite experiment is not Lucene or its token-position graph'},
              'limitations':['Known probes are diagnostics; new probes are developer-generated from previously unsampled identifier names, not sealed independent tasks',
                             'Identifier presence and annotated passage retention are different LOCAL metrics; neither is answer accuracy',
                             'All methods use identical 2,048-character blocks and provenance-budgeted assembly; hybrid uses its actual pinned optional encoder',
                             'Canonical collisions describe spellings, not program-object identity; all ordinal risk remains uncalibrated',
                             'Side-index query checks include version, parent-root and clean-cache validation; full external integrity verification is separate',
                             'Three shuffled sweeps; no concurrent agent CPU tests, benchmarks, archive compression or LIVE IO; host load uncontrolled']}
    root.mkdir(parents=True);(root/'contexts').mkdir();write_json(root/'manifest.json',manifest)
    write_json(root/'execution-sources.json',{name:(repo/name).read_bytes().decode() for name in code})
    index=root/'spelling.sqlite';os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL index experiment attempted network')):
        if a.reuse_index:
            import shutil
            build=read(a.reuse_index/'build.json');assert sha((a.reuse_index/'spelling.sqlite').read_bytes())==build['index_sha256']
            shutil.copyfile(a.reuse_index/'spelling.sqlite',index);assert sha(index.read_bytes())==build['index_sha256']
        else:
            import psutil
            rss_before=psutil.Process().memory_info().rss;start=time.perf_counter_ns();cpu=time.process_time_ns()
            stats=update(packs['fixed2048'],index,create=True)
            build={'elapsed_ms':(time.perf_counter_ns()-start)/1e6,'cpu_ms':(time.process_time_ns()-cpu)/1e6,'stats':stats,
                   'bytes':index.stat().st_size,'process_rss_before':rss_before,'process_rss_after':psutil.Process().memory_info().rss,'index_sha256':sha(index.read_bytes())}
        write_json(root/'build.json',build);print({'side_index_build':build,'build_reused':bool(a.reuse_index)},flush=True)
        import torch
        from npk.context.embedding import get_backend
        torch.set_num_threads(2);backend=get_backend();assert backend.available()
        assert backend.identity()==parent['builds']['semantic2048']['encoder_identity']
        rows=[];rng=random.Random(2609)
        for trial in range(3):
            cells=[(t,m,b) for t in tasks for m in methods for b in budgets];rng.shuffle(cells)
            for task,method,budget in cells:
                signals={};start=time.perf_counter_ns()
                def routed(con,query,limit):
                    ids,observed=rank_method(index,method,con,query,limit);signals.update(observed);return ids
                if method in ('champion','hybrid'):
                    result=select(packs['semantic2048' if method=='hybrid' else 'fixed2048'],task['query'],budget,ranking='hybrid' if method=='hybrid' else 'lexical')
                else:
                    with patch('benchmarks.unit_passages._lexical_channel',routed):result=select(packs['fixed2048'],task['query'],budget)
                elapsed=(time.perf_counter_ns()-start)/1e6;context=result.context_text()
                assert result.query==task['query'] and not result.used_generative_llm
                success=bool(any(re.search(r'(?<!\w)'+re.escape(task['identifier'])+r'(?!\w)',p.text) for p in result.pieces)) if 'identifier' in task else source_coverage(result.pieces,task['required'])['all_required_spans']
                row={'trial':trial,'task':task['id'],'cohort':task['cohort'],'kind':task['kind'],'variant':task['variant'],'method':method,'budget':budget,
                     'selected_tokens':result.selected_tokens,'available_tokens':result.available_tokens,'corpus_tokens':parent['corpora']['fixed2048']['corpus_tokens'],
                     'context_sha256':sha(context.encode()),'status':result.status,'channels':result.channels,'notes':result.notes,'signals':signals,
                     'latency_ms':elapsed,'local_metric':'literal_identifier_present' if 'identifier' in task else 'all_specified_passages','metric_pass':success,
                     'pieces':[{'path':x.path,'start':x.start,'end':x.end,'span':x.span} for x in result.pieces]}
                assert reconstruct(row,source)[1]==context
                (root/'contexts'/(row['context_sha256']+'.txt')).write_bytes(context.encode());rows.append(row)
            write_json(root/'observations.json',rows);print({'trial':trial,'observations':len(rows)},flush=True)
    cells={}
    for row in rows:cells.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    unique=[]
    for group in cells.values():
        assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
        unique.append({k:v for k,v in group[0].items() if k not in ('trial','latency_ms')}|{'median_ms':statistics.median(r['latency_ms'] for r in group)})
    summary=[];pairs=[]
    for cohort in ('known_spelling','new_spelling','known_behavior'):
        for method in methods:
            for budget in budgets:
                group=[r for r in unique if (r['cohort'],r['method'],r['budget'])==(cohort,method,budget)]
                summary.append({'cohort':cohort,'method':method,'budget':budget,'tasks':len(group),'metric_pass':sum(r['metric_pass'] for r in group),
                                'median_ms':statistics.median(r['median_ms'] for r in group),'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group),
                                'fallbacks':sum(r['status']=='fallback_required' for r in group),'embedding_used':sum('embedding' in r['channels'] for r in group)})
                if method!='champion':
                    pair={'cohort':cohort,'candidate':method,'budget':budget,'wins':[],'losses':[],'ties':[]}
                    for row in group:
                        base=cells[row['task'],'champion',budget][0]
                        name='ties' if row['metric_pass']==base['metric_pass'] else 'wins' if row['metric_pass'] else 'losses';pair[name].append(row['task'])
                    pairs.append(pair)
    result={**manifest,'status':'COMPLETE','build':build,'rows':rows,'unique':unique,'summary':summary,'pairs':pairs}
    write_json(root/'results.json',result);print({'observations':len(rows),'summary':summary},flush=True)


if __name__=='__main__':main()

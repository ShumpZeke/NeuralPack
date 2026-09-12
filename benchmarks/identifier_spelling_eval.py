"""Matched-cap public-source spelling probes, not semantic answer validation."""
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
from benchmarks.compiled_source_contract import require_compiled_sources
from benchmarks.identifier_spelling import additions,components,terms
from benchmarks.prospective_eval import write_json
from benchmarks.unit_answer_plan import reconstruct
from benchmarks.unit_passages import select
from npk.pack import verify
from npk.pack.compile import _source_lines
from npk.pack.select import _lexical_channel as original_channel


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def channel(con,query,limit,*,vocabulary):
    with patch('npk.pack.select._content_terms',lambda q:terms(q,con if vocabulary else None)):
        return original_channel(con,query,limit)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New frozen spelling run required')
    acquired=read(a.corpus/'acquisition.json');parent=read(a.parent/'results.json');assert parent['status']=='COMPLETE'
    assert parent['acquisition_sha256']==sha((a.corpus/'acquisition.json').read_bytes())
    source={};counts=Counter()
    for item in acquired['source_manifest']:
        body=(a.corpus/'source'/item['path']).read_bytes();assert sha(body)==item['sha256']
        source[item['path']]=_source_lines(body.decode())
        counts.update(re.findall(r'\b[A-Za-z][A-Za-z0-9_]+\b',body.decode()))
    snake=[n for n,c in counts.items() if 2<=c<=100 and re.fullmatch(r'[a-z]{3,}(?:_[a-z]{3,}){1,3}',n)]
    camel=[n for n,c in counts.items() if 2<=c<=100 and '_' not in n and len(components(n))>1 and additions(n)]
    names={kind:sorted(values,key=lambda n:sha(n.encode()))[:16] for kind,values in [('snake',snake),('camel',camel)]}
    assert all(len(v)==16 for v in names.values());tasks=[]
    for kind,identifiers in names.items():
        for name in identifiers:
            alias=name.split('_')[0]+''.join(p.title() for p in name.split('_')[1:]) if kind=='snake' else ' '.join(components(name))
            for variant,query in [('native',name),('alternate',alias),('prefixed','Explain how '+(alias if kind=='snake' else name)+' behaves.')]:
                tasks.append({'id':kind+'-'+sha(name.encode())[:12]+'-'+variant,'kind':kind,'identifier':name,'variant':variant,'query':query,'source_occurrences':counts[name]})
    configurations={'baseline':'lexical','split_camel':'lexical','vocabulary_split':'lexical','hybrid':'hybrid'}
    budgets=[1024,4096];pack_names={'lexical':'fixed2048','hybrid':'semantic2048'};packs={}
    for ranking,name in pack_names.items():
        pack=a.parent/(name+'.npk');assert sha(pack.read_bytes())==parent['corpora'][name]['pack_sha256'] and verify(pack)['ok']
        require_compiled_sources(pack,acquired['source_manifest']);packs[ranking]=pack
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,'budgets':budgets,'configurations':configurations,
              'source_manifest':acquired['source_manifest'],'code_sha256':code,'trials':3,
              'acquisition_sha256':sha((a.corpus/'acquisition.json').read_bytes()),'parent_results_sha256':sha((a.parent/'results.json').read_bytes()),
              'artifact_hashes':{rank:sha(pack.read_bytes()) for rank,pack in packs.items()},
              'corpus_tokens':parent['corpora']['fixed2048']['corpus_tokens'],'available_tokens':parent['corpora']['fixed2048']['available_tokens'],
              'sampling':'First 16 identifiers by SHA-256 in each declared spelling family, occurrence range 2–100, selected before retrieval',
              'limitations':['Spelling lookup probes generated from known public identifiers; not answer accuracy or semantic sufficiency',
                             'Alternate snake queries intentionally change spelling; original query bytes remain unchanged in the returned request',
                             'All methods use the same fixed 2,048-character compiled blocks and provenance-budgeted assembler',
                             'Hybrid uses the actual pinned MiniLM index and the existing declared similarity floor; channel use is reported per row',
                             'No new compilation measurement; existing cycle24 artifacts reused and verified',
                             'Three shuffled LOCAL repetitions, CPU two encoder threads, no concurrent agent CPU benchmark/test or LIVE calls; host load uncontrolled']}
    root.mkdir(parents=True);(root/'contexts').mkdir();write_json(root/'manifest.json',manifest)
    write_json(root/'execution-sources.json',{name:(repo/name).read_bytes().decode() for name in code})
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    with patch('socket.socket.connect',side_effect=AssertionError('Spelling experiment attempted network')):
        import torch
        from npk.context.embedding import get_backend
        torch.set_num_threads(2);backend=get_backend();assert backend.available()
        assert backend.identity()==parent['builds']['semantic2048']['encoder_identity']
        rows=[];rng=random.Random(2510)
        for trial in range(3):
            cells=[(t,m,b) for t in tasks for m in configurations for b in budgets];rng.shuffle(cells)
            for task,method,budget in cells:
                start=time.perf_counter_ns();ranking=configurations[method]
                if method in ('split_camel','vocabulary_split'):
                    with patch('benchmarks.unit_passages._lexical_channel',lambda con,q,n:channel(con,q,n,vocabulary=method=='vocabulary_split')):
                        result=select(packs[ranking],task['query'],budget)
                else:result=select(packs[ranking],task['query'],budget,ranking=ranking)
                elapsed=(time.perf_counter_ns()-start)/1e6;context=result.context_text()
                assert result.query==task['query'] and not result.used_generative_llm
                row={'trial':trial,'task':task['id'],'kind':task['kind'],'variant':task['variant'],'identifier':task['identifier'],
                     'method':method,'budget':budget,'selected_tokens':result.selected_tokens,'available_tokens':result.available_tokens,
                     'context_sha256':sha(context.encode()),'status':result.status,'channels':result.channels,'notes':result.notes,
                     'latency_ms':elapsed,'identifier_present':bool(re.search(r'(?<!\w)'+re.escape(task['identifier'])+r'(?!\w)',context)),
                     'pieces':[{'path':x.path,'start':x.start,'end':x.end,'span':x.span} for x in result.pieces]}
                assert reconstruct(row,source)[1]==context
                (root/'contexts'/(row['context_sha256']+'.txt')).write_bytes(context.encode());rows.append(row)
            write_json(root/'observations.json',rows);print({'trial':trial,'observations':len(rows)},flush=True)
    by_cell={}
    for row in rows:by_cell.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    unique=[]
    for group in by_cell.values():
        assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
        unique.append({k:v for k,v in group[0].items() if k not in ('trial','latency_ms')}|{'median_ms':statistics.median(r['latency_ms'] for r in group)})
    summary=[];pairs=[]
    for kind in names:
        for variant in ('native','alternate','prefixed'):
            for budget in budgets:
                for method in configurations:
                    group=[r for r in unique if (r['kind'],r['variant'],r['method'],r['budget'])==(kind,variant,method,budget)]
                    summary.append({'kind':kind,'variant':variant,'method':method,'budget':budget,'tasks':len(group),
                                    'identifier_present':sum(r['identifier_present'] for r in group),'fallbacks':sum(r['status']=='fallback_required' for r in group),
                                    'median_ms':statistics.median(r['median_ms'] for r in group),'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group),
                                    'embedding_used':sum('embedding' in r['channels'] for r in group)})
                    if method!='baseline':
                        pair={'kind':kind,'variant':variant,'candidate':method,'budget':budget,'wins':[],'losses':[],'ties':[]}
                        for row in group:
                            baseline=by_cell[row['task'],'baseline',budget][0]
                            category='ties' if row['identifier_present']==baseline['identifier_present'] else 'wins' if row['identifier_present'] else 'losses'
                            pair[category].append(row['task'])
                        pairs.append(pair)
    result={**manifest,'status':'COMPLETE','rows':rows,'unique':unique,'summary':summary,'pairs':pairs}
    write_json(root/'results.json',result);print({'observations':len(rows),'unique_cells':len(unique),'summary':summary},flush=True)


if __name__=='__main__':main()

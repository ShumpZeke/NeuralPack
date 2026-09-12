"""Independent source-span, payload, packing and exposure audit of views.

Does not import the source-view implementation or its needle-grading helper.
Scores literal source exposure, never target answer accuracy.
"""
import argparse
import ast
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path

sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_bytes())


def intervals(source):
    """Independent inventory of actual docstring physical lines."""
    lines=source.split('\n'); found=set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is None: continue
            first=node.body[0]
            prefix=lines[first.lineno-1].encode()[:first.col_offset]
            suffix=lines[first.end_lineno-1].encode()[first.end_col_offset:]
            if not prefix.strip() and not suffix.strip(): found.update(range(first.lineno,first.end_lineno+1))
    return found


def needle_hit(items, task):
    start,end=map(int,task['span'].rsplit(':',1)[1].split('-'))
    text=[]
    for item in items:
        if item['path']!=task['path']:continue
        for f in item['fragments']:
            if f['start_line']<=end and f['end_line']>=start:text.append(f['text'])
    merged=' '.join('\n\n'.join(text).split())
    return bool(task['needles']) and all(n in merged for n in task['needles'])


def audit(a):
    if a.output.exists():raise ValueError('Fresh audit report required')
    report=read(a.run/'report.json'); plan=read(a.run/'plan.json')
    assert report['status']=='COMPLETE' and sha((a.run/'plan.json').read_bytes())==report['plan_sha256']
    assert sha((a.run/'views.json').read_bytes())==plan['views_sha256']
    assert sha(a.pack.read_bytes())==plan['pack_sha256'] and sha(a.asset.read_bytes())==plan['tokenizer_sha256']
    for name,digest in plan['code_sha256'].items():assert sha((a.run/'sources'/name).read_bytes())==digest
    source={name:(a.source/name).read_bytes() for name in plan['source_sha256']}
    assert all(sha(body)==plan['source_sha256'][p] for p,body in source.items())
    text={p:b.decode().replace('\r\n','\n').replace('\r','\n') for p,b in source.items()}
    lines={p:t.split('\n') for p,t in text.items()}; docs={p:intervals(t) for p,t in text.items()}
    from npk.pack.format import open_pack,load_blocks
    from tokenizers import Tokenizer
    from benchmarks.lean_boundary_tokenizer import LeanCompactBoundaryCount
    with open_pack(a.pack) as con:blocks={b.id:b for b in load_blocks(con)}
    codec=Tokenizer.from_file(str(a.asset));codec.no_padding();codec.no_truncation()
    @lru_cache(maxsize=4096)
    def count(s):return len(codec.encode(s,add_special_tokens=False).ids)
    available=count('\n\n'.join(text[p] for p in sorted(text)))
    assert available==report['available_source_tokens_per_request']
    views={int(k):v for k,v in read(a.run/'views.json').items()}
    prepared=LeanCompactBoundaryCount(a.asset,cache_bytes=16*1024*1024)
    prepared.prepare([b.text for b in blocks.values()]+[v['text'] for v in views.values()])
    for bid,v in views.items():
        b=blocks[bid]; segments=[]
        for f in v['fragments']:
            lo,hi=f['start_line'],f['end_line']
            assert b.start_line<=lo<=hi<=b.end_line
            assert f['text']=='\n'.join(lines[b.path][lo-1:hi])
            segments.append((lo,hi,f['text']))
        for lo,hi in v['omitted']:
            assert set(range(lo,hi+1)) <= docs[b.path]
            segments.append((lo,hi,f'# [NPK: docstring omitted; source lines {lo}-{hi}]'))
        segments.sort(); cursor=b.start_line
        for lo,hi,_ in segments:assert lo==cursor;cursor=hi+1
        assert cursor==b.end_line+1
        assert v['text']=='\n'.join(s[2] for s in segments)
        assert any(f['text'].strip() for f in v['fragments']), 'Marker-only evidence'
    examples={e['id']:e for e in plan['examples']}; rows={}; seen=set(); checked=0
    proposals=0;upstream_proposals=0
    expected={(e,cap,s,p) for e in examples for cap in plan['budgets'] for s in plan['seeds'] for p in plan['policies']}
    files=list((a.run/'records').glob('*.json'))
    assert {p.name for p in files}==set(report['record_sha256'])
    for path in files:
        body=path.read_bytes();assert sha(body)==report['record_sha256'][path.name]
        r=json.loads(body);key=tuple(r['key']);assert key in expected and key not in seen;seen.add(key)
        eid,cap,seed,policy=key;e=examples[eid];cell=e['by_budget'][str(cap)];pool=cell['ranks'][seed]
        assert r['query']==e['query'] and r['budget']==cap and r['seed']==seed and r['policy']==policy
        assert r['used_generative_llm'] is False and r['available_source_tokens']==r['source_file_tokens']==available
        context=(a.run/'contexts'/(r['context_sha256']+'.txt')).read_bytes()
        assert sha(context)==r['context_sha256'] and context.decode()=='\n\n'.join(i['text'] for i in r['items'])
        assert type(r['tokens']) is int and r['tokens']==count(context.decode())<=cap
        # Independent rank-first replay with whole-context tokenization.
        selected=[];output='';selected_views=[];pieces=[]
        for bid in pool:
            raw=blocks[bid].text; v=views.get(bid)
            choices=[(raw,False)]
            if policy!='raw' and v and count(v['text'])<count(raw):
                choices=([(v['text'],True)] if policy=='compact' else [*choices,(v['text'],True)])
            for snippet,short in choices:
                joined=output+('\n\n' if selected else '')+snippet
                size=prepared.count_parts([*pieces,snippet]); proposals+=1
                if proposals%101==0:
                    assert size==count(joined);upstream_proposals+=1
                if snippet.strip() and size<=cap:
                    selected.append(bid);selected_views.append(short);pieces.append(snippet);output=joined;break
        assert selected==[i['block_id'] for i in r['items']] and output==context.decode()
        coverage=defaultdict(set)
        for item,short in zip(r['items'],selected_views):
            b=blocks[item['block_id']]
            assert item['path']==b.path and item['span']==b.span and item['name']==b.name and item['kind']==b.kind
            assert item['rank']==pool.index(b.id)+1
            if short:
                assert item['fragments']==views[b.id]['fragments'] and item['omitted']==views[b.id]['omitted']
            else:
                assert item['text']==b.text and item['omitted']==[]
                assert item['fragments']==[{'start_line':b.start_line,'end_line':b.end_line,'text':b.text}]
            for f in item['fragments']:coverage[b.path].update(range(f['start_line'],f['end_line']+1))
        assert r['fallback_required'] is (not selected)
        omitted=any(selected_views)
        assert r['status']==('fallback_required' if not selected else 'selected_with_omissions' if omitted else 'selected')
        assert r['risk']==('uncalibrated:docstrings_omitted' if omitted else 'uncalibrated')
        assert r['hits']=={t['task_id']:needle_hit(r['items'],t) for t in e['annotations']}
        if policy=='raw':
            old=cell['controls'][seed]
            assert selected==old['ids'] and r['context_sha256']==old['context_sha256'] and r['tokens']==old['tokens']
        r['coverage']=coverage; rows[key]=r;checked+=1
        if checked%600==0:print(json.dumps({'audited':checked,'planned':len(expected)}),flush=True)
    assert seen==expected
    # Post-hoc, conservative implementation exposure on the existing 15 behavior queries.
    from benchmarks.library_failure_analysis import PRIMARY,definitions
    definition_map={p:definitions(t) for p,t in text.items()}
    exposure=[]
    for (eid,cap,seed,policy),r in rows.items():
        if examples[eid]['workload']!='behavior':continue
        refs=PRIMARY[eid]; complete=[]
        for path,name in refs:
            lo,hi,_=definition_map[path][name]
            required={i for i in range(lo,hi+1) if i not in docs[path] and lines[path][i-1].strip()}
            complete.append(required <= r['coverage'][path])
        exposure.append({'task':eid,'budget':cap,'seed':seed,'policy':policy,'all_primary_non_doc_lines':all(complete)})
    summary=[]
    for declared in report['summary']:
        seed,cap,policy=declared['seed'],declared['budget'],declared['policy']
        group=[r for k,r in rows.items() if k[1:]==(cap,seed,policy)]
        hits=sum(sum(r['hits'].values()) for r in group);assert hits==declared['source_needle_hits']
        wins=losses=0
        for r in group:
            base=rows[r['key'][0],cap,seed,'raw']
            for tid,hit in r['hits'].items():wins+=hit and not base['hits'][tid];losses+=base['hits'][tid] and not hit
        assert wins==declared['wins'] and losses==declared['losses']
        summary.append(dict(declared, all_primary_non_doc_lines=sum(e['all_primary_non_doc_lines'] for e in exposure
            if (e['budget'],e['seed'],e['policy'])==(cap,seed,policy)),
            selected_docstring_lines=sum(len(r['coverage'][p]&docs[p]) for r in group for p in r['coverage'])))
    result={'status':'AUDITED','evidence_mode':'LOCAL','generative_calls':0,'selections':checked,
            'plan_sha256':sha((a.run/'plan.json').read_bytes()), 'report_sha256':sha((a.run/'report.json').read_bytes()),
            'auditor_sha256':sha(Path(__file__).read_bytes()), 'potential_views':len(views), 'source_blocks':len(blocks),
            'replayed_admission_decisions':proposals,'sampled_upstream_admission_counts':upstream_proposals,
            'source_tokens_per_request':available,'summary':summary,'behavior_exposure':exposure,
            'limits':plan['limits']+['Primary non-doc line exposure excludes docstrings, includes all other nonblank lines, and is not proof of sufficient dependencies',
                                   'Replay uses the existing prepared counter; every 101st proposal and all final payloads are additionally counted by the upstream tokenizer']}
    a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'status':'AUDITED','selections':checked,'summary_2k':[s for s in summary if s['budget']==2048]}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','source','pack','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    audit(p.parse_args())

"""Frozen source-span retrieval controls for boundary experiments (not accuracy)."""
import argparse
from functools import partial
import hashlib
import importlib
import json
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch
from benchmarks.line_anchors import split_anchored
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.evidence_diagnostics import from_evidence,validate_pieces
from npk.pack import compile_pack,verify,PackSelector
from npk.pack.compile import split_source,RawBlock,_source_lines,_extract_symbols
from npk.pack.format import open_pack,load_blocks


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def fixed_chars(text,language,*,python_members=False,max_chars=4800):
    if language not in ('c','rst','text'):return split_source(text,language,python_members=python_members)
    lines=_source_lines(text);blocks=[];start=0;size=0
    def emit(end):
        nonlocal start,size
        body='\n'.join(lines[start:end])
        if body.strip():
            block=RawBlock(len(blocks),'chunk',None,start+1,end,body);_extract_symbols(block);blocks.append(block)
        start=end;size=0
    for i,line in enumerate(lines):
        extra=len(line)+(1 if i>start else 0)
        if i>start and size+extra>max_chars:emit(i);extra=len(line)
        size+=extra
        if size>=max_chars:emit(i+1)
    if start<len(lines):emit(len(lines))
    return blocks


def methods():
    return {'baseline':split_source,'anchor_4800':split_anchored,
            'anchor_4800_min512':partial(split_anchored,min_chars=512),
            'anchor_2048':partial(split_anchored,max_chars=2048),
            'fixed_4800':fixed_chars,'fixed_2048':partial(fixed_chars,max_chars=2048)}


def tasks(source):
    specs=[
        ('runtime_protocol','typing.rst','After upgrading to Python 3.12, why can monkey-patching a protocol fail to change instance checks, and do these checks validate method signatures?',[(2209,2210),(2238,2243)]),
        ('nullable_default','typing.rst','Does giving an integer parameter a default make its annotation nullable, and when is accepting None the deciding factor?',[(1101,1106),(1111,1113)]),
        ('typed_mapping','typing.rst','Will declaring expected dictionary keys and value types make Python enforce them when the program runs?',[(2251,2254)]),
        ('cache_once','functools.rst','Why can concurrent calls execute the same cached function twice even though its cache stays coherent?',[(158,164)]),
        ('property_lock','functools.rst','Why did a lazily cached attribute stop preventing duplicate getter execution after Python 3.12, and where should synchronization now be added?',[(94,100),(120,125)]),
        ('keyword_order','functools.rst','Can changing only the order of named arguments create two memoization entries, and what restriction applies to argument values?',[(166,172)]),
        ('output_scope','contextlib.rst','Is temporarily redirecting standard output suitable for a threaded library, does it capture subprocess output, and does nesting support imply thread safety?',[(357,362),(972,975)]),
        ('transfer_cleanup','contextlib.rst','When cleanup callbacks are transferred to a fresh stack, do they execute immediately or only when the new owner closes?',[(598,601)]),
        ('group_suppression','contextlib.rst','In Python 3.12, what happens to unsuppressed exceptions when only some members of an exception group are suppressed?',[(315,319),(323,325)]),
        ('signed_multiset','collections.rst','Can multiset arithmetic accept signed counts while excluding nonpositive results from the output?',[(366,372)]),
    ]
    result=[]
    for name,file,question,spans in specs:
        path='cpython/Doc/library/'+file;lines=_source_lines((source/path).read_text(encoding='utf-8'))
        required=[]
        for start,end in spans:
            assert 1<=start<=end<=len(lines)
            body='\n'.join(lines[start-1:end]);assert body.strip()
            required.append({'path':path,'span':[start,end],'text':body,'sha256':sha(body.encode())})
        result.append({'id':name,'question':question,'required':required,'cohort':'developer_authored_known_source'})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gate',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[1]
    root=a.output.resolve();source=(a.gate/'source').resolve();parent=read(a.gate/'results.json')
    assert parent['status']=='COMPLETE'
    if root.exists():raise ValueError('New experiment directory required')
    for item in parent['source_manifest']:assert sha((source/item['path']).read_bytes())==item['sha256']
    defined=tasks(source);budgets=[256,512,1024,2048];candidates=methods()
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'trials':3,'code_sha256':code,
              'parent_results_sha256':sha((a.gate/'results.json').read_bytes()),'source_manifest':parent['source_manifest'],
              'tasks':defined,'budgets':budgets,'methods':list(candidates),
              'limitations':['Ten developer-authored questions about inspected source; not independently sealed tasks',
                             'Identical required source-line spans across chunkers, not whole selected-block retention',
                             'Source-span presence is not answer correctness or proof of sufficient evidence',
                             'All methods use the same BM25 selector and candidate limits; only chunk boundaries change',
                             'Fixed character-window controls distinguish content anchors from finer granularity',
                             'chars/4 token estimates exclude application wrappers; no pricing or target-tokenizer claim',
                             'Compilation and query timings use three shuffled trials on one host, no controlled host load',
                             'Research artifacts require this external splitter identity; not production update configuration']}
    root.mkdir(parents=True);(root/'contexts').mkdir();write_json(root/'manifest.json',manifest)
    compiler=importlib.import_module('npk.pack.compile');rng=random.Random(2317);builds=[];rows=[];corpora={}
    raw_context='\n\n'.join((source/item['path']).read_text(encoding='utf-8') for item in parent['source_manifest'])
    corpus_tokens=len(raw_context)//4
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL boundary retrieval attempted network')):
        for trial in range(3):
            names=list(candidates);rng.shuffle(names)
            for name in names:
                pack=root/f'{name}-{trial}.npk'
                with patch.object(compiler,'split_source',candidates[name]):
                    start=time.perf_counter_ns();stats=compile_pack(source,pack);elapsed=(time.perf_counter_ns()-start)/1e6
                assert verify(pack)['ok']
                with open_pack(pack) as con:blocks=load_blocks(con)
                validate_pieces(source,[from_evidence(b) for b in blocks])
                available=len('\n\n'.join(b.text for b in blocks))//4
                corpora[name]={'corpus_tokens':corpus_tokens,'available_tokens':available,'blocks':len(blocks)}
                builds.append({'method':name,'trial':trial,'compile_ms':elapsed,'pack_bytes':pack.stat().st_size,'stats':stats.as_dict()})
                selector=PackSelector(pack);order=[(task,budget) for task in defined for budget in budgets];rng.shuffle(order)
                for task,budget in order:
                    start=time.perf_counter_ns();selection=selector.select(task['question'],budget_tokens=budget);ms=(time.perf_counter_ns()-start)/1e6
                    assert selection.query==task['question'] and selection.total_tokens<=budget and not selection.used_generative_llm
                    assert selection.available_tokens==available
                    validate_pieces(source,[from_evidence(e) for e in selection.evidence])
                    raw=selection.context_text().encode();digest=sha(raw);(root/'contexts'/(digest+'.txt')).write_bytes(raw)
                    rows.append({'task':task['id'],'method':name,'trial':trial,'budget':budget,
                                 'corpus_tokens':corpus_tokens,'available_tokens':available,
                                 'baseline_prompt_tokens':len(raw_context+'\n\n'+task['question'])//4,
                                 'selected_tokens':selection.total_tokens,'selection_ms':ms,'context_sha256':digest,
                                 'status':selection.as_dict()['status'],'seed_failed':selection.seed_failed,
                                 'evidence':[e.as_dict(include_text=False) for e in selection.evidence],
                                 **source_coverage(selection.evidence,task['required'])})
                print({'method':name,'trial':trial,'compile_ms':elapsed,'blocks':len(blocks),'rows':len(rows)},flush=True)
    assert code=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for folder in ('npk','benchmarks') for p in (repo/folder).rglob('*.py')}
    unique=[]
    for task in defined:
        for name in candidates:
            for budget in budgets:
                group=[r for r in rows if (r['task'],r['method'],r['budget'])==(task['id'],name,budget)]
                assert len(group)==3 and len({r['context_sha256'] for r in group})==1
                row={k:v for k,v in group[0].items() if k not in ('trial','selection_ms')}
                row['median_selection_ms']=statistics.median(r['selection_ms'] for r in group);unique.append(row)
    summary=[]
    for name in candidates:
        for budget in budgets:
            group=[r for r in unique if r['method']==name and r['budget']==budget]
            summary.append({'method':name,'budget':budget,'tasks':len(group),'all_required_spans':sum(r['all_required_spans'] for r in group),
                            'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group),
                            'median_selection_ms':statistics.median(r['median_selection_ms'] for r in group)})
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','corpora':corpora,'builds':builds,'rows':rows,'unique':unique,'summary':summary})
    print({'complete':True,'summary':summary})


if __name__=='__main__':main()

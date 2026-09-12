"""Matched-budget raw/definition/binding selection on the new frozen corpus."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import sys
import time
from unittest.mock import patch

from benchmarks.definition_units import DefinitionIndex,select,render
from benchmarks import seed_metadata
from benchmarks.fast_tokenizer_eval import FastCount
from npk.pack import compile_pack
from npk.pack.format import open_pack,load_blocks
from npk.pack.select import _lexical_channel

sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_bytes())
SEEDS=('bm25','fields','crisp_frozen')
MODES=('raw','unit','links2','links4')
CAPS=(512,2048,8192)

# Inspected primary source definitions/bindings; not minimality or sufficiency.
# Explicit implementation lines distinguish overload stubs without a last-pick rule.
R='urllib3/util/retry.py';S='requests/sessions.py';U='requests/utils.py';V='packaging/version.py';P='packaging/specifiers.py'
REFS={
 'retry_captured_default':[(R,'Retry','__init__'),(R,'Retry','DEFAULT_BACKOFF_MAX')],
 'retry_empty_methods':[(R,'Retry','__init__'),(R,'Retry','_is_method_retryable'),(R,'Retry','is_retry'),(R,'Retry','DEFAULT_ALLOWED_METHODS')],
 'retry_false_zero':[(R,'Retry','__init__')],
 'retry_backoff_history':[(R,'Retry','__init__'),(R,'Retry','get_backoff_time'),(R,'Retry','DEFAULT_BACKOFF_MAX')],
 'retry_after_cap':[(R,'Retry','__init__'),(R,'Retry','parse_retry_after'),(R,'Retry','DEFAULT_RETRY_AFTER_MAX')],
 'session_none_merge':[(S,'','merge_setting'),(U,'','to_key_val_list',376)],
 'session_empty_hooks':[(S,'','merge_hooks'),(S,'','merge_setting')],
 'json_encoding_patterns':[(U,'','guess_json_utf'),(U,'','_null'),(U,'','_null2'),(U,'','_null3')],
 'uri_unreserved_only':[(U,'','unquote_unreserved'),(U,'','UNRESERVED_SET')],
 'version_normalization_order':[(V,'Version','__init__'),(V,'Version','__str__'),(V,'Version','__lt__',606)],
 'specifier_prerelease_fallback':[(P,'SpecifierSet','__init__'),(P,'SpecifierSet','contains'),(P,'SpecifierSet','filter',1332)],
 'specifier_local_versions':[(P,'Specifier','__init__'),(P,'Specifier','contains')],
}


def save(path,obj):
    temp=path.with_suffix(path.suffix+'.pending');temp.write_text(json.dumps(obj,separators=(',',':')),encoding='utf-8');temp.replace(path)


def references(index):
    refs={}
    for task,items in REFS.items():
        refs[task]=[]
        for ref in items:
            path,scope,name=ref[:3];ids=index.binders.get((path,tuple(scope.split('.')) if scope else (),name),set())
            if len(ref)==4:ids={uid for uid in ids if index.nodes[uid].lineno==ref[3]}
            assert len(ids)==1, f'Ambiguous or missing reference {ref}'
            u=index.units[next(iter(ids))];refs[task].append({'path':path,'start_line':u.start_line,'end_line':u.end_line,'name':'.'.join([scope,name]).lstrip('.')})
    return refs


def prepare(a):
    output=a.root/'selection'
    if output.exists():raise ValueError('Fresh selection trial required')
    source_plan=read(a.root/'plan.json')
    assert sha((a.root/'plan.json').read_bytes())==(a.root/'plan.sha256').read_text().strip()
    left=read(a.root/'oracles-cpython31210.json');right=read(a.root/'oracles-cpython31214.json')
    assert left['status']==right['status']=='COMPLETE' and left['rows']==right['rows']
    assert left['plan_sha256']==right['plan_sha256']==sha((a.root/'plan.json').read_bytes())
    source={p:(a.root/'sources'/p).read_bytes() for p in source_plan['source_sha256']}
    assert all(sha(b)==source_plan['source_sha256'][p] for p,b in source.items())
    text={p:b.decode().replace('\r\n','\n').replace('\r','\n') for p,b in source.items()}
    output.mkdir();(output/'records').mkdir();(output/'contexts').mkdir();(output/'code').mkdir()
    stats=compile_pack(a.root/'sources',output/'transport.npk',python_members=True)
    counter=FastCount(a.asset,cache_bytes=16*1024*1024)
    started=time.perf_counter();index=DefinitionIndex(text);index_ms=(time.perf_counter()-started)*1000
    refs=references(index)
    assert not index.parse_failures
    frozen=read(a.rival/'snapshot.json')
    for path,meta in frozen['files'].items():assert sha((a.rival/path).read_bytes())==meta['sha256']
    sys.path.insert(0,str(a.rival.resolve()))
    from crisp.index import analyze_terms
    from crisp.score import Scorer
    import tiktoken
    codec=tiktoken.get_encoding('cl100k_base')
    started=time.perf_counter()
    side_stats=seed_metadata.build(output/'transport.npk',output/'fields.sqlite',a.root/'sources',rival_analyze=analyze_terms,count_cl100k=lambda s:len(codec.encode(s)))
    side_ms=(time.perf_counter()-started)*1000
    side=sqlite3.connect(output/'fields.sqlite');side.row_factory=sqlite3.Row;scorer=Scorer(side)
    examples=[]
    with open_pack(output/'transport.npk') as con:
        seed_metadata.require_parent(side,con)
        for task in source_plan['tasks']:
            query=task['query']
            ranks={'bm25':_lexical_channel(con,query,160),'fields':seed_metadata.field_rank(side,query,160,mode='fields'),
                   'crisp_frozen':[bid for bid,score in scorer.candidates(scorer.plan(query),160)]}
            examples.append(dict(task,ranks=ranks,references=refs[task['id']]))
    side.close()
    # Physical full-file rendering includes provenance and terminal newlines.
    fullpieces=[{'path':p,'start_line':1,'end_line':len(t.split('\n')),'text':t} for p,t in sorted(text.items()) if t]
    full=render(fullpieces);digest=sha(full.encode());(output/'contexts'/(digest+'.txt')).write_bytes(full.encode())
    repo=Path(__file__).resolve().parents[1]
    code=[*sorted((repo/'npk').rglob('*.py')),repo/'benchmarks/definition_units.py',repo/'benchmarks/seed_metadata.py',
          repo/'benchmarks/fast_tokenizer_eval.py',repo/'benchmarks/transport_selection.py']
    hashes={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in code}
    for path in code:
        dest=output/'code'/path.relative_to(repo);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
    plan={'status':'FROZEN_BEFORE_SELECTION','evidence_mode':'LOCAL','generative_calls':0,'examples':examples,
          'source_plan_sha256':sha((a.root/'plan.json').read_bytes()),'oracle_sha256':{p.name:sha(p.read_bytes()) for p in a.root.glob('oracles-*.json')},
          'modes':MODES,'seeds':SEEDS,'budgets':CAPS,'shuffle_seed':3001,'compiler':vars(stats),'definition_index_ms':index_ms,
          'definition_units':len(index.units),'static_links':sum(len(u.links) for u in index.units.values()),
          'side_index':side_stats,'side_build_ms':side_ms,'pack_sha256':sha((output/'transport.npk').read_bytes()),
          'side_sha256':sha((output/'fields.sqlite').read_bytes()),'tokenizer_sha256':sha(a.asset.read_bytes()),
          'full_context_sha256':digest,'full_context_tokens':counter.count(full),
          'raw_file_context_tokens':counter.count('\n\n'.join(text[p] for p in sorted(text))),
          'code_sha256':hashes,'frozen_rival_snapshot_sha256':sha((a.rival/'snapshot.json').read_bytes()),
          'limits':['Primary-source exposure is a diagnostic, not answer accuracy, necessity or sufficiency',
                    'New corpus/tasks relative to prior study, but authored after code inspection; no sealed test claim',
                    'All methods have 160 candidate ceilings, identical source and exact NIM caps, including provenance headers',
                    'Frozen CRISP scoring on common NPK blocks, not current CRISP or its native full selection architecture',
                    'Static links over-approximate simple lexical bindings; dynamic behavior and inheritance remain unresolved',
                    'A whole definition/link bundle that does not fit falls back to a smaller source view with unmet requirements reported',
                    'Full-file control is complete only for these three libraries; external dependencies are not in the corpus',
                    'Artifact and side indexes are frozen research inputs; no incremental production integration is claimed']}
    save(output/'plan.json',plan);(output/'plan.sha256').write_text(sha((output/'plan.json').read_bytes()),encoding='ascii')
    print(json.dumps({'status':'PREPARED','tasks':len(examples),'planned':len(examples)*len(MODES)*len(SEEDS)*len(CAPS),
                      'source_tokens':plan['raw_file_context_tokens'],'full_prompt_context_tokens':plan['full_context_tokens'],
                      'compiler':vars(stats),'units':len(index.units),'links':plan['static_links']}),flush=True)


def run(a):
    output=a.root/'selection';plan=read(output/'plan.json');repo=Path(__file__).resolve().parents[1]
    assert sha((output/'plan.json').read_bytes())==(output/'plan.sha256').read_text().strip()
    assert sha(a.asset.read_bytes())==plan['tokenizer_sha256'] and sha((output/'transport.npk').read_bytes())==plan['pack_sha256']
    for p,d in plan['code_sha256'].items():assert sha((repo/p).read_bytes())==d
    source_plan=read(a.root/'plan.json');source={p:(a.root/'sources'/p).read_bytes() for p in source_plan['source_sha256']}
    assert all(sha(b)==source_plan['source_sha256'][p] for p,b in source.items())
    index=DefinitionIndex({p:b.decode().replace('\r\n','\n').replace('\r','\n') for p,b in source.items()})
    with open_pack(output/'transport.npk') as con:blocks={b.id:asdict(b) for b in load_blocks(con)}
    counter=FastCount(a.asset,cache_bytes=32*1024*1024)
    jobs=[(e,cap,seed,mode) for e in plan['examples'] for cap in CAPS for seed in SEEDS for mode in MODES]
    random.Random(plan['shuffle_seed']).shuffle(jobs);done=0
    for e,cap,seed,mode in jobs:
        key=[e['id'],cap,seed,mode];dest=output/'records'/(sha(json.dumps(key).encode())+'.json')
        if dest.exists():done+=1;continue
        started=time.perf_counter()
        with patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')):
            row=select(index,blocks,e['ranks'][seed],e['query'],cap,counter.count,mode=mode)
        elapsed=(time.perf_counter()-started)*1000;context=row.pop('context');digest=sha(context.encode())
        assert row['query']==e['query'] and row['tokens']==counter.count(context)<=cap
        (output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
        coverage={}
        for p in row['pieces']:coverage.setdefault(p['path'],set()).update(range(p['start_line'],p['end_line']+1))
        exposure=[set(range(p['start_line'],p['end_line']+1))<=coverage.get(p['path'],set()) for p in e['references']]
        row.update(key=key,seed=seed,context_sha256=digest,available_tokens=plan['full_context_tokens'],
                   source_file_tokens=plan['raw_file_context_tokens'],primary_exposure=exposure,
                   all_primary_exposed=all(exposure),diagnostic_selection_ms=elapsed)
        save(dest,row);done+=1
        if done%24==0:print(json.dumps({'selected':done,'planned':len(jobs)}),flush=True)
    for p,d in plan['code_sha256'].items():assert sha((repo/p).read_bytes())==d
    records=[read(p) for p in (output/'records').glob('*.json')];summary=[]
    for seed in SEEDS:
        for cap in CAPS:
            for mode in MODES:
                rows=[r for r in records if r['seed']==seed and r['budget']==cap and r['mode']==mode]
                summary.append({'seed':seed,'cap':cap,'mode':mode,'tasks':len(rows),'all_primary_exposed':sum(r['all_primary_exposed'] for r in rows),
                                'fallbacks':sum(r['fallback_required'] for r in rows),'structural_incomplete':sum(r['status']=='structural_request_incomplete' for r in rows)})
    save(output/'report.json',{'status':'COMPLETE','evidence_mode':'LOCAL','generative_calls':0,'plan_sha256':sha((output/'plan.json').read_bytes()),
         'record_sha256':{p.name:sha(p.read_bytes()) for p in (output/'records').glob('*.json')},'summary':summary,'limits':plan['limits']})
    print(json.dumps({'status':'COMPLETE','selections':len(records),'summary_2k':[s for s in summary if s['cap']==2048]}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('prepare','run'))
    for name in ('root','asset'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--rival',type=Path);a=p.parse_args();(prepare if a.phase=='prepare' else run)(a)

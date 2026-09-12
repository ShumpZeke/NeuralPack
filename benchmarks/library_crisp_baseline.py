"""Frozen CRISP on behavior questions with an explicit local NIM tokenizer.

Its native chunks/scoring are retained. The native selector's reported budget
overruns, if any, are recorded before an explicit final guard. A separate
BM25-plus-raises baseline uses exact rank-order packing of full native blocks.
This benchmark adaptation does not modify the rival checkout or ship in NPK.
"""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def exact_rank_pack(items,budget,count):
    kept=[]
    for item in items:
        if count('\n\n'.join(e['text'] for e in [*kept,item]))<=budget:kept.append(item)
    return kept


def enforce_cap(items,budget,count):
    kept=list(items);dropped=[]
    while kept and count('\n\n'.join(e['text'] for e in kept))>budget:
        index=min(range(len(kept)),key=lambda i:(kept[i]['relevance'],-i))
        dropped.append(kept[index]['block_id']);del kept[index]
    return kept,dropped


def run(snapshot,tasks,asset,output):
    if output.exists():raise ValueError('Fresh native-baseline output required')
    frozen=read(snapshot/'snapshot.json')
    for name,info in frozen['files'].items():assert sha((snapshot/name).read_bytes())==info['sha256']
    task_plan=read(tasks);assert task_plan['snapshot_sha256']==sha((snapshot/'snapshot.json').read_bytes())
    sys.path.insert(0,str(snapshot.resolve()))
    import crisp.index as index
    import crisp.select as select
    from crisp.score import Scorer
    from crisp.views import L_FULL
    from npk.pack import LocalTokenizer
    counter=LocalTokenizer(asset);encoding='local-json-sha256:'+sha(asset.read_bytes())
    class Adapter:
        def __init__(self,name):
            assert name==encoding;self.name=name;self.exact=True
        def count(self,text):return counter.count(text)
        def count_join(self,parts,sep='\n\n'):return self.count(sep.join(parts))
    output.mkdir();(output/'contexts').mkdir()
    plan={'evidence_mode':'LOCAL','generative_calls':0,'tasks':task_plan['tasks'],
          'task_plan_sha256':sha(tasks.read_bytes()),'snapshot_sha256':sha((snapshot/'snapshot.json').read_bytes()),
          'tokenizer_sha256':sha(asset.read_bytes()),'budgets':[512,2048,8192],
          'arms':['crisp_native_nim_guarded','crisp_native_bm25_raises_exact'],
          'adaptations':['Explicit NIM tokenizer adapter at compilation and selection; native document length normalization follows it',
                         'Native selector retains default candidate count, conservative fidelity and support floor; no calibration claim adopted',
                         'Native overrun recorded before removing lowest-relevance items until the exact final context fits',
                         'BM25-plus-raises control packs 160 full native blocks with exact complete-context admission'],
          'limits':['Source-informed developer questions; no target model is called by this program',
                    'Token caps include raw evidence and separators, excluding query and caller wrappers',
                    'Reduced native views must be reconstructed from the frozen renderer before LIVE use',
                    'This is an explicitly adapted target-tokenizer comparison, not the unmodified historical cl100k run']}
    (output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    pack=output/'native.crisp';start=time.perf_counter()
    assert not pack.exists()
    with patch.object(index,'Tokenizer',Adapter):stats=index.build(snapshot/'corpus/test_src',pack,encoding_name=encoding)
    compilation={'stats':stats,'wall_ms':1000*(time.perf_counter()-start),'sha256':sha(pack.read_bytes())}
    (output/'compilation.json').write_text(json.dumps(compilation,indent=2),encoding='utf-8')
    with patch.object(select,'Tokenizer',Adapter):native=select.Selector(str(pack))
    con=sqlite3.connect(pack.resolve().as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    scorer=Scorer(con)
    blocks={r['id']:dict(r) for r in con.execute('SELECT b.*,f.path FROM blocks b JOIN files f ON f.id=b.file_id')}
    rows=[]
    try:
        for task in task_plan['tasks']:
            query=task['query'];started=time.perf_counter();qp=scorer.plan(query)
            ranked=scorer.candidates(qp,160);rank_ms=1000*(time.perf_counter()-started)
            candidates=[{'block_id':bid,'path':blocks[bid]['path'],
                         'span':f"{blocks[bid]['path']}:{blocks[bid]['start_line']}-{blocks[bid]['end_line']}",
                         'text':blocks[bid]['text'],'level':L_FULL,'level_name':'full','relevance':score} for bid,score in ranked]
            for budget in plan['budgets']:
                started=time.perf_counter();result=native.select(query,budget)
                assert result.query==query
                native_ms=1000*(time.perf_counter()-started);raw=[asdict(e) for e in result.items]
                raw_tokens=counter.count(result.context_text());assert raw_tokens==result.tokens
                guarded,dropped=enforce_cap(raw,budget,counter.count)
                native_total_ms=1000*(time.perf_counter()-started)
                started=time.perf_counter();control=exact_rank_pack(candidates,budget,counter.count)
                control_ms=rank_ms+1000*(time.perf_counter()-started)
                for arm,items,wall in [('crisp_native_nim_guarded',guarded,native_total_ms),
                                       ('crisp_native_bm25_raises_exact',control,control_ms)]:
                    context='\n\n'.join(e['text'] for e in items);count=counter.count(context)
                    assert count<=budget
                    digest=sha(context.encode());(output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
                    row={'task_id':task['task_id'],'query':query,'arm':arm,'budget':budget,'selected_tokens':count,
                         'context_sha256':digest,'items':items,'fallback_required':not items,'selection_ms':wall}
                    if arm=='crisp_native_nim_guarded':
                        row.update(raw_tokens=raw_tokens,raw_budget_exceeded=raw_tokens>budget,guard_dropped=dropped,
                                   uncalibrated_support=result.support,native_reason=result.reason,raw_items=raw,
                                   raw_selection_ms=native_ms)
                    rows.append(row)
            (output/'partial.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
            print({'phase':'behavior_baseline','task':task['task_id'],'selections':len(rows)},flush=True)
    finally:native.close();con.close()
    code=Path(__file__).read_bytes();(output/'execution-source.py').write_bytes(code)
    report={'status':'COMPLETE','evidence_mode':'LOCAL','generative_calls':0,'plan_sha256':sha((output/'plan.json').read_bytes()),
            'harness_sha256':sha(code),'compilation':compilation,'rows':rows,'python':sys.version,
            'limits':plan['limits']}
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print({'status':'COMPLETE','selections':len(rows),'native_overruns':sum(r.get('raw_budget_exceeded',False) for r in rows)},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','tasks','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.snapshot,a.tasks,a.asset,a.output)

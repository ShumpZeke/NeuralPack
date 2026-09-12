"""Compare the literal-intent product repair with its declared frozen challenger."""
import argparse
import ast
from dataclasses import asdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import re
import statistics
import sys
import time
from unittest.mock import patch


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def run(experiment,snapshot,behavior,pack,asset,output):
    if output.exists():raise ValueError('Fresh product-gate directory required')
    repo=Path(__file__).resolve().parents[1];plan=read(experiment/'plan.json')
    assert sha(pack.read_bytes())==plan['pack_sha256']
    assert sha(asset.read_bytes())==plan['asset_sha256']
    frozen=experiment/'execution-root/npk/pack/select.py'
    assert sha(frozen.read_bytes())==plan['code_sha256']['npk/pack/select.py']
    def packing_ast(body):
        tree=ast.parse(body)
        tree.body=[node for node in tree.body if not
                   (isinstance(node,ast.FunctionDef) and node.name in ('_explicit_literals','_lexical_terms'))]
        return ast.dump(tree,include_attributes=False)
    assert packing_ast(frozen.read_bytes())==packing_ast((repo/'npk/pack/select.py').read_bytes())
    for name,digest in plan['code_sha256'].items():
        if name.startswith('npk/') and name!='npk/pack/select.py':assert sha((repo/name).read_bytes())==digest
    from npk.pack import PackSelector,LocalTokenizer
    from npk.pack.format import open_pack
    from npk.pack.select import _lexical_channel
    module_name='npk.pack._literal_gate_frozen'
    spec=importlib.util.spec_from_file_location(module_name,frozen)
    baseline=importlib.util.module_from_spec(spec);sys.modules[module_name]=baseline;spec.loader.exec_module(baseline)
    original_terms=baseline._lexical_terms
    def declared_terms(con,query):
        # The fixed candidate restores atomic literal references *after* the
        # original camel-case/vocabulary policy, without changing its order.
        literals=re.findall(r'(?<!`)`(\w+(?:\.\w+)*)`(?!`)',query)
        return list(dict.fromkeys([*original_terms(con,query),
            *(part.lower() for token in literals for part in (token,*token.split('.')))]))
    tasks=read(snapshot/'work/tasks_heldout.json')
    oracle_plan=read(behavior/'plan.json')
    assert sha((snapshot/'snapshot.json').read_bytes())==oracle_plan['snapshot_sha256']==plan['snapshot_sha256']
    queries=sorted({t['query'] for t in tasks}|{t['query'] for t in oracle_plan['tasks']}|
                   {f'What is `{term}`?\r\n' for term in ('get','set','value','return','id','q','值','7')})
    output.mkdir();(output/'contexts').mkdir()
    changed=[];ranking_checks=0;timings=[];rng=random.Random(2903)
    with open_pack(pack) as con:
        for query in queries:
            differs=False
            for limit in (60,160,240,640):
                old=baseline._lexical_channel(con,query,limit)
                with patch.object(baseline,'_lexical_terms',declared_terms):
                    expected=baseline._lexical_channel(con,query,limit)
                actual=_lexical_channel(con,query,limit)
                assert actual==expected, 'Product ranking differs from fixed challenger'
                differs=differs or actual!=old;ranking_checks+=1
            if differs:changed.append(query)
        # Alternate order within each pair. This is seed-stage timing, not
        # end-to-end query latency; no tokenizer is in this timed region.
        for trial in range(3):
            shuffled=queries[:];rng.shuffle(shuffled)
            for query in shuffled:
                arms=['before','after'];rng.shuffle(arms)
                for arm in arms:
                    fn=baseline._lexical_channel if arm=='before' else _lexical_channel
                    started=time.perf_counter_ns();ids=fn(con,query,60)
                    timings.append({'trial':trial,'query_sha256':sha(query.encode()),'arm':arm,
                                    'wall_ms':(time.perf_counter_ns()-started)/1e6,'candidates':len(ids)})
    print({'phase':'rank_checked','checks':ranking_checks,'changed_queries':len(changed)},flush=True)
    counter=LocalTokenizer(asset)
    from tokenizers import Tokenizer
    independent=Tokenizer.from_file(str(asset));independent.no_truncation();independent.no_padding()
    product=PackSelector(pack,tokenizer=counter);reference=baseline.PackSelector(pack,tokenizer=counter)
    observations=[]
    for query in changed:
        for budget in (512,2048,8192):
            before=reference.select(query,budget_tokens=budget)
            with patch.object(baseline,'_lexical_terms',declared_terms):
                expected=reference.select(query,budget_tokens=budget)
            actual=product.select(query,budget_tokens=budget)
            assert actual.query==expected.query==before.query==query
            assert [asdict(e) for e in actual.evidence]==[asdict(e) for e in expected.evidence]
            assert actual.total_tokens==expected.total_tokens and actual.seed_failed==expected.seed_failed
            variants={}
            for name,result in [('before',before),('after',actual)]:
                context=result.context_text();digest=sha(context.encode())
                tokens=len(independent.encode(context,add_special_tokens=False).ids)
                assert tokens==result.total_tokens<=budget and not result.used_generative_llm
                (output/'contexts'/(digest+'.txt')).write_bytes(context.encode())
                variants[name]={'context_sha256':digest,'tokens':tokens,'fallback':result.seed_failed,
                                'items':[asdict(e) for e in result.evidence]}
            observations.append({'query':query,'budget':budget,**variants})
        print({'phase':'selection_checked','queries':len(observations)//3,'planned':len(changed)},flush=True)
    captured={p.relative_to(repo).as_posix():p.read_bytes().decode() for p in (repo/'npk').rglob('*.py')}
    captured[Path(__file__).relative_to(repo).as_posix()]=Path(__file__).read_bytes().decode()
    body=gzip.compress(json.dumps(captured).encode(),mtime=0);(output/'sources.json.gz').write_bytes(body)
    report={'status':'PASSED','evidence_mode':'LOCAL','generative_calls':0,'new_api_calls':0,
        'experiment_plan_sha256':sha((experiment/'plan.json').read_bytes()),
        'behavior_plan_sha256':sha((behavior/'plan.json').read_bytes()),'sources_sha256':sha(body),
        'pack_sha256':sha(pack.read_bytes()),'tokenizer_sha256':sha(asset.read_bytes()),
        'queries':len(queries),'ranking_checks':ranking_checks,'changed_queries':changed,
        'matched_selections':len(observations),'observations':observations,'timings':timings,
        'seed_stage_median_ms':{arm:statistics.median(r['wall_ms'] for r in timings if r['arm']==arm) for arm in ('before','after')},
        'limits':['Rank parity with a frozen challenger is not answer quality',
                  'Only queries with changed candidate rankings need selection parity checks; unchanged packing code is source-checked',
                  'Three paired passes, warmed SQLite and uncontrolled host load; seed-stage time excludes full token packing',
                  'The larger nine-arm retrieval study remains a separate experiment']}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:report[k] for k in ('status','queries','ranking_checks','matched_selections','seed_stage_median_ms')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('experiment','snapshot','behavior','pack','asset','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.experiment,a.snapshot,a.behavior,a.pack,a.asset,a.output)

"""LOCAL champion/challenger seeds on frozen Click plus public CPython source.

Embeddings are experimental sidecars; production PackSelector performs assembly,
query preservation, budgeting and fallback. This is not runtime integration.
"""
import argparse
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from unittest.mock import patch


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def timed(call):
    start=time.perf_counter();value=call();return value,1000*(time.perf_counter()-start)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--tasks',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    args=p.parse_args();repo=Path(__file__).resolve().parents[1];run=args.run.resolve()
    if run.exists():raise ValueError('new experiment run required')
    run.mkdir(parents=True)
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import numpy as np
    from npk.pack import compile_pack,verify,PackSelector
    from npk.pack.format import open_pack,load_blocks
    from npk.context.embedding import get_backend,DOCUMENT_CHAR_LIMIT
    from npk.context.info_gain import content_terms
    from benchmarks.seed_candidates import fuse
    from benchmarks import fielded_seeds
    from benchmarks.qwen_encoder import QwenEncoder
    from benchmarks.repository_eval import source_coverage
    from benchmarks.evidence_diagnostics import from_evidence,validate_pieces
    module=importlib.import_module('npk.pack.select');original_lexical=module._lexical_channel
    corpus=args.corpus.resolve();acquisition=json.loads((corpus/'acquisition.json').read_text())
    assert sha(corpus/'acquisition.json')==(corpus/'acquisition.sha256').read_text().strip()
    for row in acquisition['source_manifest']:assert sha(corpus/'source'/row['path'])==row['sha256']
    fresh=json.loads(args.tasks.read_text());assert sha(args.tasks)==args.tasks.with_suffix('.sha256').read_text().strip()
    old=json.loads((repo/'experiments/runs/cycle13-diagnostic-v1/deepseek/plan.json').read_text())
    tasks=[*fresh['tasks'],*[dict(t,cohort='previous_click_controls') for t in old['dataset']['tasks']]]
    methods=['bm25','fields_uniform','fields_name4','fields_name16','qwen_plain','qwen_headers',
             'hybrid_qwen','hybrid_fields_qwen','minilm_rrf']
    budgets=[512,2048,8192]
    code={p.relative_to(repo).as_posix():sha(p) for d in ('npk','benchmarks') for p in (repo/d).rglob('*.py')}
    manifest={'status':'PREPARED','evidence_mode':'LOCAL','generative_calls':0,'tasks':tasks,
              'task_definition_sha256':sha(args.tasks),'acquisition_sha256':sha(corpus/'acquisition.json'),
              'source_manifest':acquisition['source_manifest'],'methods':methods,'budgets':budgets,'source_code_sha256':code,
              'limitations':['Prototype rankings are injected into the actual PackSelector lexical slot; this is not a shipped Qwen integration',
                             'GPU Qwen and CPU MiniLM use different hardware, truncation, pooling and model sizes; do not interpret time differences as algorithm-only speedups',
                             'Window chunks and candidate limit 60 match across methods; assembly uses original evidence, unchanged query and floor(chars/4) budgets',
                             'Channels eagerly rank 240 candidates for possible empty-selection escalation; fused rankings then supply 60 candidates initially, 240 only on escalation',
                             'MiniLM RRF is a controlled 60-candidate prototype, not an assertion that the shipped three-channel hybrid has identical selection behavior',
                             'Twelve new developer-authored questions are frozen before retrieval; eight cases share configparser and eight old Click questions are controls',
                             'Click-only lacks the required source for new stdlib tasks; those are out-of-corpus diagnostics, not a valid promotion cohort',
                             'All methods receive the same corpus within each comparison; source-universe changes are separately identified',
                             'Coverage of whole required source spans is conservative, not task accuracy or a sufficiency/MSC proof',
                             'Encoded query rankings are reused across budgets; standalone query cost adds the measured encoding/ranking cost back once',
                             'Fielded document lengths include metadata even where a weight is small; this is ordinary FTS5 weighted BM25',
                             'No remote model or query rewriting; dense risk is uncalibrated and no new score threshold is selected from these tasks']}
    (run/'manifest.json').write_text(json.dumps(manifest,indent=2))
    packs={};blocksets={};compilations=[];fields={}
    for name in ('click_only','expanded'):
        source=run/(name+'-source');source.mkdir()
        for row in acquisition['source_manifest']:
            if name=='click_only' and row['path'].startswith('cpython/'):continue
            destination=source/row['path'];destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(corpus/'source'/row['path'],destination)
        pack=run/(name+'.npk');stats,compile_ms=timed(lambda:compile_pack(source,pack))
        assert verify(pack)['ok']
        with open_pack(pack) as con:blocks=load_blocks(con)
        validate_pieces(source,[from_evidence(b) for b in blocks])
        field_path=run/(name+'-fields.sqlite');field,index_ms=timed(lambda:fielded_seeds.build(field_path,blocks))
        fields[name]=field;blocksets[name]=blocks;packs[name]=pack
        compilations.append({'corpus':name,'stats':stats.as_dict(),'compile_ms':compile_ms,'field_compile_ms':index_ms,
                             'pack_bytes':pack.stat().st_size,'field_index_bytes':field_path.stat().st_size})
    expanded=blocksets['expanded'];key=lambda b:(b.path,b.ordinal,hashlib.sha256(b.text.encode()).hexdigest())
    canonical={key(b):i for i,b in enumerate(expanded)}
    subset={name:np.asarray([canonical[key(b)] for b in blocks]) for name,blocks in blocksets.items()}
    embeddings={};encoder_stats={};query_stats=[]
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL seed experiment attempted network')):
        qwen=QwenEncoder(repo/'experiments/results/cycle14-qwen-download.json')
        encoder_stats['qwen']={'identity':qwen.identity(),'load_seconds':qwen.load_seconds,'documents':{}}
        for mode in ('plain','headers'):
            chunks=[];tokens=truncated=0;start=time.perf_counter()
            for offset in range(0,len(expanded),128):
                group=expanded[offset:offset+128]
                texts=[b.text if mode=='plain' else f'File: {b.path}\nSymbol: {b.name or ""}\n{b.text}' for b in group]
                vectors=qwen.encode(texts);chunks.append(vectors);tokens+=qwen.last_batch['encoded_tokens'];truncated+=qwen.last_batch['truncated_texts']
                np.save(run/f'qwen-{mode}-{offset}.npy',vectors)
                print({'encoding':mode,'completed':min(offset+128,len(expanded)),'blocks':len(expanded)},flush=True)
            embeddings[mode]=np.concatenate(chunks)
            encoder_stats['qwen']['documents'][mode]={'seconds':time.perf_counter()-start,'encoded_tokens':tokens,
                                                      'truncated_blocks':truncated,'vector_bytes':embeddings[mode].nbytes}
        qqueries=[]
        for task in tasks:
            vector,ms=timed(lambda:qwen.encode([task['question']],query=True))
            qqueries.append(vector[0]);query_stats.append({'task':task['id'],'qwen_query_ms':ms,'qwen_tokens':dict(qwen.last_batch)})
        import torch
        encoder_stats['qwen'].update(gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated(),gpu_name=torch.cuda.get_device_name())
        # Release model before CPU baseline to keep measured resources attributable.
        del qwen;torch.cuda.empty_cache()
        backend=get_backend();loaded,load_ms=timed(backend.available);assert loaded
        assert backend.identity()['revision']=='1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
        docs=[b.text[:DOCUMENT_CHAR_LIMIT] for b in expanded]
        rows,mini_ms=timed(lambda:backend.embed_matrix(docs));assert rows is not None
        embeddings['minilm']=np.asarray(rows,dtype=np.float32);del rows
        encoder_stats['minilm']={'identity':backend.identity(),'load_ms':load_ms,'document_ms':mini_ms,
                                 'vector_bytes':embeddings['minilm'].nbytes,'device':'cpu','document_char_limit':DOCUMENT_CHAR_LIMIT}
        mqueries=[]
        for task,stats in zip(tasks,query_stats):
            vector,ms=timed(lambda:backend.embed_query(task['question']));assert vector is not None
            mqueries.append(vector);stats['minilm_query_ms']=ms
    qqueries=np.asarray(qqueries);mqueries=np.asarray(mqueries)
    for name,matrix in embeddings.items():np.save(run/(name+'-vectors.npy'),matrix)
    np.save(run/'qwen-queries.npy',qqueries);np.save(run/'minilm-queries.npy',mqueries)
    rows=[];rankings=[]
    def ordered(name,matrix,query):
        sims=matrix[subset[name]]@query
        indices=np.argsort(-sims,kind='stable')[:240]
        return [blocksets[name][i].id for i in indices],float(sims[indices[0]]),float(sims[indices[0]]-sims[indices[1]])
    for name,pack in packs.items():
        blocks=blocksets[name];selector=PackSelector(pack)
        for i,task in enumerate(tasks):
            with open_pack(pack) as con:
                lex,lex_ms=timed(lambda:original_lexical(con,task['question'],240))
                sym,sym_ms=timed(lambda:module._symbol_channel(con,task['question'],240))
            candidate={'bm25':lex};costs={'bm25':lex_ms}
            for method,weight in [('fields_uniform',1),('fields_name4',4),('fields_name16',16)]:
                candidate[method],costs[method]=timed(lambda:fielded_seeds.rank(fields[name],task['question'],name_weight=weight,limit=240))
            dense={}
            for mode in ('plain','headers','minilm'):
                data,ms=timed(lambda:ordered(name,embeddings[mode],mqueries[i] if mode=='minilm' else qqueries[i]))
                dense[mode]=data;costs[mode]=ms+query_stats[i]['minilm_query_ms' if mode=='minilm' else 'qwen_query_ms']
            candidate['qwen_plain']=dense['plain'][0];costs['qwen_plain']=costs['plain']
            candidate['qwen_headers']=dense['headers'][0];costs['qwen_headers']=costs['headers']
            candidate['hybrid_qwen'],fusion_ms=timed(lambda:fuse([lex,dense['headers'][0]],240));costs['hybrid_qwen']=lex_ms+costs['headers']+fusion_ms
            candidate['hybrid_fields_qwen'],fusion_ms=timed(lambda:fuse([candidate['fields_name4'],dense['headers'][0]],240));costs['hybrid_fields_qwen']=costs['fields_name4']+costs['headers']+fusion_ms
            mini_channels=[sym,lex]+([dense['minilm'][0]] if dense['minilm'][1]>=.35 else [])
            candidate['minilm_rrf'],fusion_ms=timed(lambda:fuse(mini_channels,240));costs['minilm_rrf']=lex_ms+sym_ms+costs['minilm']+fusion_ms
            rankings.append({'corpus':name,'task':task['id'],'rankings':candidate,'standalone_ranking_ms':costs,
                             'dense_top_and_margin':{k:[v[1],v[2]] for k,v in dense.items()}})
            order=methods[i%len(methods):]+methods[:i%len(methods)]
            for method in order:
                for budget in budgets:
                    def channel(con,query,limit):
                        assert query==task['question'];return candidate[method][:limit]
                    with patch.object(module,'_lexical_channel',channel):
                        selection,assembly_ms=timed(lambda:selector.select(task['question'],budget_tokens=budget))
                    assert selection.query==task['question'] and selection.total_tokens<=budget and not selection.used_generative_llm
                    if method=='bm25':
                        native=selector.select(task['question'],budget_tokens=budget)
                        assert native.context_text()==selection.context_text() and native.total_tokens==selection.total_tokens
                    validate_pieces(run/(name+'-source'),[from_evidence(e) for e in selection.evidence])
                    context=selection.context_text();digest=hashlib.sha256(context.encode()).hexdigest()
                    contexts=run/'contexts';contexts.mkdir(exist_ok=True);(contexts/(digest+'.txt')).write_bytes(context.encode())
                    rows.append({'corpus':name,'task':task['id'],'cohort':task['cohort'],'method':method,'budget':budget,
                                 'context_sha256':digest,'selected_tokens':selection.total_tokens,'available_tokens':selection.available_tokens,
                                 'seed_failed':selection.seed_failed,'status':selection.as_dict()['status'],'risk_band':selection.risk_band,
                                 'ranking_ms':costs[method],'assembly_ms':assembly_ms,'selection_ms':costs[method]+assembly_ms,
                                 'evidence':[e.as_dict(include_text=False) for e in selection.evidence],
                                 'required_source_present':all((run/(name+'-source')/r['path']).is_file() for r in task['required']),
                                 **source_coverage(selection.evidence,task['required'])})
            print({'retrieved':name,'task':task['id'],'methods':len(methods)},flush=True)
        (run/'results.json').write_text(json.dumps({**manifest,'status':'RUNNING','compilations':compilations,
                                                  'encoders':encoder_stats,'query_stats':query_stats,'rankings':rankings,'rows':rows},indent=2))
    for con in fields.values():con.close()
    assert all(sha(repo/path)==value for path,value in code.items())
    final={**manifest,'status':'COMPLETE','compilations':compilations,'encoders':encoder_stats,
           'query_stats':query_stats,'rankings':rankings,'rows':rows}
    (run/'results.json').write_text(json.dumps(final,indent=2))
    print({'observations':len(rows),'status':'COMPLETE','generative_calls':0})


if __name__=='__main__':main()

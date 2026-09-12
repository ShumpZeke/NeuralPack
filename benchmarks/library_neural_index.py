"""Reusable LOCAL encoder arrays for frozen library behavior evaluation.

Research sidecars only: source artifacts and the default runtime stay unchanged.
Document work is separate from timed per-query encoding. No network or generation.
"""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,value):
    temp=path.with_suffix(path.suffix+'.pending')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def run(pack,tasks,output,encoder,device,resume):
    repo=Path(__file__).resolve().parents[1]
    if output.exists() and not resume:raise ValueError('Fresh encoder output required')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    import numpy as np
    import torch
    from npk.pack.format import open_pack,load_blocks
    if encoder=='minilm' and device!='cpu':raise ValueError('MiniLM control is explicitly CPU')
    torch.set_num_threads(2)
    with open_pack(pack) as con:
        blocks=sorted(load_blocks(con),key=lambda b:(b.path,b.ordinal))
    task_plan=read(tasks)
    query_rows=task_plan['tasks'];assert len({r['task_id'] for r in query_rows})==len(query_rows)
    code={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    for p in (Path(__file__),repo/'benchmarks/qwen_encoder.py'):code[p.relative_to(repo).as_posix()]=sha(p.read_bytes())
    plan={'evidence_mode':'LOCAL','generative_calls':0,'encoder':encoder,'device':device,
          'pack_sha256':sha(pack.read_bytes()),'task_plan_sha256':sha(tasks.read_bytes()),'code_sha256':code,
          'blocks':[{'id':b.id,'path':b.path,'span':b.span,'name':b.name,'sha256':sha(b.text.encode())} for b in blocks],
          'queries':[{'task_id':r['task_id'],'query':r['query']} for r in query_rows],
          'versions':{name:importlib.metadata.version(name) for name in ('torch','transformers','numpy','tokenizers')},
          'python':sys.version,
          'limits':['Research arrays require matching source hash; no incremental sidecar update is implemented',
                    'Query embeddings are timed separately and saved for reuse across budget diagnostics',
                    'MiniLM uses body prefix 2000 characters and 256 tokens; Qwen uses path/name/body and 512 tokens',
                    'Different models, devices and truncation policies are not algorithm-only speed comparisons',
                    'Encoder similarities are uncalibrated relevance signals, not evidence sufficiency']}
    output.mkdir(parents=True,exist_ok=resume)
    if resume:
        prior=read(output/'plan.json');assert prior==plan
    else:
        save(output/'plan.json',plan)
        capture=gzip.compress(json.dumps({name:(repo/name).read_bytes().decode() for name in code}).encode(),mtime=0)
        (output/'sources.json.gz').write_bytes(capture)
    parts=output/'parts';parts.mkdir(exist_ok=True)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL encoder attempted network')):
        started=time.perf_counter();cpu=time.process_time()
        if encoder=='minilm':
            from npk.context.embedding import LocalEmbeddingBackend,DOCUMENT_CHAR_LIMIT
            backend=LocalEmbeddingBackend()
            assert backend.available(), 'Required pinned MiniLM weights/runtime unavailable'
            identity=backend.identity();assert identity['revision']=='1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
            def encode(texts,query=False):
                values=backend.embed_matrix(texts)
                assert values is not None
                return np.asarray(values,dtype=np.float32)
            texts=[b.text[:DOCUMENT_CHAR_LIMIT] for b in blocks]
        else:
            from benchmarks.qwen_encoder import QwenEncoder
            backend=QwenEncoder(repo/'experiments/results/cycle14-qwen-download.json',device=device,max_length=512,batch_size=8)
            identity=backend.identity()
            encode=backend.encode
            texts=[f'File: {b.path}\nSymbol: {b.name or ""}\n{b.text}' for b in blocks]
        load={'wall_ms':1000*(time.perf_counter()-started),'cpu_ms':1000*(time.process_time()-cpu),
              'identity':identity,'torch_threads':torch.get_num_threads()}
        if not (output/'load.json').exists():save(output/'load.json',load)
        elif read(output/'load.json')['identity']!=identity:raise ValueError('Encoder identity changed on resume')
        def encoded_part(name,texts,query=False):
            dest=parts/(name+'.npy');metadata=parts/(name+'.json')
            input_sha=sha(json.dumps(texts,ensure_ascii=False).encode())
            if metadata.exists():
                saved=read(metadata)
                assert saved['input_sha256']==input_sha and saved['query']==query
                assert sha(dest.read_bytes())==saved['array_sha256']
                values=np.load(dest,allow_pickle=False)
            else:
                start=time.perf_counter();cpu=time.process_time()
                values=encode(texts,query=query)
                saved={'input_sha256':input_sha,'query':query,'wall_ms':1000*(time.perf_counter()-start),
                       'cpu_ms':1000*(time.process_time()-cpu),'rows':len(texts)}
                if encoder=='qwen':saved['tokenization']=dict(backend.last_batch)
                with dest.open('wb') as handle:np.save(handle,values,allow_pickle=False)
                saved['array_sha256']=sha(dest.read_bytes());save(metadata,saved)
            assert values.ndim==2 and values.shape[0]==len(texts) and np.isfinite(values).all()
            assert np.allclose(np.linalg.norm(values,axis=1),1,atol=1e-4)
            return values,saved
        document_parts=[];document_metrics=[]
        for start in range(0,len(blocks),128):
            values,metrics=encoded_part(f'doc-{start}',texts[start:start+128])
            document_parts.append(values);document_metrics.append(metrics)
            print({'phase':'documents','encoder':encoder,'done':min(start+128,len(blocks)),'planned':len(blocks)},flush=True)
        query_parts=[];query_metrics=[]
        for task in query_rows:
            values,metrics=encoded_part('query-'+sha(task['task_id'].encode()),[task['query']],query=True)
            query_parts.append(values);query_metrics.append({'task_id':task['task_id'],**metrics})
        for name,arrays in (('documents',document_parts),('queries',query_parts)):
            with (output/(name+'.npy')).open('wb') as handle:np.save(handle,np.concatenate(arrays),allow_pickle=False)
    import psutil
    report={'status':'COMPLETE','evidence_mode':'LOCAL','generative_calls':0,
            'plan_sha256':sha((output/'plan.json').read_bytes()),'identity':identity,
            'documents':len(blocks),'queries':len(query_rows),'document_batches':document_metrics,'query_metrics':query_metrics,
            'document_wall_ms':sum(r['wall_ms'] for r in document_metrics),
            'document_cpu_ms':sum(r['cpu_ms'] for r in document_metrics),
            'matrix_files':{name:{'bytes':(output/name).stat().st_size,'sha256':sha((output/name).read_bytes())} for name in ('documents.npy','queries.npy')},
            'rss_bytes_after_encoding':psutil.Process().memory_info().rss,'limits':plan['limits']}
    assert all(sha((repo/name).read_bytes())==digest for name,digest in code.items())
    save(output/'report.json',report)
    print({k:report[k] for k in ('status','documents','queries','document_wall_ms')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pack','tasks','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--encoder',choices=('minilm','qwen'),required=True)
    p.add_argument('--device',choices=('cpu','cuda'),default='cpu');p.add_argument('--resume',action='store_true')
    a=p.parse_args();run(a.pack,a.tasks,a.output,a.encoder,a.device,a.resume)

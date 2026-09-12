"""Experimental local Qwen embedding baseline; no generation or runtime registration.

Identity, query instruction, input truncation and last-token pooling are explicit.
Weights are downloaded separately and checked against the frozen download record.
"""
import hashlib
import json
from pathlib import Path
import time

MODEL='Qwen/Qwen3-Embedding-0.6B'
REVISION='97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3'
INSTRUCTION='Given a question about Python library behavior, retrieve source code and documentation that help answer the question.'


def last_token_pool(hidden,mask):
    import torch
    # Works for either padding direction; never select padded positions.
    positions=torch.arange(mask.shape[1],device=mask.device).expand_as(mask)
    indices=positions.masked_fill(mask==0,-1).max(dim=1).values
    if bool((indices<0).any()):raise ValueError('cannot pool an empty token sequence')
    return hidden[torch.arange(hidden.shape[0],device=hidden.device),indices]


class QwenEncoder:
    def __init__(self,record,*,device='cuda',max_length=512,batch_size=8):
        if device not in ('cpu','cuda'):raise ValueError('explicit cpu or cuda device required')
        if type(max_length) is not int or not 1<=max_length<=32768:raise ValueError('invalid maximum length')
        if type(batch_size) is not int or batch_size<1:raise ValueError('invalid batch size')
        self.started=time.perf_counter();data=json.loads(Path(record).read_text())
        if (data['model'],data['revision'])!=(MODEL,REVISION):raise ValueError('wrong frozen encoder')
        snapshot=Path(data['snapshot']);checked=0
        for row in data['files']:
            path=snapshot/row['name'];h=hashlib.sha256()
            with path.open('rb') as handle:
                for part in iter(lambda:handle.read(1024*1024),b''):h.update(part)
            if h.hexdigest()!=row['sha256']:raise ValueError('model snapshot differs from frozen bytes')
            checked+=1
        import torch
        from transformers import AutoTokenizer,AutoModel
        torch.set_num_threads(4)
        if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('configured GPU is unavailable')
        self.device=device;self.batch_size=batch_size;self.max_length=max_length
        self.dtype=torch.float16 if device=='cuda' else torch.float32
        self.tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False,padding_side='left')
        self.model=AutoModel.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False,
                                           dtype=self.dtype,use_safetensors=True,attn_implementation='sdpa').to(device).eval()
        if device=='cuda':torch.cuda.synchronize()
        self.load_seconds=time.perf_counter()-self.started;self.checked_files=checked

    def identity(self):
        return {'model':MODEL,'revision':REVISION,'max_length':self.max_length,'batch_size':self.batch_size,
                'pooling':'last_nonpadding_token_l2','instruction':INSTRUCTION,'device':self.device,
                'dtype':str(self.dtype),'attention':'sdpa','generative_calls':0,'checked_snapshot_files':self.checked_files}

    def encode(self,texts,*,query=False):
        import numpy as np
        import torch
        self.last_batch={'texts':0,'untruncated_tokens':0,'truncated_texts':0,'encoded_tokens':0}
        if not texts:return np.empty((0,self.model.config.hidden_size),dtype=np.float32)
        vectors=[];lengths=[];truncated=0
        for start in range(0,len(texts),self.batch_size):
            batch=texts[start:start+self.batch_size]
            if query:batch=[f'Instruct: {INSTRUCTION}\nQuery:{text}' for text in batch]
            original=self.tokenizer(batch,add_special_tokens=True,truncation=False)['input_ids']
            lengths.extend(map(len,original));truncated+=sum(len(t)>self.max_length for t in original)
            encoded=self.tokenizer(batch,padding=True,truncation=True,max_length=self.max_length,return_tensors='pt').to(self.device)
            with torch.inference_mode():
                output=self.model(**encoded)
                pooled=last_token_pool(output.last_hidden_state,encoded['attention_mask'])
                pooled=torch.nn.functional.normalize(pooled.float(),p=2,dim=1)
            vectors.append(pooled.cpu().numpy())
        self.last_batch={'texts':len(texts),'untruncated_tokens':sum(lengths),'truncated_texts':truncated,
                         'encoded_tokens':sum(min(n,self.max_length) for n in lengths)}
        return np.concatenate(vectors)

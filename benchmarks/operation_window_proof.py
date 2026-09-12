"""Reproduce the encoder's actual input features using the pinned local tokenizer."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from benchmarks.prospective_eval import write_json
from npk.context.embedding import DEFAULT_MODEL_ID,DEFAULT_MODEL_REVISION,MODEL_CACHE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    windows=json.loads((a.local/'encoder-windows.json').read_text());result=json.loads((a.local/'results.json').read_text())
    identity=result['builds']['semantic2048']['encoder_identity']
    assert identity['model_id']==DEFAULT_MODEL_ID and identity['revision']==DEFAULT_MODEL_REVISION
    with patch('socket.socket.connect',side_effect=AssertionError('Tokenizer proof attempted network')):
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(DEFAULT_MODEL_ID,revision=DEFAULT_MODEL_REVISION,cache_dir=str(MODEL_CACHE),local_files_only=True,trust_remote_code=False)
        rows=[];groups={}
        for row in windows:
            features=dict(tokenizer([row['views']['full']['text']],padding=True,truncation=True,max_length=identity['max_length']))
            payload=json.dumps(features,sort_keys=True,separators=(',',':')).encode();digest=hashlib.sha256(payload).hexdigest()
            assert len(features['input_ids'][0])==row['views']['full']['kept_encoder_tokens']
            rows.append({'task':row['task'],'layout':row['layout'],'encoder_input_sha256':digest,'features':features})
            groups.setdefault(digest,[]).append(row['task'])
    padded=[r for r in rows if r['layout']=='padded'];assert len(padded)==20 and len({r['encoder_input_sha256'] for r in padded})==1
    proof={'evidence_mode':'LOCAL','generative_calls':0,'encoder_identity':identity,'requests':len(rows),'input_groups':groups,'rows':rows,
           'identical_padded_inputs':len(padded),'interpretation':'Identical features imply identical deterministic encoder outputs under fixed model/evaluation assumptions. Hybrid still has a full-query lexical channel.',
           'limitation':'The target answer model receives the full original query; this is a limitation of the truncated retrieval representation, not an answer-impossibility theorem.'}
    write_json(a.output,proof);print({'requests':len(rows),'unique_encoder_inputs':len(groups),'identical_padded_inputs':len(padded)},flush=True)


if __name__=='__main__':main()

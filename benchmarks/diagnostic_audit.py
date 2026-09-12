"""Independently reconstruct frozen diagnostic prompts before spending calls."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.prospective_eval import request_key,write_json


def sha(data):return hashlib.sha256(data).hexdigest()


def audit(root):
    repo=Path(__file__).resolve().parents[1];reports=[];snapshot={}
    for model in ('deepseek','nemotron'):
        folder=root/model;raw=(folder/'plan.json').read_bytes()
        assert sha(raw)==(folder/'plan.sha256').read_text().strip()
        plan=json.loads(raw);questions={t['id']:t['question'] for t in plan['dataset']['tasks']}
        source={}
        for item in plan['source_manifest']:
            data=(root/'source'/item['path']).read_bytes();assert sha(data)==item['sha256']
            source[item['path']]=data.decode('utf-8').replace('\r\n','\n').replace('\r','\n').split('\n')
        for path,digest in plan['code_sha256'].items():
            data=(repo/path).read_bytes();assert sha(data)==digest
            snapshot[path]={'sha256':digest,'text':data.decode('utf-8')}
        paired={};failed=0
        for row in plan['observations']:
            parts=[]
            for piece in row['evidence']:
                lines=source[piece['path']];start,end=piece['start'],piece['end']
                assert 1<=start<=end<=len(lines)
                literal='\n'.join(lines[start-1:end]);assert literal==piece['text']
                if row['rendering']=='provenance_labels':
                    literal=f"[Source: {piece['path']}:{start}-{end}; symbols: {json.dumps(piece['symbols'],ensure_ascii=False)}]\n"+literal
                parts.append(literal)
            context='\n\n'.join(parts);encoded=context.encode()
            assert sha(encoded)==row['context_sha256']
            assert encoded==(folder/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
            # Reproduce the declared floor(chars/4) convention, not a tokenizer.
            tokens=max(1,len(context)//4) if context else 0
            assert tokens==row['selected_tokens']
            assert row['budget'] is None or tokens<=row['budget']
            assert request_key(plan['settings'],questions[row['task']],context)==row['request_sha256']
            failed+=row.get('status')=='SELECTION_FAILED'
            if row['method'] in ('bm25_labeled','bm25_same_blocks'):
                paired.setdefault((row['task'],row['budget']),[]).append(row['evidence'])
        assert len(paired)==16 and all(len(pair)==2 and pair[0]==pair[1] for pair in paired.values())
        assert not (folder/'ledger.json').exists() or not json.loads((folder/'ledger.json').read_text()),'preflight requires an unattempted run'
        reports.append({'model':model,'plan_sha256':sha(raw),'observations':len(plan['observations']),
                        'unique_requests':len(plan['requests']),'same_source_pairs':len(paired),
                        'selection_failures':failed,'source_files':len(source),
                        'literal_sources_and_prompts_valid':True,'generative_calls':0})
    destination=root/'preparation-sources.json.gz'
    assert not destination.exists()
    with gzip.open(destination,'wb') as handle:handle.write(json.dumps(snapshot,ensure_ascii=False).encode())
    report={'evidence_mode':'LOCAL','reports':reports,'source_snapshot_sha256':sha(destination.read_bytes()),
            'auditor_sha256':sha(Path(__file__).read_bytes())}
    write_json(root/'preflight.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    audit(parser.parse_args().run.resolve())

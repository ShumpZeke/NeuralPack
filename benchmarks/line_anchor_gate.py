"""LOCAL boundary-stability gate; no update speed or answer-quality inference."""
import argparse
from collections import Counter
from functools import partial
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch
from benchmarks.line_anchors import split_anchored
from benchmarks.prospective_eval import write_json
from npk.pack.compile import split_source,_source_lines,TEXT_SUFFIXES


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def edit(text,kind,language):
    marker='/* NeuralPack boundary experiment */' if language=='c' else '.. NeuralPack boundary experiment'
    lines=_source_lines(text)
    if kind=='append':return text+'\n'+marker+'\n'
    if kind=='prepend_blank':return '\n'+text
    if kind=='middle_insert':lines.insert(len(lines)//2,marker)
    elif kind=='middle_replace':lines[len(lines)//2]=marker
    elif kind=='one_percent':
        indexes=random.Random(2301).sample(range(len(lines)),max(1,len(lines)//100))
        for i in indexes:lines[i]=marker+' '+str(i)
    elif kind not in ('append','prepend_blank'):raise ValueError('Unknown edit')
    return '\n'.join(lines)+'\n'


def coverage(text,blocks):
    lines=_source_lines(text);covered=set()
    for b in blocks:
        assert b.text=='\n'.join(lines[b.start_line-1:b.end_line])
        span=set(range(b.start_line,b.end_line+1));assert not covered&span;covered|=span
    assert all(i in covered for i,line in enumerate(lines,1) if line.strip())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('New evidence directory required')
    inputs=[]
    for folder in ('cycle22-block-update-v1','cycle19-manuals-v1'):
        parent=repo/'experiments/runs/packs'/folder;acquisition=read(parent/'acquisition.json')
        for item in acquisition['source_manifest']:
            if Path(item['path']).suffix not in ('.c','.rst'):continue
            # Cycle 19's three added CPython manuals only; other old RST files
            # remain available for later held-out checks.
            if folder=='cycle19-manuals-v1' and item['path'] not in {
                'cpython/Doc/library/collections.rst','cpython/Doc/library/functools.rst',
                'cpython/Doc/library/contextlib.rst'}:continue
            body=(parent/'source'/item['path']).read_bytes();assert sha(body)==item['sha256']
            inputs.append({'path':item['path'],'text':body.decode(),'bytes':body,'sha256':sha(body),
                           'language':TEXT_SUFFIXES[Path(item['path']).suffix],'origin':folder})
    assert len(inputs)==5
    root.mkdir(parents=True);source=root/'source';source.mkdir()
    for item in inputs:
        dest=source/item['path'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(item['bytes'])
    methods={'baseline':split_source,'anchor_4800':split_anchored,
             'anchor_4800_min512':partial(split_anchored,min_chars=512),
             'anchor_2048':partial(split_anchored,max_chars=2048)}
    kinds=('append','prepend_blank','middle_insert','middle_replace','one_percent')
    code={name:sha((repo/name).read_bytes()) for name in ('benchmarks/line_anchors.py','benchmarks/line_anchor_gate.py','npk/pack/compile.py')}
    manifest={'evidence_mode':'LOCAL','generative_calls':0,'trials':3,'code_sha256':code,
              'source_manifest':[{k:v for k,v in item.items() if k not in ('text','bytes')} for item in inputs],
              'methods':list(methods),'edits':list(kinds),
              'limitations':['Five previously available public files, not unseen tasks or repositories',
                             'Splitter-only timing, not update latency, disk or query performance',
                             'Three shuffled repetitions, warm filesystem, uncontrolled host load',
                             'No answer quality or safe-context sufficiency measurement',
                             'CRC32 is a boundary hint, not cryptographic integrity or FastCDC']}
    write_json(root/'manifest.json',manifest);rows=[];rng=random.Random(2309)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL gate attempted network')):
        for trial in range(3):
            order=[(item,name,kind) for item in inputs for name in methods for kind in kinds];rng.shuffle(order)
            for item,name,kind in order:
                changed=edit(item['text'],kind,item['language']);fn=methods[name]
                old=fn(item['text'],item['language']);old_count=Counter((b.kind,b.name,b.text) for b in old)
                start=time.perf_counter_ns();new=fn(changed,item['language']);elapsed=(time.perf_counter_ns()-start)/1e6
                coverage(changed,new);new_count=Counter((b.kind,b.name,b.text) for b in new);shared=old_count&new_count
                row={'file':item['path'],'case':kind,'method':name,'trial':trial,'split_ms':elapsed,
                     'source_sha256':sha(changed.encode()),'source_chars':len(changed),
                     'old_blocks':len(old),'new_blocks':len(new),'reused_blocks':sum(shared.values()),
                     'reused_chars':sum(len(key[2])*count for key,count in shared.items()),
                     'selected_chars_total':sum(len(b.text) for b in new),'max_block_chars':max(map(lambda b:len(b.text),new)),
                     'blocks_over_4800':sum(len(b.text)>4800 for b in new)}
                rows.append(row)
    assert code=={name:sha((repo/name).read_bytes()) for name in code}
    summary=[]
    for item in inputs:
        for name in methods:
            for kind in kinds:
                group=[r for r in rows if (r['file'],r['method'],r['case'])==(item['path'],name,kind)]
                signature={json.dumps({k:v for k,v in r.items() if k not in ('trial','split_ms')},sort_keys=True) for r in group}
                assert len(signature)==1 and len(group)==3
                row=json.loads(signature.pop());row['median_split_ms']=statistics.median(r['split_ms'] for r in group)
                row['retained_payload_fraction']=row['reused_chars']/row['selected_chars_total'];summary.append(row)
    write_json(root/'results.json',{**manifest,'status':'COMPLETE','rows':rows,'summary':summary})
    print({'complete':True,'rows':len(rows),'sources':len(inputs)})
    for row in summary:
        if row['case']=='prepend_blank':print({k:row[k] for k in ('file','method','retained_payload_fraction','median_split_ms','new_blocks','max_block_chars')})


if __name__=='__main__':main()

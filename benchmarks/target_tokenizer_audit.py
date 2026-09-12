"""Compare a pinned public tokenizer with past provider usage, without model calls.

Only allowlisted tokenizer/config/template/license data is downloaded. No model
weights, remote Python modules, credentials or generative optimization are used.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import urllib.request

from benchmarks.answer_records import validate_origin, validate_response
from benchmarks.repository_eval import answer_payload
from benchmarks.prospective_eval import request_key
from npk.pack.source_policy import check_source


MODEL = 'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16'
REVISION = '2dc98e2afe4face0e4ce40972a915c45368bd34a'
LIMIT = 32 * 1024 * 1024


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def download(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        body = response.read(LIMIT+1)
    if len(body) > LIMIT: raise ValueError('Tokenizer asset exceeds data-only size cap')
    return body


def acquire(output):
    if output.exists(): raise ValueError('Fresh tokenizer acquisition directory required')
    metadata = download(f'https://huggingface.co/api/models/{MODEL}/revision/{REVISION}')
    info = json.loads(metadata)
    if info['sha'] != REVISION: raise ValueError('Tokenizer revision mismatch')
    names = {item['rfilename'] for item in info['siblings']}
    required = {'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'}
    if not required <= names: raise ValueError('Pinned tokenizer assets are incomplete')
    wanted = required | ({'special_tokens_map.json', 'LICENSE', 'LICENSE.txt', 'README.md'} & names)
    assets = {name: download(f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}') for name in sorted(wanted)}
    for name, body in assets.items(): check_source(body.decode('utf-8'), name)
    output.mkdir(parents=True)
    (output/'metadata.json').write_bytes(metadata)
    for name, body in assets.items(): (output/name).write_bytes(body)
    manifest = {'evidence_mode':'LOCAL', 'generative_calls':0, 'created_utc':datetime.now(timezone.utc).isoformat(),
                'model_repository':MODEL, 'revision':REVISION, 'metadata_sha256':sha(metadata),
                'files':{name:{'sha256':sha(body),'bytes':len(body)} for name,body in assets.items()},
                'limitations':['Public model tokenizer is a candidate; hosted NIM tokenizer/template equivalence must be tested',
                               'No weights or remote model code were downloaded']}
    (output/'acquisition.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print({'files':len(assets),'bytes':sum(map(len,assets.values())),'revision':REVISION},flush=True)


def audit(assets, run, output):
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    from tokenizers import Tokenizer
    import importlib.metadata
    manifest = read(assets/'acquisition.json')
    for name, info in manifest['files'].items(): assert sha((assets/name).read_bytes()) == info['sha256']
    tokenizer = Tokenizer.from_file(str(assets/'tokenizer.json'))
    template = ImmutableSandboxedEnvironment(trim_blocks=True,lstrip_blocks=True).from_string((assets/'chat_template.jinja').read_text())
    plan = read(run/'plan.json'); ledger = read(run/'ledger.json'); rows=[]
    for key, entry in ledger.items():
        assert entry['state'] == 'DONE'
        result=entry['result']; validate_origin(run,result); validate_response(result)
        if not result.get('transport_success'): continue
        request=plan['requests'][key]
        context=(run/'contexts'/(request['context_sha256']+'.txt')).read_bytes()
        assert sha(context)==request['context_sha256']
        settings=plan['settings']
        assert settings['model']=='nvidia/nemotron-3-super-120b-a12b'
        assert request_key(settings,request['question'],context.decode())==key
        payload=answer_payload(settings['model'],request['question'],context.decode(),
                               **{k:v for k,v in settings.items() if k not in {'model','timeout_seconds'}})
        rendered=template.render(messages=payload['messages'],add_generation_prompt=True,
                                 **settings.get('chat_template_kwargs',{}))
        local=len(tokenizer.encode(rendered,add_special_tokens=False).ids)
        raw_context=len(tokenizer.encode(context.decode(),add_special_tokens=False).ids)
        actual=result['usage']['prompt_tokens']
        rows.append({'request_sha256':key,'evidence_mode':result['evidence_mode'],
                     'reported_prompt_tokens':actual,'local_framed_tokens':local,'delta':local-actual,
                     'local_context_tokens':raw_context,'context_chars4_estimate':max(1,len(context.decode())//4) if context else 0})
    differences=[r['delta'] for r in rows]
    report={'status':'AUDITED','evidence_mode':'LOCAL','generative_calls':0,'new_api_calls':0,
            'revision':REVISION,'plan_sha256':sha((run/'plan.json').read_bytes()),'rows':rows,
            'versions':{name:importlib.metadata.version(name) for name in ('tokenizers','jinja2')},
            'matching_usage_records':sum(d==0 for d in differences),'records':len(rows),
            'delta_counts':dict(Counter(differences)),
            'limitations':['Comparisons reuse completed responses; no failed request is retried',
                           'Matching sampled usage does not prove that the hosted implementation never changes',
                           'Different framing counts must be reported before claiming exact hosted prompt budgets']}
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({k:report[k] for k in ('records','matching_usage_records','delta_counts')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('acquire','audit'))
    p.add_argument('--assets',type=Path,required=True);p.add_argument('--run',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.action=='acquire':acquire(a.assets)
    else:audit(a.assets,a.run,a.output)

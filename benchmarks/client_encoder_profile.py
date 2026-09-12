"""Fresh-process optional-client profile; real offline encoder, MOCK target."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time
import zipfile


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p, value): p.write_text(json.dumps(value, indent=2), encoding='utf-8')


def worker(a):
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['NPK_ENABLE_EMBEDDINGS'] = '0' if a.arm == 'before_disabled' else '1'
    sys.path.insert(0, str(a.package.resolve()))
    import socket
    def denied(*args, **kwargs): raise AssertionError('profile attempted network')
    socket.socket.connect = denied
    import psutil
    rss_before = psutil.Process().memory_info().rss
    start = time.perf_counter()
    from npk.runtime import NeuralPackClient
    from npk.context.analyzer import estimate_tokens
    import npk.context.embedding as embedding
    # A git snapshot has a different package-relative model directory. Both
    # arms deliberately use the same installed local cache, never a download.
    embedding.MODEL_CACHE = a.model_cache
    import_ms = (time.perf_counter()-start)*1000
    items = json.loads((a.root/'inputs.json').read_text()); rows = []
    for item in items:
        context = (a.root/item['file']).read_text(encoding='utf-8')
        messages = [{'role':'system','content':'Use supplied source and explicitly identify missing evidence.'},
                    {'role':'user','content':context},
                    {'role':'user','content':'How are inherited defaults overridden by section-specific options?'}]
        opts = {'use_local_embeddings': True} if a.arm == 'after_enabled' else {}
        client = NeuralPackClient(provider='mock',default_model='unpriced-example',
                                 trace_path=str(a.root/f'{a.arm}-{a.trial}-{item["target"]}.jsonl'),**opts)
        sent = []; original = client.provider.chat_completion
        def capture(*args, **kwargs):
            sent.append(kwargs['messages']); return original(*args, **kwargs)
        client.provider.chat_completion = capture
        for repeat in range(2):
            start = time.perf_counter(); cpu = time.process_time()
            response = client.chat_completion(messages)
            wall_ms = (time.perf_counter()-start)*1000; cpu_ms = (time.process_time()-cpu)*1000
            actual = sent[-1]
            assert len(sent) == repeat+1 and actual[0] == messages[0] and actual[-1] == messages[-1]
            assert any(m['content'].strip() for m in actual[1:-1])
            backend = embedding.get_backend()
            rows.append({**item,'arm':a.arm,'trial':a.trial,'repeat':repeat,'wall_ms':wall_ms,'cpu_ms':cpu_ms,
                         'rss_after':psutil.Process().memory_info().rss,
                         'messages_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest(),
                         'original_messages_sha256':hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest(),
                         'selected_tokens':sum(estimate_tokens(m['content']) for m in actual),
                         'plan':response.raw['neuralpack_plan'], 'query_system_context_preserved':True,
                         'provider_calls':1,'torch_loaded':'torch' in sys.modules,'transformers_loaded':'transformers' in sys.modules,
                         'encoder_load_attempted':backend._load_attempted,'encoder_loaded':backend._model is not None})
    backend = embedding.get_backend()
    identity = backend.identity() if backend._model is not None else None
    if a.arm in ('before_default','after_enabled') and identity is None:
        raise ValueError('encoder arm did not load the pinned local model')
    if a.arm in ('before_disabled','after_default') and any(r['torch_loaded'] or r['encoder_load_attempted'] for r in rows):
        raise ValueError('deterministic arm probed a model')
    dump(a.root/f'{a.arm}-{a.trial}.json', {'rows':rows,'import_ms':import_ms,'rss_before':rss_before,
                                         'encoder_identity':identity})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--worker',action='store_true')
    p.add_argument('--package',type=Path);p.add_argument('--arm');p.add_argument('--trial',type=int)
    p.add_argument('--model-cache',type=Path);p.add_argument('--output',type=Path)
    a = p.parse_args(); a.root = a.root.resolve()
    if a.worker: return worker(a)
    if a.root.exists() or a.output.exists(): raise ValueError('new profile output required')
    a.root.mkdir(parents=True);repo=Path(__file__).resolve().parents[1]
    source=repo/'experiments/runs/packs/cycle16-policy-final'
    for path in [source/'inputs.json',*source.glob('context-*.txt')]:shutil.copyfile(path,a.root/path.name)
    baseline=a.root/'baseline';baseline.mkdir()
    raw=subprocess.run(['git','archive','--format=zip','5a22535','npk'],check=True,capture_output=True).stdout
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if not (baseline/name).resolve().is_relative_to(baseline):raise ValueError('invalid snapshot path')
        z.extractall(baseline)
    current={p.relative_to(repo).as_posix():sha(p) for p in (repo/'npk').rglob('*.py')}
    manifest={'champion':'5a22535','candidate_source_sha256':current,
              'inputs_sha256':{p.name:sha(p) for p in a.root.glob('*') if p.is_file()},
              'evidence_mode':'LOCAL','target_mode':'MOCK','generative_calls':0,
              'shared_model_cache':str(repo/'experiments/models/hf_cache')}
    dump(a.root/'manifest.json',manifest);runs=[];rng=random.Random(1717)
    for trial in range(3):
        arms=['before_default','before_disabled','after_default','after_enabled'];rng.shuffle(arms)
        for arm in arms:
            package=baseline if arm.startswith('before') else repo
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--root',str(a.root),
                            '--package',str(package),'--arm',arm,'--trial',str(trial),
                            '--model-cache',manifest['shared_model_cache']],check=True)
            run=json.loads((a.root/f'{arm}-{trial}.json').read_text());run['arm']=arm;run['trial']=trial;runs.append(run)
            print({'arm':arm,'trial':trial,'complete':True},flush=True)
    assert current=={p.relative_to(repo).as_posix():sha(p) for p in (repo/'npk').rglob('*.py')}
    rows=[r for run in runs for r in run['rows']];summary=[]
    for arm in ['before_default','before_disabled','after_default','after_enabled']:
        for target in (2000,25000,50000,100000):
            group=[r for r in rows if r['arm']==arm and r['target']==target]
            summary.append({'arm':arm,'target':target,'context_tokens':group[0]['context_chars_div4_tokens'],
                            'first_median_ms':statistics.median(r['wall_ms'] for r in group if r['repeat']==0),
                            'warm_median_ms':statistics.median(r['wall_ms'] for r in group if r['repeat']==1),
                            'rss_after_median':statistics.median(r['rss_after'] for r in group),
                            'original_message_matches':sum(r['messages_sha256']==r['original_messages_sha256'] for r in group)})
    dump(a.output,{**manifest,'runs':runs,'summary':summary,
                   'limits':['Three shuffled fresh-process trials per arm; four real-context sizes; one repeat per size',
                             'Cold 2K call includes model initialization; later sizes can reuse model and query vector',
                             'Real local encoder, no network, MOCK target; no answer-quality or billing claims',
                             'Same cache explicitly supplied to both code snapshots; identity required for enabled arms',
                             'All timing includes MOCK target and trace I/O; RSS after is not peak; OS activity uncontrolled',
                             'Only older optional client, not the compiled .npk query runtime']})
    print(summary,flush=True)


if __name__=='__main__':main()

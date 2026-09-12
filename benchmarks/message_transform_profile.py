"""Paired fresh-process client overhead after removing unsafe generic transforms."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import zipfile
import statistics


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path, value): path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def worker(a):
    sys.path.insert(0, str((a.root/a.arm).resolve()))
    import socket
    def denied(*args, **kwargs): raise AssertionError('LOCAL profile attempted network')
    socket.socket.connect = denied
    import psutil
    start = time.perf_counter()
    from npk.runtime import NeuralPackClient
    import_ms = (time.perf_counter()-start)*1000
    rows = []
    for item in json.loads((a.root/'inputs.json').read_text()):
        context = (a.root/item['file']).read_text(encoding='utf-8')
        original = [{'role':'system','content':'Use supplied source and explicitly identify missing evidence.'},
                    {'role':'user','content':context},
                    {'role':'user','content':'How are inherited defaults overridden by section-specific options?'}]
        client = NeuralPackClient(provider='mock', default_model='unpriced-example',
                                 trace_path=str(a.root/f'{a.arm}-{a.trial}-{item["target"]}.jsonl'))
        sent = []; dispatch = client.provider.chat_completion
        def capture(*args, **kwargs):
            sent.append(kwargs['messages']); return dispatch(*args, **kwargs)
        client.provider.chat_completion = capture
        for repeat in range(3):
            start = time.perf_counter_ns(); cpu = time.process_time_ns()
            result = client.chat_completion(original)
            cpu_ms = (time.process_time_ns()-cpu)/1e6; wall_ms = (time.perf_counter_ns()-start)/1e6
            assert len(sent) == repeat+1
            assert sent[-1][0] == original[0] and sent[-1][-1] == original[-1]
            assert 'torch' not in sys.modules and 'transformers' not in sys.modules
            rows.append({'target':item['target'], 'available_chars_div4':len(context)//4,
                         'repeat':repeat,'wall_ms':wall_ms,'cpu_ms':cpu_ms,
                         'rss_after':psutil.Process().memory_info().rss,'provider_calls':1,
                         'original':original,'dispatched':sent[-1], 'unchanged':original == sent[-1],
                         'plan':result.raw['neuralpack_plan']})
    dump(a.root/f'{a.arm}-{a.trial}.json', {'arm':a.arm,'trial':a.trial,'import_ms':import_ms,'rows':rows})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True); p.add_argument('--output',type=Path)
    p.add_argument('--worker',action='store_true'); p.add_argument('--arm'); p.add_argument('--trial',type=int)
    a=p.parse_args();a.root=a.root.resolve()
    if a.worker:return worker(a)
    if a.root.exists() or a.output.exists():raise ValueError('new profile required')
    a.root.mkdir(parents=True);repo=Path(__file__).resolve().parents[1]
    source=repo/'experiments/runs/packs/cycle17-client-profile-v1'
    for path in [source/'inputs.json',*source.glob('context-*.txt')]:shutil.copyfile(path,a.root/path.name)
    baseline=a.root/'before';baseline.mkdir()
    raw=subprocess.run(['git','archive','--format=zip','2f4543d','npk'],check=True,capture_output=True).stdout
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if any(not (baseline/name).resolve().is_relative_to(baseline) for name in z.namelist()):
            raise ValueError('unsafe snapshot path')
        z.extractall(baseline)
    shutil.copytree(repo/'npk',a.root/'after/npk',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    current={f.relative_to(repo).as_posix():sha(f) for f in (repo/'npk').rglob('*.py')}
    manifest={'champion_before':'2f4543d','candidate_source_sha256':current,
              'input_sha256':{f.name:sha(f) for f in a.root.glob('*.txt')},'inputs_sha256':sha(a.root/'inputs.json'),
              'profiler_sha256':sha(Path(__file__)),'evidence_mode':'LOCAL','target_mode':'MOCK','generative_calls':0}
    dump(a.root/'manifest.json',manifest)
    runs=[];rng=random.Random(1819)
    for trial in range(3):
        arms=['before','after'];rng.shuffle(arms)
        for arm in arms:
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--root',str(a.root),
                            '--arm',arm,'--trial',str(trial)],check=True)
            runs.append(json.loads((a.root/f'{arm}-{trial}.json').read_text()))
            print({'arm':arm,'trial':trial,'complete':True},flush=True)
    assert current == {f.relative_to(repo).as_posix():sha(f) for f in (repo/'npk').rglob('*.py')}
    summary=[]
    for arm in ('before','after'):
        for target in (2000,25000,50000,100000):
            rows=[r for run in runs if run['arm']==arm for r in run['rows'] if r['target']==target]
            summary.append({'arm':arm,'target':target,'available_chars_div4':rows[0]['available_chars_div4'],
                            'first_median_ms':statistics.median(r['wall_ms'] for r in rows if r['repeat']==0),
                            'warm_median_ms':statistics.median(r['wall_ms'] for r in rows if r['repeat']>0),
                            'rss_after_median':statistics.median(r['rss_after'] for r in rows),
                            'unchanged_dispatches':sum(r['unchanged'] for r in rows),'dispatches':len(rows)})
    dump(a.output,{**manifest,'runs':runs,'summary':summary,
                   'limitations':['Three shuffled fresh processes per arm; first call and two warm repeats per size',
                                  'Real public-source contexts, MOCK target; no answer-quality or billing inference',
                                  'Includes trace IO and MOCK dispatch; imports measured separately; RSS after is not peak',
                                  'LIVE answer IO overlapped; no CPU tests/mutations; OS caches and other host activity uncontrolled',
                                  'Older chat client only; compiled .npk source and retrieval remain unchanged']})
    print(summary,flush=True)


if __name__=='__main__':main()

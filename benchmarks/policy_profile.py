"""Paired legacy-client policy/overhead checks on literal public source; MOCK target."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time
import zipfile


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def worker(a):
    sys.path.insert(0, str(a.package.resolve()))
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import socket
    def denied(*args, **kwargs): raise AssertionError('profile attempted network')
    socket.socket.connect = denied
    from npk.runtime import NeuralPackClient
    from npk.context.analyzer import estimate_tokens
    import psutil
    manifest = json.loads((a.root/'inputs.json').read_text()); rows = []
    for item in manifest:
        context = (a.root/item['file']).read_text(encoding='utf-8')
        query = 'How are inherited defaults overridden by section-specific options?'
        system = 'Use supplied source and explicitly identify missing evidence.'
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': context}, {'role': 'user', 'content': query}]
        for mode in ('optimized', 'shadow'):
            trace = a.root/f'{a.arm}-{a.trial}-{item["target"]}-{mode}.jsonl'
            client = NeuralPackClient(provider='mock', default_model='unpriced-example', mode=mode, trace_path=str(trace))
            sent = []; original = client.provider.chat_completion
            def capture(*args, **kwargs):
                sent.append(kwargs['messages']); return original(*args, **kwargs)
            client.provider.chat_completion = capture
            for repeat in range(2):
                start = time.perf_counter(); cpu = time.process_time()
                client.chat_completion(messages)
                cpu_ms = (time.process_time()-cpu)*1000; wall_ms = (time.perf_counter()-start)*1000
                actual = sent[-1]
                assert len(sent) == repeat+1 and actual[0] == messages[0] and actual[-1] == messages[-1]
                assert any(m.get('content', '').strip() for m in actual[1:-1])
                record = json.loads(trace.read_text().splitlines()[-1])
                rows.append({**item, 'arm': a.arm, 'trial': a.trial, 'mode': mode, 'repeat': repeat,
                             'wall_ms': wall_ms, 'cpu_ms': cpu_ms, 'rss_bytes_after': psutil.Process().memory_info().rss,
                             'actual_dispatched_tokens_estimate': sum(estimate_tokens(m['content']) for m in actual),
                             'reported_tokens_avoided': record['tokens_avoided'], 'reported_cost_saved': record['cost_saved_est'],
                             'provider_calls': 1, 'system_query_and_nonempty_context_preserved': True})
    a.output.write_text(json.dumps(rows, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True); p.add_argument('--corpus', type=Path)
    p.add_argument('--worker', action='store_true'); p.add_argument('--package', type=Path)
    p.add_argument('--arm'); p.add_argument('--trial', type=int); p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.worker: return worker(a)
    if a.root.exists(): raise ValueError('new output directory required')
    a.root.mkdir(parents=True); repo = Path(__file__).resolve().parents[1]
    baseline = a.root/'baseline'; baseline.mkdir()
    raw = subprocess.run(['git', 'archive', '--format=zip', '5429fa7', 'npk'], check=True, capture_output=True).stdout
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            target = (baseline/name).resolve()
            if not target.is_relative_to(baseline.resolve()): raise ValueError('invalid snapshot path')
        z.extractall(baseline)
    source = sorted([f for f in a.corpus.rglob('*') if f.suffix in ('.py', '.rst', '.md')], key=lambda f: (f.stat().st_size, f.as_posix()))
    inputs = []
    for target in (2000, 25000, 50000, 100000):
        pieces = []; hashes = {}
        for path in source:
            text = path.read_text(encoding='utf-8')
            pieces.append(f'```File: {path.relative_to(a.corpus).as_posix()}\n{text}\n```')
            hashes[path.relative_to(a.corpus).as_posix()] = sha(path)
            if len('\n\n'.join(pieces))//4 >= target: break
        body = '\n\n'.join(pieces); filename = f'context-{target}.txt'
        (a.root/filename).write_text(body, encoding='utf-8')
        inputs.append({'target': target, 'file': filename, 'context_chars_div4_tokens': len(body)//4, 'source_sha256': hashes})
    (a.root/'inputs.json').write_text(json.dumps(inputs, indent=2))
    rows = []; rng = random.Random(1616)
    for trial in range(3):
        arms = [('before', baseline), ('after', repo)]; rng.shuffle(arms)
        for arm, package in arms:
            output = a.root/f'{arm}-{trial}.json'
            subprocess.run([sys.executable, str(Path(__file__)), '--worker', '--root', str(a.root.resolve()),
                            '--package', str(package.resolve()), '--arm', arm, '--trial', str(trial), '--output', str(output.resolve())], check=True)
            rows.extend(json.loads(output.read_text())); print({'trial': trial, 'arm': arm, 'complete': True}, flush=True)
    summary = [{'target': n, 'mode': mode, 'arm': arm,
                'warm_median_ms': statistics.median(r['wall_ms'] for r in rows if r['target'] == n and r['mode'] == mode and r['arm'] == arm and r['repeat'] == 1)}
               for n in (2000,25000,50000,100000) for mode in ('optimized','shadow') for arm in ('before','after')]
    current = {f.relative_to(repo).as_posix():sha(f) for f in (repo/'npk').rglob('*.py')}
    a.output.write_text(json.dumps({'evidence_mode':'LOCAL', 'target_mode':'MOCK', 'rows':rows, 'summary':summary,
                                   'candidate_source_sha256':current, 'champion':'5429fa7',
                                   'limits':['Literal whole public files wrapped for legacy client, not compiled-runtime benchmarks',
                                             'Three shuffled process pairs; one first and one repeat call per size/mode',
                                             'Timings include mock target and trace I/O; no answer-quality or actual billing evidence',
                                             'All network calls forbidden; CPU tests run separately; OS caches and host activity uncontrolled',
                                             'Existing .npk compiler and query modules are unchanged']}, indent=2))
    print(summary)


if __name__ == '__main__': main()

"""Paired LOCAL log-check cost; synthetic fixtures are not answer-quality data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import time

from benchmarks.prospective_eval import write_json
from npk.auditor import audit_run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=Path('experiments/runs/packs/cycle15-auditor-profile'))
    args = p.parse_args(); root = args.output; root.mkdir(parents=True, exist_ok=True)
    old = subprocess.run(['git', 'show', '463b38f:npk/auditor.py'], check=True, capture_output=True).stdout
    path = root/'champion-auditor.py'; path.write_bytes(old)
    spec = importlib.util.spec_from_file_location('npk._cycle15_original_auditor', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    functions = {'before': module.audit_run, 'after': audit_run}; rows = []; rng = random.Random(15)
    for n in (20, 1000, 10000):
        folder = root/str(n); folder.mkdir(exist_ok=True)
        write_json(folder/'config.json', {'provider': 'mock', 'model': 'unpriced-synthetic'})
        documents = {name: [] for name in ('inputs', 'baseline_outputs', 'optimized_outputs', 'usage')}
        for i in range(n):
            key = f'task-{i}'; fact = f'answer-{i}'
            documents['inputs'].append({'id': key, 'expected_fact': fact})
            for arm, divisor, tokens in (('baseline', 3, 1000), ('optimized', 4, 300)):
                documents[arm+'_outputs'].append({'id': key, 'content': fact if i % divisor == 0 else 'wrong'})
                documents['usage'].append({'id': key, 'mode': arm, 'prompt_tokens': tokens, 'completion_tokens': 10})
        for name, records in documents.items():
            (folder/(name+'.jsonl')).write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
        for repetition in range(7):
            order = list(functions); rng.shuffle(order)
            for arm in order:
                begin = time.perf_counter(); result = functions[arm](folder)
                elapsed = (time.perf_counter()-begin)*1000
                assert result['tasks_audited'] == n and result['audited_tokens_avoided'] == n*700
                if arm == 'after':
                    assert result['audited_baseline_fixture_pass_pct'] == round(sum(i % 3 == 0 for i in range(n))/n*100, 2)
                    assert result['audited_baseline_cost_usd'] is None
                rows.append({'tasks': n, 'arm': arm, 'repetition': repetition, 'elapsed_ms': elapsed})
                write_json(folder/(arm+'-result.json'), result)
    source_hashes = {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (Path('npk/auditor.py'), Path(__file__).relative_to(Path.cwd()), path)}
    summary = [{'tasks': n, 'arm': arm, 'median_ms': statistics.median(r['elapsed_ms'] for r in rows if r['tasks'] == n and r['arm'] == arm)}
               for n in (20, 1000, 10000) for arm in functions]
    write_json(Path('experiments/results/cycle15-auditor-profile.json'), {
        'evidence_mode': 'LOCAL', 'fixture_mode': 'MOCK', 'rows': rows, 'summary': summary, 'source_sha256': source_hashes,
        'python': platform.python_version(), 'equality_checks': len(rows),
        'limits': ['Synthetic log workloads; no model or network calls', 'Seven shuffled pairs; OS caches uncontrolled',
                   'Historical before-result dollar/accuracy fields are invalid claims retained only to reproduce the defect',
                   'The compiler and selector are unchanged; this measures the audit command only']})
    print(summary)


if __name__ == '__main__': main()

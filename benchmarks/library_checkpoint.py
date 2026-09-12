"""Archive a quiescent behavior checkpoint; never declare the open goal complete."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from npk.pack.source_policy import check_source


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo = Path(__file__).resolve().parents[1]; runs = repo/'experiments/runs/packs'; results = repo/'experiments/results'
    live = runs/'cycle28-library-live-v1'; report = read(results/'cycle28-library-answer-76-stable.json')
    assert report['ledger_sha256'] == sha((live/'ledger.json').read_bytes())
    assert report['plan_sha256'] == sha((live/'plan.json').read_bytes())
    assert report['accounting']['attempts'] == 76 and report['accounting']['live_answers'] == 59
    assert read(live/'failure-pauses.json')['active']
    audit = read(results/'cycle28-library-selection-audit.json'); assert audit['status'] == 'AUDITED'
    mutants = read(results/'cycle28-final-evidence-mutations.json')
    assert len(mutants['rows']) == 88 and all(r['status'] == 'KILLED' for r in mutants['rows'])
    for name, digest in mutants['source_hashes'].items(): assert sha((repo/name).read_bytes()) == digest
    suites = ET.parse(results/'cycle28-final-evidence-full.xml').findall('.//testsuite')
    assert suites and all(int(s.get('failures', 0)) == int(s.get('errors', 0)) == 0 for s in suites)
    test_counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'skipped')}
    assert test_counts['tests'] > test_counts['skipped']
    archive = results/'cycle28-library-checkpoint.zip'
    if archive.exists(): raise ValueError('Do not overwrite an evidence checkpoint')
    chosen = {}
    def add(path):
        if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pending', '.tmp'): return
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(repo)
        chosen[path.relative_to(repo).as_posix()] = path
    for directory in ('npk', 'benchmarks', 'tests'):
        for path in (repo/directory).rglob('*.py'): add(path)
    for name in ('README.md', 'EVOLUTION_LOG.md', 'pyproject.toml', 'research/CYCLE28_SEED_ABLATION.md',
                 'research/CYCLE28_WORKING_RECORD.md', 'research/CYCLE28_BEHAVIOR_ANSWERS.md'):
        add(repo/name)
    for name in ('cycle28-crisp-snapshot-v1', 'cycle28-nim-tokenizer-v1', 'cycle28-library-behavior-v2',
                 'cycle28-library-crisp-v1', 'cycle28-library-minilm-v1', 'cycle28-library-qwen-v1',
                 'cycle28-library-selection-v1', 'cycle28-library-live-v1', 'cycle28-fast-tokenizer-v1'):
        for path in (runs/name).rglob('*'):
            if path.is_file(): add(path)
    add(runs/'cycle28-local-budget-v2/compiled.npk')
    add(runs/'cycle28-seed-metadata-v1/features.sqlite')
    add(results/'cycle14-qwen-download.json')
    for pattern in ('cycle28-library-*.json', 'cycle28-library-*.xml', 'cycle28-pac*.json', 'cycle28-pac*.xml',
                    'cycle28-behavior-full.xml', 'cycle28-ledger-*.xml', 'cycle28-final-evidence-*.json', 'cycle28-final-evidence-*.xml'):
        for path in results.glob(pattern): add(path)
    files = {}; scans = 0; arrays = 0; pending = archive.with_suffix('.zip.pending')
    with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for name, path in sorted(chosen.items()):
            body = path.read_bytes()
            if path.suffix in ('.npk', '.crisp', '.sqlite'):
                con = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
                try:
                    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                    for statement in con.iterdump(): check_source(statement, name); scans += 1
                finally: con.close()
            elif path.suffix == '.npy':
                import numpy as np
                value = np.load(path, allow_pickle=False)
                assert value.dtype == np.float32 and value.ndim == 2 and np.isfinite(value).all()
                arrays += 1
            else:
                plain = gzip.decompress(body) if path.suffix == '.gz' else body
                check_source(plain.decode('utf-8'), name); scans += 1
            stream.writestr(name, body); files[name] = {'sha256': sha(body), 'bytes': len(body)}
        record = {'status': 'OPEN_BEHAVIOR_CHECKPOINT', 'goal_complete': False, 'verdict': 'PIVOT REQUIRED',
                  'created_utc': datetime.now(timezone.utc).isoformat(), 'evidence_mode': 'LIVE+LOCAL',
                  'api_attempts': 76, 'live_answers': 59, 'http503': 16, 'http429': 1,
                  'planned_unique_requests': 416, 'generative_optimization_calls': 0,
                  'matched_budget_selections': 405, 'mutants_killed': 88, 'files': files,
                  'test_counts': test_counts,
                  'limits': ['LIVE run is paused after service overload; missing outcomes do not become passes',
                             'Selected evidence and token accounting passed audit; answer superiority is unproven',
                             '15 inspected questions and one stochastic model configuration, not independent sealed validation',
                             'Local model weights are not bundled; exact revisions and resulting vector arrays are included',
                             'The earlier completed 5589-selection seed matrix has its separate verified archive',
                             'Credential pattern checks are not proof of universal secret absence']}
        raw = json.dumps(record, indent=2).encode(); stream.writestr('CHECKPOINT.json', raw)
    with zipfile.ZipFile(pending) as stream:
        assert len(stream.namelist()) == len(set(stream.namelist())) == len(files)+1
        for name, meta in files.items():
            body = stream.read(name); assert sha(body) == meta['sha256'] and len(body) == meta['bytes']
        assert stream.read('CHECKPOINT.json') == raw and stream.testzip() is None
    assert report['ledger_sha256'] == sha((live/'ledger.json').read_bytes()), 'live run changed during archive'
    pending.replace(archive)
    summary = {k: v for k, v in record.items() if k != 'files'}
    summary.update(archive=archive.name, archive_sha256=sha(archive.read_bytes()), archive_bytes=archive.stat().st_size,
                   archived_files=len(files), checked_numeric_arrays=arrays, decoded_pattern_scans=scans, recognized_pattern_matches=0)
    (results/'cycle28-library-archive.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print({k: v for k, v in summary.items() if k != 'limits'}, flush=True)


if __name__ == '__main__': main()

"""Archive the completed seed experiment and both gates, without rewriting history."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

from npk.pack.source_policy import check_source


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo = Path(__file__).resolve().parents[1]; runs = repo/'experiments/runs/packs'; results = repo/'experiments/results'
    study = runs/'cycle28-seed-metadata-v1'; archive = results/'cycle28-seed-checkpoint.zip'
    if archive.exists(): raise ValueError('Do not overwrite evidence archives')
    state = read(study/'state.json'); plan = read(study/'plan.json')
    audit = read(results/'cycle28-seed-metadata-audit.json'); gate = read(results/'cycle28-seed-rank-gate.json')
    assert state['status'] == 'COMPLETE' and state['completed'] == state['planned'] == 5589
    assert audit['status'] == 'AUDITED' and audit['selections'] == 5589
    assert gate['status'] == 'PASSED'
    assert audit['plan_sha256'] == gate['plan_sha256'] == sha((study/'plan.json').read_bytes())
    assert sha((study/'features.sqlite').read_bytes()) == plan['side_sha256']
    assert sha((runs/'cycle28-local-budget-v2/compiled.npk').read_bytes()) == plan['pack_sha256']
    chosen = {}
    def add(path):
        if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pending'): return
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(repo)
        chosen[path.relative_to(repo).as_posix()] = path
    for root in (study, runs/'cycle28-crisp-snapshot-v1', runs/'cycle28-nim-tokenizer-v1'):
        for path in root.rglob('*'):
            if path.is_file(): add(path)
    add(runs/'cycle28-local-budget-v2/compiled.npk')
    for name in ('cycle28-seed-metadata-audit.json', 'cycle28-seed-rank-gate.json', 'cycle28-library-contracts.xml'):
        add(results/name)
    for path in (repo/'benchmarks').glob('seed_*.py'): add(path)
    for path in (repo/'tests').glob('test_seed_*.py'): add(path)
    add(repo/'research/CYCLE28_SEED_ABLATION.md')
    files = {}; scans = 0; pending = archive.with_suffix('.zip.pending')
    with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for name, path in sorted(chosen.items()):
            body = path.read_bytes()
            if path.suffix in ('.npk', '.sqlite'):
                con = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
                try:
                    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                    for statement in con.iterdump(): check_source(statement, name); scans += 1
                finally: con.close()
            else:
                plain = gzip.decompress(body) if path.suffix == '.gz' else body
                check_source(plain.decode('utf-8'), name); scans += 1
            stream.writestr(name, body); files[name] = {'sha256': sha(body), 'bytes': len(body)}
        manifest = {'status': 'COMPLETED_SEED_STUDY', 'goal_complete': False, 'verdict': 'PIVOT REQUIRED',
                    'created_utc': datetime.now(timezone.utc).isoformat(), 'evidence_mode': 'LOCAL', 'new_api_calls': 0,
                    'plan_sha256': audit['plan_sha256'], 'selections': audit['selections'],
                    'source_items_checked': audit['source_items_checked'], 'files': files,
                    'limits': ['This archive certifies reproducible retrieval diagnostics, not better target answers',
                               'The source questions are inspected development data, not a sealed holdout',
                               'The parent NPK is included; optional metadata indexes have no incremental update support',
                               'Credential pattern checks are not proof of universal secret absence']}
        raw = json.dumps(manifest, indent=2).encode(); stream.writestr('CHECKPOINT.json', raw)
    with zipfile.ZipFile(pending) as stream:
        assert len(stream.namelist()) == len(set(stream.namelist())) == len(files)+1
        for name, meta in files.items():
            body = stream.read(name); assert len(body) == meta['bytes'] and sha(body) == meta['sha256']
        assert stream.read('CHECKPOINT.json') == raw and stream.testzip() is None
    pending.replace(archive)
    summary = {k: v for k, v in manifest.items() if k != 'files'}
    summary.update(archive=archive.name, archive_sha256=sha(archive.read_bytes()), archive_bytes=archive.stat().st_size,
                   archived_files=len(files), decoded_pattern_scans=scans, recognized_pattern_matches=0)
    (results/'cycle28-seed-archive.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print({k: v for k, v in summary.items() if k != 'limits'}, flush=True)


if __name__ == '__main__': main()

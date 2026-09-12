"""Preserve cycle-15 literal inputs, logs and code; screen decoded archive text."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.prospective_eval import write_json
from npk.pack.source_policy import PATTERNS


def sha(body): return hashlib.sha256(body).hexdigest()


def main():
    repo = Path(__file__).resolve().parents[1]; out = repo/'experiments/results'
    local = repo/'experiments/runs/packs/cycle15-hierarchy-v1'
    live = repo/'experiments/runs/cycle15-hierarchy-live-v1'
    files = {}; blobs = {}; scans = 0
    def screen(body):
        nonlocal scans
        text = body.decode('utf-8'); scans += 1
        if any(pattern.search(text) for _, pattern in PATTERNS):
            raise ValueError('Recognized credential pattern in archive input; no matching values printed')
    def add(name, body):
        screen(body); key = sha(body)
        if name in files and files[name] != key: raise ValueError('Archive path collision')
        files[name] = key; blobs[key] = base64.b64encode(body).decode()
    def tree(root, prefix, pattern):
        for path in sorted(root.rglob(pattern)):
            if path.is_file(): add(prefix+'/'+path.relative_to(root).as_posix(), path.read_bytes())
    for name in ('manifest.json', 'results.json'): add('local/'+name, (local/name).read_bytes())
    tree(local/'contexts', 'local/contexts', '*.txt')
    corpus = repo/'experiments/runs/packs/cycle14-corpus-v1'
    for name in ('acquisition.json', 'acquisition.sha256', 'CPYTHON-LICENSE.txt'):
        add('corpus/'+name, (corpus/name).read_bytes())
    tree(corpus/'source', 'corpus/source', '*')
    for model in ('nemotron', 'deepseek'):
        tree(live/model, 'live/'+model, '*.json')
        tree(live/model/'contexts', 'live/'+model+'/contexts', '*.txt')
        tree(live/model/'execution-sources', 'live/'+model+'/execution-sources', '*.py')
        add('live/'+model+'/plan.sha256', (live/model/'plan.sha256').read_bytes())
    add('live/preflight.json', (live/'preflight.json').read_bytes())
    prep = json.loads(gzip.decompress((live/'preparation-sources.json.gz').read_bytes()))
    for path, row in prep.items():
        body = row['text'].encode(); assert sha(body) == row['sha256']; add('preparation/'+path, body)
    for directory in ('npk', 'benchmarks', 'tests'): tree(repo/directory, 'final/'+directory, '*.py')
    profile = repo/'experiments/runs/packs/cycle15-auditor-profile'
    for pattern in ('*.py', '*.json', '*.jsonl'): tree(profile, 'audit-profile', pattern)
    tree(repo/'experiments/runs/packs/cycle15-late-lexical-v1', 'late-lexical', '*.py')
    for path in sorted(out.glob('cycle15-*')):
        if path.suffix in {'.json', '.xml', '.md', '.sha256'} and path.name not in {'cycle15-summary.json', 'cycle15-archive-scan.json'}:
            add('results/'+path.name, path.read_bytes())
    current = {name[len('final/'):]: digest for name, digest in files.items() if name.startswith('final/npk/')}
    mutations = json.loads((out/'cycle15-final-mutations.json').read_text())
    assert current == mutations['source_hashes']
    assert len(mutations['rows']) == 34 and all(r['status'] == 'KILLED' for r in mutations['rows'])
    late = json.loads((out/'cycle15-late-lexical.json').read_text())
    assert all(files['final/'+name] == digest for name, digest in late['code_sha256'].items())
    archive = out/'cycle15-evidence.json.gz'
    archive.write_bytes(gzip.compress(json.dumps({'encoding': 'base64 byte-exact SHA-256 addressed files',
                                                 'files': files, 'blobs': blobs}, separators=(',', ':')).encode(), mtime=0))
    restored = json.loads(gzip.decompress(archive.read_bytes()))
    for key, encoded in restored['blobs'].items():
        body = base64.b64decode(encoded, validate=True); assert sha(body) == key; screen(body)
    assert restored['files'] == files
    report = {'evidence_mode': 'LOCAL', 'archive': archive.name, 'archive_sha256': sha(archive.read_bytes()),
              'archive_bytes': archive.stat().st_size, 'files': len(files), 'unique_blobs': len(blobs),
              'decoded_text_scans': scans, 'recognized_pattern_matches': 0,
              'limits': ['Pattern screening does not recognize all possible secrets',
                        'SQLite sidecars and compiled packs are reproducible, not archived binaries',
                        'Preparation and execution code are separate from final repaired report code',
                        'Synthetic before-audit outputs preserve invalid historical metric claims only as defect evidence']}
    write_json(out/'cycle15-archive-scan.json', report); print(report)


if __name__ == '__main__': main()

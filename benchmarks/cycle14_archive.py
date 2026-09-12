"""Content-addressed, byte-exact archives for cycle-14 LOCAL and LIVE evidence."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import zipfile
from benchmarks.prospective_eval import write_json
from npk.pack.source_policy import PATTERNS


def digest(data): return hashlib.sha256(data).hexdigest()


def main():
    repo = Path(__file__).resolve().parents[1]; out = repo/'experiments/results'
    local = repo/'experiments/runs/packs/cycle14-seeds-v1'
    live = repo/'experiments/runs/cycle14-seed-live-v1'
    corpus = repo/'experiments/runs/packs/cycle14-corpus-v1'
    files = {}; blobs = {}; decoded = 0
    def screen(body):
        nonlocal decoded
        text = body.decode('utf-8'); decoded += 1
        assert not any(pattern.search(text) for _, pattern in PATTERNS), 'recognized credential pattern in archive input'
    def add(name, body):
        screen(body); key = digest(body); files[name] = key; blobs[key] = base64.b64encode(body).decode()
    def tree(root, prefix, pattern):
        for path in sorted(root.rglob(pattern)):
            if path.is_file(): add(prefix+'/'+path.relative_to(root).as_posix(), path.read_bytes())
    for name in ('manifest.json','results.json'): add('local/'+name, (local/name).read_bytes())
    for name in ('acquisition.json','acquisition.sha256','CPYTHON-LICENSE.txt'): add('corpus/'+name,(corpus/name).read_bytes())
    tree(corpus/'source','corpus/source','*')
    tree(local/'contexts','local/contexts','*.txt')
    tree(live,'live','*.json'); tree(live/'contexts','live/contexts','*.txt')
    add('live/plan.sha256', (live/'plan.sha256').read_bytes())
    tree(live/'execution-sources','live/execution-sources','*.py')
    prep = json.loads(gzip.decompress((live/'preparation-sources.json.gz').read_bytes()))
    for path, row in prep.items():
        body = row['text'].encode(); assert digest(body) == row['sha256']; add('preparation/'+path, body)
    for directory in ('npk','benchmarks','tests'): tree(repo/directory,'final/'+directory,'*.py')
    tree(repo/'experiments/runs/packs/cycle14-storage-profile/champion/npk','champion/npk','*.py')
    current = {k[len('final/'):]:v for k,v in files.items() if k.startswith('final/npk/')}
    profile_raw = (out/'cycle14-storage-profile.json').read_bytes(); profile = json.loads(profile_raw)
    mutations = json.loads((out/'cycle14-mutations.json').read_text())
    assert current == profile['candidate_hashes'] == mutations['source_hashes']
    assert len(mutations['rows']) == 29 and all(r['status']=='KILLED' for r in mutations['rows'])
    archive = out/'cycle14-evidence.json.gz'
    body = json.dumps({'encoding':'base64 byte-exact SHA-256 addressed files', 'files':files, 'blobs':blobs},separators=(',',':')).encode()
    archive.write_bytes(gzip.compress(body,mtime=0))
    restored = json.loads(gzip.decompress(archive.read_bytes()))
    for key, value in restored['blobs'].items():
        raw = base64.b64decode(value,validate=True); assert digest(raw)==key; screen(raw)
    assert restored['files']==files
    compressed = out/'cycle14-storage-profile.json.gz'; compressed.write_bytes(gzip.compress(profile_raw,mtime=0))
    assert gzip.decompress(compressed.read_bytes()) == profile_raw; screen(profile_raw)
    # Preserve numeric sidecars directly; no pickle or model/provider state.
    vector_names = ['plain-vectors.npy','headers-vectors.npy','minilm-vectors.npy','qwen-queries.npy','minilm-queries.npy']
    vector_archive = out/'cycle14-vectors.zip'; vectors = {}
    with zipfile.ZipFile(vector_archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in vector_names:
            raw = (local/name).read_bytes(); vectors[name]={'sha256':digest(raw),'bytes':len(raw)}; z.writestr(name,raw)
    import numpy as np
    with zipfile.ZipFile(vector_archive) as z:
        for name in vector_names:
            raw = z.read(name); assert digest(raw)==vectors[name]['sha256']
            with z.open(name) as f:
                matrix = np.load(f,allow_pickle=False)
                assert matrix.dtype.name in ('float32','float64') and np.isfinite(matrix).all()
                vectors[name].update(shape=list(matrix.shape),dtype=str(matrix.dtype))
    write_json(out/'cycle14-archive-scan.json', {'evidence_mode':'LOCAL','files':len(files),'unique_text_blobs':len(blobs),
        'decoded_text_scans':decoded,'recognized_pattern_matches':0,'archive':archive.name,'archive_sha256':digest(archive.read_bytes()),
        'archive_bytes':archive.stat().st_size,'vector_archive':vector_archive.name,'vectors':vectors,
        'vector_archive_sha256':digest(vector_archive.read_bytes()),'vector_archive_bytes':vector_archive.stat().st_size,
        'vector_validation':'ZIP roundtrip + file SHA-256 + allow_pickle=False + finite float32/float64 with actual dtype recorded; numeric arrays are not text secret scans',
        'profile_archive_sha256':digest(compressed.read_bytes()),'profile_raw_sha256':digest(profile_raw),
        'limitations':['Pattern scan is not a guarantee of recognizing every secret',
                       'Initial encoder weights remain external pinned downloads; numeric document/query outputs are archived',
                       'Compiled SQLite artifacts are reproducible inputs, not copies in this archive; literal contexts and source/code are byte-exact']})
    print({'files':len(files),'text_blobs':len(blobs),'decoded_text_scans':decoded,'text_bytes':archive.stat().st_size,
           'vector_archive_bytes':vector_archive.stat().st_size,'recognized_pattern_matches':0})


if __name__=='__main__': main()

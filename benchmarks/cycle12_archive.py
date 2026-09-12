"""Bind cycle-12 measured implementations, immutable requests and raw answers."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    repo=Path(__file__).resolve().parents[1];results=repo/'experiments/results'
    storage_path=results/'cycle12-storage.json'
    storage=json.loads(storage_path.read_text()) if storage_path.exists() else {}
    for name in ('cycle12-boundary-profile.json','cycle12-final-profile.json',
                 'cycle12-live-preflight.xml','cycle12-source-lines-before.xml'):
        path=results/name;compressed=path.with_suffix(path.suffix+'.gz')
        if path.exists():
            raw=path.read_bytes();compressed.write_bytes(gzip.compress(raw,mtime=0))
            assert gzip.decompress(compressed.read_bytes())==raw
            storage[name]={'archive':compressed.name,'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw)}
            assert path.resolve().parent==results.resolve()
            path.unlink()  # Exact file, preserved byte-for-byte in the checked archive.
        else:
            assert hashlib.sha256(gzip.decompress(compressed.read_bytes())).hexdigest()==storage[name]['raw_sha256']
    storage_path.write_text(json.dumps(storage,indent=2),encoding='utf-8')
    run=repo/'experiments/runs/repository-identifier-live-v1'
    plan=json.loads((run/'plan.json').read_text());ledger=json.loads((run/'ledger.json').read_text())
    assert sha(run/'plan.json')==(run/'plan.sha256').read_text().strip()
    assert set(ledger)==set(plan['requests']) and all(row['state']=='DONE' for row in ledger.values())
    live=json.loads((run/'results.json').read_text())
    assert live['plan_sha256']==sha(run/'plan.json') and live['answer_attempts_in_ledger']==len(ledger)
    assert all(row['evidence_mode'] not in {'PENDING','REPLAY_MISS'} for row in live['rows'])
    contexts={}
    for digest in {r['context_sha256'] for r in plan['observations']}:
        context=(run/'contexts'/(digest+'.txt')).read_text(encoding='utf-8')
        assert hashlib.sha256(context.encode()).hexdigest()==digest;contexts[digest]=context
    execution={}
    for p in (run/'execution-sources').glob('*.py'):
        assert p.stem.endswith(sha(p));execution[p.name]=base64.b64encode(p.read_bytes()).decode()
    raw={'results':live,'ledger':ledger,'contexts':contexts,'execution_sources':execution}
    (results/'cycle12-live-raw.json.gz').write_bytes(gzip.compress(json.dumps(raw).encode(),mtime=0))
    # Byte-exact implementations: the original champion, repaired prefilter-free
    # implementation, final implementation, and all current test/harness sources.
    blobs={};snapshots={}
    roots={'champion':repo/'experiments/runs/packs/cycle12-boundary-profile/champion',
           'repaired_before_screen_optimization':repo/'experiments/runs/packs/cycle12-boundary-profile/candidate',
           'final':repo}
    for label,root in roots.items():
        snapshot={}
        directories=('npk','benchmarks','tests') if label=='final' else ('npk',)
        for directory in directories:
            for path in (root/directory).rglob('*.py'):
                body=path.read_bytes();digest=hashlib.sha256(body).hexdigest()
                snapshot[path.relative_to(root).as_posix()]=digest
                blobs[digest]=base64.b64encode(body).decode()
        snapshots[label]=snapshot
    current={name:digest for name,digest in snapshots['final'].items() if name.startswith('npk/')}
    mutations=json.loads((results/'cycle12-mutations-optimized.json').read_text())
    profile=json.loads(gzip.decompress((results/'cycle12-final-profile.json.gz').read_bytes()))
    assert current==mutations['source_hashes']==profile['candidate_hashes']
    assert len(mutations['rows'])==22 and all(r['status']=='KILLED' for r in mutations['rows'])
    suite=ET.parse(results/'cycle12-full-optimized.xml').getroot().find('testsuite')
    assert suite.attrib['tests']=='480' and suite.attrib['failures']==suite.attrib['errors']=='0'
    archive={'encoding':'base64 byte-exact SHA-256 addressed sources','snapshots':snapshots,'blobs':blobs}
    (results/'cycle12-source-snapshots.json.gz').write_bytes(gzip.compress(json.dumps(archive).encode(),mtime=0))
    # A raw text scan cannot see compressed or base64-encoded content.
    from npk.pack.source_policy import PATTERNS
    scanned=[];count=0;matches=[]
    def screen(text,label):
        for name,pattern in PATTERNS:
            if pattern.search(text):matches.append({'artifact':label,'category':name})
    for path in sorted(results.glob('cycle12-*')):
        if path.suffix!='.gz':continue
        data=gzip.decompress(path.read_bytes());screen(data.decode(),path.name)
        scanned.append(path.name)
        if path.name.endswith('.xml.gz'):continue
        decoded=json.loads(data)
        for name,value in decoded.get('base64_sources',{}).items():
            body=base64.b64decode(value)
            assert hashlib.sha256(body).hexdigest()==decoded['source_code_sha256'][name]
            screen(body.decode(),path.name+':'+name);count+=1
        for digest,value in decoded.get('blobs',{}).items():
            body=base64.b64decode(value);assert hashlib.sha256(body).hexdigest()==digest
            screen(body.decode(),path.name+':'+digest);count+=1
        for name,value in decoded.get('execution_sources',{}).items():
            body=base64.b64decode(value);assert name.endswith(hashlib.sha256(body).hexdigest()+'.py')
            screen(body.decode(),path.name+':'+name);count+=1
    if matches:raise AssertionError('recognized credential pattern in decoded cycle evidence')
    scan={'archives':scanned,'decoded_sources':count,'matches':0,'evidence_mode':'LOCAL'}
    (results/'cycle12-archive-scan.json').write_text(json.dumps(scan,indent=2),encoding='utf-8')
    print({'requests':len(ledger),'contexts':len(contexts),'source_blobs':len(blobs),'decoded_archives':len(scanned),'recognized_credential_matches':0})


if __name__=='__main__':main()

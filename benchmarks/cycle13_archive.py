"""Archive exact cycle-13 inputs, answers, measured code and acceptance evidence."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.prospective_eval import request_key,write_json
from npk.pack.source_policy import PATTERNS


def digest(body):return hashlib.sha256(body).hexdigest()


def archive_json(path,data):
    body=json.dumps(data,ensure_ascii=False).encode();path.write_bytes(gzip.compress(body,mtime=0))
    assert gzip.decompress(path.read_bytes())==body


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results'
    run=repo/'experiments/runs/cycle13-diagnostic-v1';models={}
    for model in ('deepseek','nemotron'):
        root=run/model;plan_bytes=(root/'plan.json').read_bytes();sha=digest(plan_bytes)
        assert sha==(root/'plan.sha256').read_text().strip()
        plan=json.loads(plan_bytes);ledger=json.loads((root/'ledger.json').read_text());contexts={}
        # A provider outage may leave unattempted requests. Retain that state;
        # never pretend a partial plan is complete or retry an uncertain request.
        assert all(row['state']=='DONE' for row in ledger.values())
        for row in plan['observations']:
            sha_context=row['context_sha256'];body=(root/'contexts'/(sha_context+'.txt')).read_bytes()
            assert digest(body)==sha_context;contexts[sha_context]=body.decode()
        for key,item in plan['requests'].items():
            assert request_key(plan['settings'],item['question'],contexts[item['context_sha256']])==key
        sources={}
        for path in (root/'execution-sources').glob('*.py'):
            body=path.read_bytes();assert path.stem.endswith(digest(body));sources[path.name]=base64.b64encode(body).decode()
        results=json.loads((root/'results.json').read_text());assert results['plan_sha256']==sha
        assert results['answer_attempts_in_ledger']==len(ledger)
        original_results=json.loads(gzip.decompress((root/'results-before-final-report.json.gz').read_bytes()))
        assert [r['task_success'] for r in original_results['rows']]==[r['task_success'] for r in results['rows']]
        models[model]={'results':results,'original_results':original_results,'ledger':ledger,'contexts':contexts,'execution_sources':sources,
                       'plan_bytes_base64':base64.b64encode(plan_bytes).decode(),
                       'pending_requests':sorted(set(plan['requests'])-set(ledger))}
    preparation=json.loads(gzip.decompress((run/'preparation-sources.json.gz').read_bytes()))
    for path,row in preparation.items():assert digest(row['text'].encode())==row['sha256']
    sources={};manifest=models['deepseek']['results']['plan']['source_manifest']
    for item in manifest:
        body=(run/'source'/item['path']).read_bytes();assert digest(body)==item['sha256']
        sources[item['path']]=base64.b64encode(body).decode()
    archive_json(out/'cycle13-live-raw.json.gz',{'models':models,'preparation_sources':preparation,
                 'source_files_base64':sources,'source_manifest':manifest,'preflight':json.loads((run/'preflight.json').read_text())})
    snapshots={};blobs={}
    for label,root,dirs in [('champion',repo/'experiments/runs/packs/cycle13-storage-profile/champion',('npk',)),
                            ('final',repo,('npk','benchmarks','tests'))]:
        snapshot={}
        for directory in dirs:
            for path in (root/directory).rglob('*.py'):
                body=path.read_bytes();sha=digest(body);snapshot[path.relative_to(root).as_posix()]=sha
                blobs[sha]=base64.b64encode(body).decode()
        snapshots[label]=snapshot
    current={p:s for p,s in snapshots['final'].items() if p.startswith('npk/')}
    profile_path=out/'cycle13-storage-profile.json';compressed=profile_path.with_suffix('.json.gz')
    if profile_path.exists():
        raw=profile_path.read_bytes();compressed.write_bytes(gzip.compress(raw,mtime=0))
        assert gzip.decompress(compressed.read_bytes())==raw
        write_json(out/'cycle13-storage-archive.json',{'raw_sha256':digest(raw),'raw_bytes':len(raw),'archive':compressed.name})
        assert profile_path.resolve().parent==out.resolve();profile_path.unlink()
    profile=json.loads(gzip.decompress(compressed.read_bytes()))
    mutations=json.loads((out/'cycle13-mutations.json').read_text())
    assert current==profile['candidate_hashes']==mutations['source_hashes']
    assert len(mutations['rows'])==26 and all(r['status']=='KILLED' for r in mutations['rows'])
    grader=json.loads((out/'cycle13-grader-mutation.json').read_text());assert grader['rows'][0]['status']=='KILLED'
    archive_json(out/'cycle13-source-snapshots.json.gz',{'snapshots':snapshots,'blobs':blobs,'encoding':'base64 byte-exact SHA-256 addressed sources'})
    scanned=[];decoded=0
    def screen(body):
        nonlocal decoded
        decoded+=1;text=body.decode('utf-8')
        if any(pattern.search(text) for _,pattern in PATTERNS):raise AssertionError('recognized credential pattern in decoded archive')
    def embedded(node):
        if isinstance(node,dict):
            for key,value in node.items():
                if key in ('blobs','source_files_base64','execution_sources'):
                    for body in value.values():screen(base64.b64decode(body))
                elif key=='plan_bytes_base64':screen(base64.b64decode(value))
                else:embedded(value)
        elif isinstance(node,list):
            for value in node:embedded(value)
    for path in sorted(out.glob('cycle13-*.gz')):
        raw=gzip.decompress(path.read_bytes());screen(raw);scanned.append(path.name)
        if path.name.endswith('.json.gz'):embedded(json.loads(raw))
    write_json(out/'cycle13-archive-scan.json',{'evidence_mode':'LOCAL','archives':scanned,'decoded_payloads':decoded,'recognized_pattern_matches':0})
    print({'models':{m:{'attempts':len(d['ledger']),'pending':len(d['pending_requests'])} for m,d in models.items()},
           'source_blobs':len(blobs),'recognized_pattern_matches':0})


if __name__=='__main__':main()

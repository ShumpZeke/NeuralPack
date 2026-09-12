"""Archive completed cycle-18 evidence; the second LIVE run remains separate."""
import base64
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET
from benchmarks.repository_eval import source_coverage
from npk.pack.source_policy import PATTERNS
from benchmarks.source_archive import manifest_sources


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def dump(path, value): path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results'
    local=repo/'experiments/runs/packs/cycle18-clauses-v1'
    source=repo/'experiments/runs/packs/cycle14-seeds-v1/expanded-source'
    live=repo/'experiments/runs/cycle18-clause-live-v1'
    profile=repo/'experiments/runs/packs/cycle18-message-profile-v1'
    data=read(local/'results.json');rows=data['rows'];tasks={t['id']:t for t in data['tasks']}
    raw={}
    for item in data['source_manifest']:
        body=(source/item['path']).read_bytes();assert sha(body)==item['sha256']
        raw[item['path']]=body.decode().replace('\r\n','\n').replace('\r','\n').split('\n')
    for row in rows:
        pieces=[]
        for e in row['evidence']:
            match=re.fullmatch(re.escape(e['path'])+r':(\d+)-(\d+)',e['span']);assert match
            start,end=map(int,match.groups());assert 1<=start<=end<=len(raw[e['path']])
            pieces.append('\n'.join(raw[e['path']][start-1:end]))
        text='\n\n'.join(pieces)
        assert sha(text.encode())==row['context_sha256']
        assert text.encode()==(local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert (max(1,len(text)//4) if text else 0)==row['selected_tokens']<=row['budget']
        # source_coverage accepts objects exposing path/span, as the product does.
        from types import SimpleNamespace
        coverage=source_coverage([SimpleNamespace(**e) for e in row['evidence']],tasks[row['task']]['required'])
        assert all(row[k]==v for k,v in coverage.items())
    identities={(r['task'],r['method'],r['budget']) for r in rows}
    assert len(identities)==len(rows)==540
    assert identities=={(t,m,b) for t in tasks for m in data['methods'] for b in data['budgets']}
    current={f.relative_to(repo).as_posix():sha(f.read_bytes()) for f in (repo/'npk').rglob('*.py')}
    measured=read(out/'cycle18-message-profile.json');mutants=read(out/'cycle18-mutations.json')
    assert current==measured['candidate_source_sha256']==mutants['source_hashes']
    assert all(v==data['code_sha256'][k] for k,v in current.items() if k.startswith('npk/pack/'))
    before=read(out/'cycle18-message-attack-before.json');after=read(out/'cycle18-message-attack-final.json')
    assert after['code_sha256']==current and len(before['rows'])==len(after['rows'])==5
    assert all(not r['unchanged'] and r['invariants_pass'] for r in before['rows'])
    assert all(r['unchanged'] and r['invariants_pass'] for r in after['rows'])
    assert len(mutants['rows'])==51 and all(r['status']=='KILLED' for r in mutants['rows'])
    tests=ET.parse(out/'cycle18-acceptance-final.xml').find('.//testsuite').attrib
    assert tests['errors']==tests['failures']=='0'
    nemo=read(out/'cycle18-nemotron-answers.json')
    assert nemo['reporter_sha256']==sha((repo/'benchmarks/modern_seed_report.py').read_bytes())
    assert len(nemo['task_outcomes'])==252 and not nemo['pending_unique_requests']
    assert nemo['audited_answer_observations']==sum(bool(r['transport_success']) for r in nemo['task_outcomes'])
    assert nemo['local_results_sha256']==sha((local/'results.json').read_bytes())
    files={};blobs={};kinds={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(pattern.search(text) for _,pattern in PATTERNS):
            raise ValueError('Recognized credential pattern in evidence; no value printed')
    def add(name,body,compressed=False):
        screen(gzip.decompress(body) if compressed else body)
        key=sha(body);files[name]=key;blobs[key]=base64.b64encode(body).decode();kinds[key]='gzip' if compressed else 'text'
    for folder in ('npk','benchmarks','tests'):
        for f in sorted((repo/folder).rglob('*.py')):add('final/'+f.relative_to(repo).as_posix(),f.read_bytes())
    for name,body in manifest_sources(source,data['source_manifest'],'public-source').items():add(name,body)
    for folder,prefix in ((local,'local'),(profile,'message-profile'),(live/'nemotron','nemotron')):
        for f in sorted(folder.rglob('*')):
            if f.is_file() and f.suffix in ('.py','.txt','.json','.jsonl','.md','.rst'):
                add(prefix+'/'+f.relative_to(folder).as_posix(),f.read_bytes())
    # Only immutable plans and inputs from the still-running model are archived.
    for f in [live/'preflight.json',live/'preparation-sources.json.gz',live/'deepseek/plan.json',
              live/'deepseek/plan.sha256',*sorted((live/'deepseek/contexts').glob('*.txt'))]:
        add('live-preparation/'+f.relative_to(live).as_posix(),f.read_bytes(),f.suffix=='.gz')
    for f in sorted(out.glob('cycle18-*')):
        if f.suffix in ('.json','.xml','.md','.sha256') and f.name not in ('cycle18-checkpoint.json','cycle18-checkpoint-scan.json'):
            add('results/'+f.name,f.read_bytes())
    archive=out/'cycle18-checkpoint-evidence.json.xz'
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64',
        'files':files,'blobs':blobs,'kinds':kinds},separators=(',',':')).encode()
    started=time.perf_counter();archive.write_bytes(lzma.compress(payload))
    compression_ms=(time.perf_counter()-started)*1000
    restored_payload=lzma.decompress(archive.read_bytes());assert restored_payload==payload
    restored=json.loads(restored_payload);assert restored['files']==files
    for key,value in restored['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==key
        screen(gzip.decompress(body) if restored['kinds'][key]=='gzip' else body)
    scan={'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'archive_file':archive.name,'codec':'standard XZ, Python lzma default preset 6',
          'compression_ms':compression_ms,'uncompressed_container_bytes':len(payload),
          'limitation':'Recognized patterns only; not universal secret detection; compression timing is one run with LIVE IO'}
    dump(out/'cycle18-checkpoint-scan.json',scan)
    summary={'status':'CHECKPOINT_SECOND_MODEL_PENDING','verdict':'PIVOT REQUIRED','champion_before':'2f4543d',
             'candidate_source_sha256':current,'compiled_runtime_changed':False,'tests':tests,'mutants_killed':51,
             'counterexamples_preserved_before':0,'counterexamples_preserved_after':5,
             'source_reconstructed_local_rows':len(rows),'message_profile':measured['summary'],
             'local_seed_summary':data['summary'],'nemotron_report_sha256':sha((out/'cycle18-nemotron-answers.json').read_bytes()),
             'nemotron_attempts':nemo['attempts'],'nemotron_answers':nemo['completed_unique_requests'],
             'archive_scan':scan,'kept':['Message preservation repairs','Strictly unknown risk for unmeasured transforms',
                                      'Permanent adversarial tests and independent evidence reconstruction'],
             'discarded':['Automatic generic deduplication','Automatic message reordering','Obsolete hardcoded savings profiler'],
             'next':'Finish the already frozen DeepSeek run and paired audit; investigate missing API documentation as a separate corpus challenger'}
    dump(out/'cycle18-checkpoint.json',summary)
    print({'tests':tests,'mutants':51,'archive':scan,'status':summary['status']})


if __name__=='__main__':main()

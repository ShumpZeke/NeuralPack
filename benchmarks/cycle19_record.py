"""Audit and archive the completed known-task manual-corpus experiment."""
import base64
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from benchmarks.answer_records import counts, validate_origin, validate_response
from benchmarks.repository_eval import source_coverage
from benchmarks.prospective_eval import write_json
from npk.pack.source_policy import PATTERNS
from benchmarks.source_archive import manifest_sources


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results'
    local=repo/'experiments/runs/packs/cycle19-manual-seeds-v1'
    manuals=repo/'experiments/runs/packs/cycle19-manuals-v1'
    live=repo/'experiments/runs/cycle19-manual-live-v1/nemotron'
    archive=out/'cycle19-evidence.json.xz'
    if archive.exists():raise ValueError('This final evidence archive already exists')
    data=read(local/'results.json');compilation=read(manuals/'compilation.json')
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    mutants=read(out/'cycle19-mutations.json')
    assert current==compilation['candidate_source_sha256']==mutants['source_hashes']
    assert len(mutants['rows'])==54 and all(r['status']=='KILLED' for r in mutants['rows'])
    suite=ET.parse(out/'cycle19-acceptance.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0'
    tasks={t['id']:t for t in data['tasks']};sources={}
    for corpus,meta in data['corpora'].items():
        # The larger corpus contains every original file byte-for-byte.
        sources[corpus]={}
        for item in meta['source_manifest']:
            body=(manuals/'source'/item['path']).read_bytes();assert sha(body)==item['sha256']
            sources[corpus][item['path']]=body.decode().replace('\r\n','\n').replace('\r','\n').split('\n')
    seen=set()
    for row in data['rows']:
        identity=(row['corpus'],row['task'],row['method'],row['budget'])
        assert identity not in seen;seen.add(identity);pieces=[]
        for e in row['evidence']:
            match=re.fullmatch(re.escape(e['path'])+r':(\d+)-(\d+)',e['span']);assert match
            first,last=map(int,match.groups());lines=sources[row['corpus']][e['path']]
            assert 1<=first<=last<=len(lines);pieces.append('\n'.join(lines[first-1:last]))
        text='\n\n'.join(pieces);assert sha(text.encode())==row['context_sha256']
        assert text.encode()==(local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert (max(1,len(text)//4) if text else 0)==row['selected_tokens']<=row['budget']
        coverage=source_coverage([SimpleNamespace(**e) for e in row['evidence']],tasks[row['task']]['required'])
        assert all(row[k]==v for k,v in coverage.items())
    assert seen=={(c,t,m,b) for c in data['corpora'] for t in tasks for m in data['methods'] for b in data['budgets']}
    plan=read(live/'plan.json');ledger=read(live/'ledger.json')
    assert set(plan['requests'])==set(ledger)
    for key,entry in ledger.items():
        assert entry['state']=='DONE' and entry['result']==read(live/'responses'/(key+'.json'))
        validate_origin(live,entry['result']);validate_response(entry['result'])
    accounting=counts(ledger);answers=read(out/'cycle19-nemotron-answers.json')
    assert all(answers[k]==v for k,v in accounting.items())
    assert not answers['pending_unique_requests']
    assert answers['plan_sha256']==sha((live/'plan.json').read_bytes())
    assert answers['reporter_sha256']==sha((repo/'benchmarks/modern_seed_report.py').read_bytes())
    assert answers['local_results_sha256']==sha((local/'results.json').read_bytes())
    dependency=out/'cycle18-checkpoint-evidence.json.xz'
    assert sha(dependency.read_bytes())==read(out/'cycle18-checkpoint-scan.json')['archive_sha256']
    files={};blobs={};kinds={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):
            raise ValueError('Recognized credential pattern in archive; no value printed')
    def add(name,body,compressed=False):
        screen(gzip.decompress(body) if compressed else body)
        key=sha(body);assert name not in files
        files[name]=key;blobs[key]=base64.b64encode(body).decode();kinds[key]='gzip' if compressed else 'text'
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for folder,prefix in ((local,'local'),(manuals,'manuals'),(live,'nemotron')):
        for p in sorted(folder.rglob('*')):
            if folder==manuals and p.is_relative_to(manuals/'source'):continue
            if p.is_file() and p.suffix in ('.py','.txt','.rst','.md','.json','.jsonl','.sha256','.gz'):
                add(prefix+'/'+p.relative_to(folder).as_posix(),p.read_bytes(),p.suffix=='.gz')
    for name,body in manifest_sources(manuals/'source',read(manuals/'acquisition.json')['source_manifest'],'manuals/source').items():add(name,body)
    for p in sorted(out.glob('cycle19-*')):
        if p.suffix in ('.json','.md','.xml') and p.name not in ('cycle19-record.json','cycle19-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,'kinds':kinds,
                        'dependencies':{dependency.name:sha(dependency.read_bytes())}},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));restored=lzma.decompress(archive.read_bytes());assert restored==payload
    for key,value in json.loads(restored)['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==key
        screen(gzip.decompress(body) if kinds[key]=='gzip' else body)
    scan={'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','archive_file':archive.name,
          'limitations':['Recognized credential patterns only; not universal secret detection',
                         'No archive timing benchmark; compilation timings are separately recorded']}
    write_json(out/'cycle19-archive-scan.json',scan)
    timing={method:statistics.median(r['wall_ms'] for r in compilation['timings'] if r['method']==method)
            for method in ('full','incremental')}
    record={'status':'COMPLETE_MANUAL_CORPUS_EXPERIMENT','verdict':'PIVOT REQUIRED',
            'compiled_runtime_changed':False,'candidate_source_sha256':current,
            'tests':suite,'mutants_killed':54,'source_reconstructed_local_rows':len(seen),
            'corpus_available_tokens':{c:m['available_tokens'] for c,m in data['corpora'].items()},
            'compilation_median_ms':timing,'compilation_equivalence':{
                k:compilation[k] for k in ('compiled_representation_checks','paired_query_checks')},
            'answer_accounting':accounting,'corpus_pairs':answers['corpus_pairs'],
            'nemotron_report_sha256':sha((out/'cycle19-nemotron-answers.json').read_bytes()),'archive_scan':scan,
            'kept':['Explicit origin-bound replays and raw response usage checks',
                    'Matched-corpus pair reporting, exact-version corpus and raw evidence'],
            'not_promoted':['Whole-manual corpus addition as a general answer-quality improvement',
                            'Weighted fields as a replacement for default BM25'],
            'next':'Separate target reasoning/formatting limitations from retrieval with privileged-source and target-configuration controls',
            'limitations':data['limitations']+['Cycle 18 DeepSeek remains a separate pending experiment',
                'Known task ablation, not independent validation; missing answers are explicit',
                'No end-to-end dollar-savings, full-context or remote-preprocessor comparison']}
    write_json(out/'cycle19-record.json',record)
    print({'status':record['status'],'tests':suite,'mutants':54,'timing':timing,'archive':scan})


if __name__=='__main__':main()

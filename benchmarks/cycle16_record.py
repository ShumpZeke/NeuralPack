"""Archive and bind cycle-16 post-fix evidence without new model calls."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json
from npk.pack.source_policy import PATTERNS


def sha(body): return hashlib.sha256(body).hexdigest()


def main():
    repo=Path(__file__).resolve().parents[1]; out=repo/'experiments/results'
    read=lambda name: json.loads((out/name).read_text())
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    profile=read('cycle16-policy-final.json'); mutants=read('cycle16-final-mutations.json')
    assert current == profile['candidate_source_sha256'] == mutants['source_hashes']
    assert len(mutants['rows']) == 40 and all(r['status']=='KILLED' for r in mutants['rows'])
    previous=read('cycle15-summary.json')['candidate_source_sha256']
    assert all(v==previous[k] for k,v in current.items() if k.startswith('npk/pack/'))
    tests=ET.parse(out/'cycle16-acceptance.xml').find('.//testsuite').attrib
    secrets=ET.parse(out/'cycle16-secret-acceptance.xml').find('.//testsuite').attrib
    assert tests['failures']==tests['errors']==secrets['failures']==secrets['errors']=='0'
    reports={model:read(f'cycle16-{model}-economics.json') for model in ('nemotron','deepseek')}
    assert all(r['new_api_calls']==0 and r['evidence_mode']=='REPLAY' and r['net_savings_usd'] is None
               and r['reporter_sha256']==sha((repo/'benchmarks/economics.py').read_bytes()) for r in reports.values())
    files={}; blobs={}; scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8'); scans+=1
        if any(pattern.search(text) for _,pattern in PATTERNS):
            raise ValueError('Credential pattern in archive input; no value printed')
    def add(name,body):
        screen(body); key=sha(body); files[name]=key; blobs[key]=base64.b64encode(body).decode()
    def tree(root,prefix,pattern):
        for p in sorted(root.rglob(pattern)):
            if p.is_file(): add(prefix+'/'+p.relative_to(root).as_posix(),p.read_bytes())
    for folder in ('npk','benchmarks','tests'):tree(repo/folder,'final/'+folder,'*.py')
    for version in ('v1','final'):
        root=repo/f'experiments/runs/packs/cycle16-policy-{version}'
        for pattern in ('*.py','*.txt','*.json','*.jsonl'):tree(root,'policy-'+version,pattern)
    for p in sorted(out.glob('cycle16-*')):
        if p.suffix in ('.json','.xml') and p.name not in ('cycle16-summary.json','cycle16-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    dependency='cycle15-evidence.json.gz'; dependency_sha=sha((out/dependency).read_bytes())
    archive=out/'cycle16-evidence.json.gz'
    archive.write_bytes(gzip.compress(json.dumps({'encoding':'base64 byte-exact SHA-256 addressed files',
        'dependencies':{dependency:dependency_sha},'files':files,'blobs':blobs},separators=(',',':')).encode(),mtime=0))
    restored=json.loads(gzip.decompress(archive.read_bytes()))
    for key,value in restored['blobs'].items():
        body=base64.b64decode(value,validate=True); assert sha(body)==key; screen(body)
    assert restored['files']==files
    scan={'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'dependencies':{dependency:dependency_sha},'limit':'Pattern screening is not universal secret detection'}
    write_json(out/'cycle16-archive-scan.json',scan)
    summary={'verdict':'PIVOT REQUIRED','champion_before':'5429fa7','candidate_source_sha256':current,
             'compiled_runtime_changed':False,'new_answer_model_calls':0,'tests':tests,'post_stage_secret_scan':secrets,
             'product_mutants_killed':37,'grader_report_mutants_killed':2,'scanner_mutants_killed':1,
             'initial_pricing_contract_failures':17,'passthrough_calibration_failure':1,
             'profile_calls_preserving_query_system_and_nonempty_context':len(profile['rows']),
             'profile_summary':profile['summary'], 'memory_probe':read('cycle16-memory-probe.json'),
             'replayed_attempts':sum(r['live_attempts_in_ledger'] for r in reports.values()),
             'replayed_answers':sum(r['unique_responses'] for r in reports.values()),
             'archive_scan':scan,
             'kept':['Explicit provider-scoped text quotes and absent unknown costs','Honest planner/client/trace metadata',
                     'Risk threshold inversion repair','Reconstructed raw-evidence economics','Permanent regression and mutation checks'],
             'discarded':['Arbitrary pricing and mock aliases','Invented output, latency and cache-hit forecasts',
                          'Old headline quality overlays','Six obsolete report runners and unsafe summary helpers'],
             'next_hypothesis':'CONJECTURE: make optional client neural encoders explicit after measuring evidence parity; then test deterministic query decomposition',
             'limits':['No retrieval-superiority or economic break-even claim','No new independent held-out answer evaluation',
                       'Risk remains uncalibrated; target-specific token budgets remain advisory',
                       'Memory probe compares different APIs/configurations, not equivalent answer quality',
                       'Quotes are scoped assumptions, not actual billing; optional provider adapters are not required for .npk queries']}
    summary['artifacts']={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(out.glob('cycle16-*'))
                          if p.is_file() and p.name!='cycle16-summary.json'}
    write_json(out/'cycle16-summary.json',summary)
    print({'verdict':summary['verdict'],'tests':tests['tests'],'skips':tests['skipped'],'mutants':40,
           'new_model_calls':0,'archive_files':len(files),'archive_bytes':archive.stat().st_size,'matches':0})


if __name__=='__main__':main()

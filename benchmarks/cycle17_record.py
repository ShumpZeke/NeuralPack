"""Bind final repair checks and separately frozen LOCAL seed/profile evidence."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from benchmarks.legacy_seed_audit import audit
from npk.pack.source_policy import PATTERNS


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def dump(path, data): path.write_text(json.dumps(data,indent=2),encoding='utf-8')


def main():
    repo = Path(__file__).resolve().parents[1]; out = repo/'experiments/results'
    seeds = repo/'experiments/runs/packs/cycle17-legacy-seeds-v1'
    profile_root = repo/'experiments/runs/packs/cycle17-client-profile-v1'
    selected = read(seeds/'results.json'); inputs = read(seeds/'inputs.json')
    assert selected['inputs_sha256'] == sha((seeds/'inputs.json').read_bytes())
    assert selected['dense_sha256'] == sha((seeds/'dense.json').read_bytes())
    reconstructed = audit(inputs, selected['rows'])
    profile = read(out/'cycle17-client-profile.json'); mutations = read(out/'cycle17-mutations.json')
    dispatch = read(out/'cycle17-dispatch-reconstruction.json')
    assert dispatch['new_api_calls'] == 0 and sum(r['captured_dispatches_matched'] for r in dispatch['rows']) == 96
    assert dispatch['profile_sha256'] == sha((out/'cycle17-client-profile.json').read_bytes())
    current = {p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert current == profile['candidate_source_sha256'] == mutations['source_hashes']
    frozen = {p.relative_to(seeds/'candidate').as_posix():sha(p.read_bytes()) for p in (seeds/'candidate/npk').rglob('*.py')}
    assert frozen == selected['candidate_source_sha256']
    changed = sorted(p for p in current if current[p] != frozen[p])
    assert set(changed) <= {'npk/context/safety.py','npk/planner.py','npk/runtime.py','npk/telemetry.py'}
    # The measured selection algorithm and encoder implementation must match the
    # final source, even though message guards and labels were repaired afterward.
    for p in ('npk/context/info_gain.py','npk/context/bm25.py','npk/context/analyzer.py',
              'npk/context/retrieval.py','npk/context/embedding.py'):
        assert frozen[p] == current[p]
    previous = read(out/'cycle16-summary.json')['candidate_source_sha256']
    assert all(v==previous[k] for k,v in current.items() if k.startswith('npk/pack/'))
    tests = ET.parse(out/'cycle17-acceptance.xml').find('.//testsuite').attrib
    secrets = ET.parse(out/'cycle17-secret-acceptance.xml').find('.//testsuite').attrib
    assert tests['errors']==tests['failures']==secrets['errors']==secrets['failures']=='0'
    assert len(mutations['rows']) == 47 and all(r['status']=='KILLED' for r in mutations['rows'])
    files={}; blobs={}; scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(pattern.search(text) for _,pattern in PATTERNS):
            raise ValueError('Credential pattern in archive input; no value printed')
    def add(name,body):
        screen(body);key=sha(body);files[name]=key;blobs[key]=base64.b64encode(body).decode()
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for root,prefix in ((seeds,'seeds'),(profile_root,'profile')):
        for p in sorted(root.rglob('*')):
            if p.is_file() and p.suffix in ('.py','.txt','.json','.jsonl'):
                add(prefix+'/'+p.relative_to(root).as_posix(),p.read_bytes())
    for p in sorted(out.glob('cycle17-*')):
        if p.suffix in ('.json','.xml') and p.name not in ('cycle17-summary.json','cycle17-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    dep='cycle16-evidence.json.gz';dependencies={dep:sha((out/dep).read_bytes())}
    archive=out/'cycle17-evidence.json.gz'
    archive.write_bytes(gzip.compress(json.dumps({'encoding':'SHA-256 addressed byte-exact base64',
        'files':files,'blobs':blobs,'dependencies':dependencies},separators=(',',':')).encode(),mtime=0))
    restored=json.loads(gzip.decompress(archive.read_bytes()))
    assert restored['files']==files
    for key,value in restored['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==key;screen(body)
    scan={'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,
          'recognized_pattern_matches':0,'dependencies':dependencies,'limit':'Not universal secret detection'}
    dump(out/'cycle17-archive-scan.json',scan)
    summary={'verdict':'PIVOT REQUIRED','champion_before':'5a22535','candidate_source_sha256':current,
             'seed_snapshot_sha256':frozen,'files_changed_after_seed_snapshot':changed,
             'selection_algorithm_matches_final_source':True,'compiled_runtime_changed':False,
             'new_answer_model_calls':0,'tests':tests,'secret_scan':secrets,
             'mutants_killed':len(mutations['rows']),'local_rows_reconstructed':reconstructed,
             'profile_dispatches_reconstructed':96,
             'seed_summary':selected['summary'],'profile_summary':profile['summary'],'archive_scan':scan,
             'limits':['Real LOCAL encoder, MOCK client target, no new answer accuracy or billed economics',
                       'Known source-span labels diagnose evidence; they do not prove sufficiency',
                       'Seed experiment froze before final message-boundary and metadata repairs; exact versions archived',
                       'Shared model cache explicitly supplied to both profile snapshots; earlier informal probes were not that control'],
             'kept':['Default client no longer probes optional neural libraries','Explicit local encoder opt-in',
                     'Legacy selector enforces joined-text budget and declares full fallback',
                     'Full current query preservation and query-excluded source check','Correct estimator labels',
                     'Source-reconstructed evidence and new mutation checks'],
             'next_hypothesis':'Deterministic clause retrieval plus original-query fusion against competent compiled BM25/weighted BM25, followed by new answer tests only if LOCAL evidence improves'}
    dump(out/'cycle17-summary.json',summary)
    print({'verdict':summary['verdict'],'archive':scan,'tests':tests,'mutants':len(mutations['rows']),
           'reconstructed_rows':reconstructed,'seed_to_final_changes':changed})


if __name__=='__main__':main()

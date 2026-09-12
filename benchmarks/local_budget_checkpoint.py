"""Archive an explicitly incomplete research checkpoint and its exact inputs."""
from datetime import datetime,timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import xml.etree.ElementTree as ET

from npk.pack.source_policy import check_source


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];runs=repo/'experiments/runs/packs';results=repo/'experiments/results'
    archive=results/'cycle28-local-budget-checkpoint.tar.xz'
    if archive.exists():raise ValueError('Fresh checkpoint archive required')
    suite=ET.parse(results/'cycle28-budget-acceptance-sandbox.xml').find('.//testsuite').attrib
    assert int(suite['tests'])==853 and int(suite['skipped'])==22 and int(suite['failures'])==int(suite['errors'])==0
    first=read(results/'cycle28-exact-budget-mutations.json');extra=read(results/'cycle28-additive-mutation.json')
    assert first['source_hashes']==extra['source_hashes']
    mutants=first['rows']+extra['rows']
    assert len(mutants)==len({r['mutant'] for r in mutants})==84 and all(r['status']=='KILLED' for r in mutants)
    for path,expected in first['source_hashes'].items():assert sha((repo/path).read_bytes())==expected
    audited=read(results/'cycle28-local-budget-audit.json')
    assert audited['status']=='AUDITED' and audited['selections']==2484 and audited['source_items_checked']==44158
    gate_root=runs/'cycle28-local-budget-product-v1';gate=read(gate_root/'report.json')
    assert gate['status']=='PASSED' and gate['unchanged_default_selections']==621 and gate['matched_exact_selections']==216
    captured=(gate_root/'sources.json.gz').read_bytes();assert sha(captured)==gate['sources_sha256']
    for path,text in json.loads(gzip.decompress(captured)).items():
        if path.startswith('npk/'):assert (repo/path).read_bytes().decode()==text
    selected={}
    def add(path):
        if path.is_symlink() or not path.resolve().is_relative_to(repo):raise ValueError('Archive path escapes workspace')
        if '__pycache__' in path.parts or path.suffix in ('.pyc','.pending'):return
        selected[path.relative_to(repo).as_posix()]=path
    for folder in ('npk','benchmarks','tests'):
        for path in (repo/folder).rglob('*.py'):add(path)
    for name in ('README.md','EVOLUTION_LOG.md','pyproject.toml','research/CYCLE28_WORKING_RECORD.md',
                 'research/CYCLE28_LOCAL_BUDGETS.md','research/CYCLE28_CRISP_REPRODUCTION.md'):
        add(repo/name)
    for name in ('cycle28-crisp-snapshot-v1','cycle28-nim-tokenizer-v1','cycle28-local-budget-v2','cycle28-local-budget-product-v1'):
        for path in (runs/name).rglob('*'):
            if path.is_file():add(path)
    for pattern in ('cycle28-*budget*.xml','cycle28-*budget*.json','cycle28-additive-*.xml','cycle28-additive-*.json'):
        for path in results.glob(pattern):add(path)
    files={};scans=0;total=0
    pending=archive.with_suffix('.xz.pending')
    with tarfile.open(pending,'w|xz') as stream:
        for i,(name,path) in enumerate(sorted(selected.items()),1):
            body=path.read_bytes()
            if path.suffix=='.npk':
                con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
                try:
                    for statement in con.iterdump():check_source(statement,name);scans+=1
                finally:con.close()
            else:
                decoded=gzip.decompress(body) if path.suffix=='.gz' else body
                check_source(decoded.decode('utf-8'),name);scans+=1
            files[name]={'bytes':len(body),'sha256':sha(body)};total+=len(body)
            info=tarfile.TarInfo(name);info.size=len(body);info.mode=0o644;info.mtime=0
            stream.addfile(info,io.BytesIO(body))
            if i%500==0:print({'archived':i,'bytes':total},flush=True)
        record={'status':'CHECKPOINT','cycle_complete':False,'goal_complete':False,'verdict':'PIVOT REQUIRED',
                'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','new_api_calls':0,
                'tests_passed':831,'tests_skipped':22,'canonical_python_checks_pending':20,
                'mutants_killed':84,'mutation_batches':[{'name':p.name,'sha256':sha(p.read_bytes())} for p in
                    (results/'cycle28-exact-budget-mutations.json',results/'cycle28-additive-mutation.json')],
                'audited_selections':2484,'source_items_checked':44158,'profile_observations':864,
                'gate':{k:v for k,v in gate.items() if k!='profile'},'files':files,
                'limitations':['Recognized credential patterns only; this does not assert universal secret detection',
                               'Source retention is not answer accuracy; canonical full-version verification remains pending',
                               'Automatic approval review timed out twice before launching the canonical full test command',
                               'Strong seed and SQLAlchemy target-answer research remain open'],
                'next':'Repair code-aware seed retrieval and validate executable answers against the strong frozen baseline'}
        manifest=json.dumps(record,indent=2).encode();info=tarfile.TarInfo('CHECKPOINT.json');info.size=len(manifest);info.mtime=0
        stream.addfile(info,io.BytesIO(manifest))
    seen=set()
    with tarfile.open(pending,'r|xz') as stream:
        for member in stream:
            assert member.isfile() and member.name not in seen;seen.add(member.name)
            body=stream.extractfile(member).read()
            if member.name=='CHECKPOINT.json':assert body==manifest
            else:assert files[member.name]=={'bytes':len(body),'sha256':sha(body)}
    assert seen==set(files)|{'CHECKPOINT.json'}
    pending.replace(archive)
    summary={k:v for k,v in record.items() if k!='files'}
    summary.update(archive=archive.name,archive_sha256=sha(archive.read_bytes()),archive_bytes=archive.stat().st_size,
                   archived_files=len(files),uncompressed_bytes=total,decoded_pattern_scans=scans,recognized_pattern_matches=0)
    (results/'cycle28-local-budget-checkpoint.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print({k:v for k,v in summary.items() if k not in ('gate','limitations')},flush=True)


if __name__=='__main__':main()

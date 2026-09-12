"""Seal a LOCAL research checkpoint without claiming that cycle 28 is finished."""
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import xml.etree.ElementTree as ET

from npk.pack.source_policy import check_source


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1]; runs=repo/'experiments/runs/packs'; results=repo/'experiments/results'
    archive=results/'cycle28-rival-checkpoint.tar.xz'
    if archive.exists(): raise ValueError('Checkpoint archive already exists')
    suite=ET.parse(results/'cycle28-checkpoint-acceptance.xml').find('.//testsuite').attrib
    assert int(suite['tests'])==828 and int(suite['skipped'])==2 and int(suite['failures'])==int(suite['errors'])==0
    mutations=read(results/'cycle28-mutations.json')['rows']
    assert len(mutations)==76 and all(row['status']=='KILLED' for row in mutations)
    audit=read(results/'cycle28-rival-comparison.json')
    assert audit['status']=='AUDITED' and audit['audited_rows']==8610 and audit['source_items_checked']==86871
    usage=read(results/'cycle28-target-tokenizer.json')
    assert usage['records']==usage['matching_usage_records']==74 and usage['new_api_calls']==0
    old,new=[runs/name for name in ('cycle28-api-live-v1','cycle28-api-live-v2')]
    first,second=read(old/'plan.json'),read(new/'plan.json')
    assert all(first[k]==second[k] for k in ('requests','observations','settings','dataset'))
    for root in (old,new):
        ledger=read(root/'ledger.json')
        assert len(ledger)==97 and all(e['state']=='DONE' and e['result']['evidence_mode']=='REPLAY'
                                     and e['result']['api_attempts_this_run']==0 for e in ledger.values())
    supersession={'status':'SUPERSEDED_BEFORE_LIVE','old_plan_sha256':sha((old/'plan.json').read_bytes()),
                  'replacement_plan_sha256':sha((new/'plan.json').read_bytes()),'identical_request_identities':249,
                  'identical_observations':270,'new_api_calls_in_either_plan':0,
                  'reason':'Version 2 shuffles the same request identities before any new target call'}
    (old/'superseded-before-live.json').write_text(json.dumps(supersession,indent=2),encoding='utf-8')
    selected={}
    def add(path):
        if path.is_symlink() or not path.resolve().is_relative_to(repo): raise ValueError('Checkpoint path escapes workspace')
        if '__pycache__' in path.parts or path.suffix in ('.pyc','.pending','.tmp'): return
        selected[path.relative_to(repo).as_posix()]=path
    for directory in ('npk','benchmarks','tests'):
        for path in (repo/directory).rglob('*.py'): add(path)
    for path in results.glob('cycle28-*'):
        if path.suffix in ('.json','.xml'): add(path)
    for name in ('pyproject.toml','research/CYCLE28_WORKING_RECORD.md','research/CYCLE28_CRISP_REPRODUCTION.md'):
        add(repo/name)
    roots=('cycle28-crisp-snapshot-v1','cycle28-crisp-reproduction-v5','cycle28-nim-tokenizer-v1',
           'cycle28-api-live-v1','cycle28-api-live-v2')
    for name in roots:
        for path in (runs/name).rglob('*'):
            if path.is_file(): add(path)
    # Preserve interrupted observations/source snapshots but avoid duplicating
    # their derived SQLite artifacts. The complete run's artifacts are retained.
    for name in ('cycle28-crisp-reproduction-v1','cycle28-crisp-reproduction-v2',
                 'cycle28-crisp-reproduction-v3','cycle28-crisp-reproduction-v4'):
        for path in (runs/name).rglob('*'):
            if path.is_file() and path.suffix not in ('.npk','.crisp'): add(path)
    files={}; scans=0; total=0
    temporary=archive.with_suffix(archive.suffix+'.pending')
    # Python 3.12 streaming tar uses LZMA's default preset (6).
    with tarfile.open(temporary,'w|xz') as stream:
        for index,(name,path) in enumerate(sorted(selected.items()),1):
            body=path.read_bytes()
            if path.suffix in ('.npk','.crisp'):
                con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
                try:
                    for statement in con.iterdump(): check_source(statement,name); scans+=1
                finally: con.close()
            else:
                decoded=gzip.decompress(body) if path.suffix=='.gz' else body
                check_source(decoded.decode('utf-8'),name); scans+=1
            files[name]={'sha256':sha(body),'bytes':len(body)};total+=len(body)
            info=tarfile.TarInfo(name);info.size=len(body);info.mtime=0;info.mode=0o644
            stream.addfile(info,io.BytesIO(body))
            if index%1000==0:print({'archived_files':index,'bytes':total},flush=True)
        record={'status':'CHECKPOINT','cycle_complete':False,'goal_complete':False,'verdict':'PIVOT REQUIRED',
                'created_utc':datetime.now(timezone.utc).isoformat(),'tests_passed':826,'tests_skipped':2,'mutants_killed':76,
                'audited_rival_selections':8610,'source_items_checked':86871,'tokenizer_usage_matches':74,
                'new_api_calls':0,'unattempted_prepared_api_requests':152,'supersession':supersession,
                'production_selector_changed':False,'files':files,
                'limitations':['Recognized credential patterns only, not universal secret detection',
                               'Source retention on inspected tasks is not answer accuracy',
                               'SQLAlchemy acquisition/retrieval data remain in the working cycle and require the final cycle archive'],
                'next':'Repair exact local budgeting; build code-aware seed challengers against the audited CRISP structural baseline; validate behavior answers'}
        manifest=json.dumps(record,indent=2).encode();info=tarfile.TarInfo('CHECKPOINT.json');info.size=len(manifest);info.mtime=0
        stream.addfile(info,io.BytesIO(manifest))
    seen=set()
    with tarfile.open(temporary,'r|xz') as stream:
        for member in stream:
            assert member.isfile() and member.name not in seen;seen.add(member.name)
            body=stream.extractfile(member).read()
            if member.name=='CHECKPOINT.json': assert body==manifest
            else: assert files[member.name]=={'sha256':sha(body),'bytes':len(body)}
    assert seen==set(files)|{'CHECKPOINT.json'}
    temporary.replace(archive)
    summary={k:v for k,v in record.items() if k!='files'}
    summary.update({'archive':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
                    'archived_files':len(files),'uncompressed_bytes':total,'decoded_pattern_scans':scans,
                    'recognized_pattern_matches':0})
    (results/'cycle28-checkpoint.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(summary,flush=True)


if __name__=='__main__':main()

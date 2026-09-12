"""Archive the checked literal-reference repair, not the unfinished seed study."""
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from npk.pack.source_policy import check_source


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];runs=repo/'experiments/runs/packs';results=repo/'experiments/results'
    archive=results/'cycle28-literal-repair-checkpoint.zip'
    if archive.exists():raise ValueError('Do not overwrite a repair checkpoint')
    mutants=read(results/'cycle28-literal-mutations.json')
    assert len(mutants['rows'])==85 and all(r['status']=='KILLED' for r in mutants['rows'])
    assert len({r['mutant'] for r in mutants['rows']})==len(mutants['rows'])
    for name,digest in mutants['source_hashes'].items():assert sha((repo/name).read_bytes())==digest
    suite=ET.parse(results/'cycle28-literal-full.xml').find('.//testsuite').attrib
    additional=ET.parse(results/'cycle28-source-coverage-contracts.xml').find('.//testsuite').attrib
    for result in (suite,additional):assert int(result['failures'])==int(result['errors'])==0
    gate=read(runs/'cycle28-literal-product-v1/report.json')
    assert gate['status']=='PASSED' and gate['ranking_checks']==920 and gate['matched_selections']==21
    oracle_root=runs/'cycle28-library-behavior-v2';one=read(oracle_root/'oracles-1.json');two=read(oracle_root/'oracles-2.json')
    assert one['rows']==two['rows'] and two['expected_outputs_match_previous'] and two['trace_lines_match_previous']
    chosen={}
    def add(path):
        if '__pycache__' in path.parts or path.suffix in ('.pyc','.pending'):return
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(repo)
        chosen[path.relative_to(repo).as_posix()]=path
    for folder in ('npk','benchmarks','tests'):
        for path in (repo/folder).rglob('*.py'):add(path)
    for name in ('README.md','EVOLUTION_LOG.md','pyproject.toml','INDEPENDENT_AUDIT.md',
                 'research/math/INDEPENDENT_MATH_AUDIT.md','research/CYCLE28_WORKING_RECORD.md',
                 'research/CYCLE28_LOCAL_BUDGETS.md','research/CYCLE28_CRISP_REPRODUCTION.md','research/CYCLE28_SEED_ABLATION.md'):
        add(repo/name)
    for folder in ('cycle28-crisp-snapshot-v1','cycle28-nim-tokenizer-v1','cycle28-literal-product-v1',
                   'cycle28-library-behavior-v1','cycle28-library-behavior-v2'):
        for path in (runs/folder).rglob('*'):
            if path.is_file():add(path)
    add(runs/'cycle28-local-budget-v2/compiled.npk')
    # Only immutable seed-study inputs are included. Its growing raw records
    # are a separate unfinished experiment and provide no repair-quality claim.
    for name in ('plan.json','sources.json.gz','execution-copy.json'):
        add(runs/'cycle28-seed-metadata-v1'/name)
    for path in (runs/'cycle28-seed-metadata-v1/execution-root').rglob('*.py'):add(path)
    for pattern in ('cycle28-literal-*.xml','cycle28-literal-mutations.json','cycle28-seed-*.xml','cycle28-source-coverage-contracts.xml'):
        for path in results.glob(pattern):add(path)
    files={};scans=0;pending=archive.with_suffix('.zip.pending')
    with zipfile.ZipFile(pending,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
        for name,path in sorted(chosen.items()):
            body=path.read_bytes()
            if path.suffix=='.npk':
                con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
                try:
                    for statement in con.iterdump():check_source(statement,name);scans+=1
                finally:con.close()
            else:
                plain=gzip.decompress(body) if path.suffix=='.gz' else body
                check_source(plain.decode('utf-8'),name);scans+=1
            stream.writestr(name,body);files[name]={'sha256':sha(body),'bytes':len(body)}
        record={'status':'REPAIR_CHECKPOINT','goal_complete':False,'cycle_complete':False,
            'created_utc':datetime.now(timezone.utc).isoformat(),'verdict':'PIVOT REQUIRED','evidence_mode':'LOCAL','new_api_calls':0,
            'full_suite_passed':int(suite['tests'])-int(suite['skipped']),'full_suite_skipped':int(suite['skipped']),
            'canonical_python_oracles_pending':20,
            'additional_auditor_tests_passed':int(additional['tests'])-int(additional['skipped']),
            'mutants_killed':len(mutants['rows']),'ranking_checks':gate['ranking_checks'],
            'matched_selections':gate['matched_selections'],
            'oracle_tasks':len(two['rows']),'fresh_oracle_runs':2,'files':files,
            'limits':['Only the explicit-reference repair is checked here; stronger retrieval and actual target answers remain open',
                      'The nine-arm seed study has only its immutable plan/code inputs here, not its growing raw results or auxiliary index',
                      'The extra auditor run contains one new coverage guard after the full suite; other tests overlap',
                      'Recognized credential pattern checks do not prove universal absence of secrets']}
        manifest=json.dumps(record,indent=2).encode();stream.writestr('CHECKPOINT.json',manifest)
    with zipfile.ZipFile(pending) as stream:
        assert len(stream.namelist())==len(set(stream.namelist()))==len(files)+1
        for name,info in files.items():
            body=stream.read(name);assert sha(body)==info['sha256'] and len(body)==info['bytes']
        assert stream.read('CHECKPOINT.json')==manifest and stream.testzip() is None
    pending.replace(archive)
    summary={k:v for k,v in record.items() if k!='files'}
    summary.update(archive=archive.name,archive_sha256=sha(archive.read_bytes()),archive_bytes=archive.stat().st_size,
                   archived_files=len(files),decoded_pattern_scans=scans,recognized_pattern_matches=0)
    (results/'cycle28-literal-repair-archive.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print({k:v for k,v in summary.items() if k not in ('limits',)},flush=True)


if __name__=='__main__':main()

"""Materialize the exact captured seed-experiment code for resumable isolation.

The original run is immutable. Its next batch may import this private execution
copy so later product fixes cannot change either baseline halfway through.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path,PurePosixPath
import subprocess


def sha(body):return hashlib.sha256(body).hexdigest()


def materialize(run):
    repo=Path(__file__).resolve().parents[1]
    plan=json.loads((run/'plan.json').read_text(encoding='utf-8'))
    capture=(run/'sources.json.gz').read_bytes()
    assert sha(capture)==plan['sources_sha256']
    files={name:text.encode() for name,text in json.loads(gzip.decompress(capture)).items()}
    assert set(files)==set(plan['code_sha256'])
    for name,body in files.items():assert sha(body)==plan['code_sha256'][name]
    # These imported benchmark helpers were omitted from the original source
    # digest. Bind them to the unchanged committed implementation, explicitly
    # recording this provenance limitation rather than backdating a capture.
    extra={}
    for name in ('benchmarks/__init__.py','benchmarks/rival_reproduction.py'):
        body=(repo/name).read_bytes()
        committed=subprocess.check_output(['git','show','8ec1214:'+name],cwd=repo)
        assert body==committed, 'Uncaptured helper changed since the baseline commit'
        files[name]=body;extra[name]={'sha256':sha(body),'committed_source':'8ec1214'}
    destination=run/'execution-root'
    if destination.exists():raise ValueError('Execution copy already exists; validate and reuse it')
    destination.mkdir()
    for name,body in files.items():
        relative=PurePosixPath(name)
        assert not relative.is_absolute() and '..' not in relative.parts
        assert relative.parts[0] in ('npk','benchmarks') and relative.suffix=='.py'
        path=destination.joinpath(*relative.parts)
        assert path.resolve().is_relative_to(destination.resolve())
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        assert path.read_bytes()==body
    record={'status':'MATERIALIZED','plan_sha256':sha((run/'plan.json').read_bytes()),
            'captured_files':plan['code_sha256'],'additional_helpers':extra,
            'all_files':{name:sha(body) for name,body in sorted(files.items())},
            'limitation':'Two helper files validated against unchanged commit; they were not in the original runtime digest',
            'execution_root':str(destination.resolve())}
    (run/'execution-copy.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print({'status':record['status'],'files':len(files),'execution_root':record['execution_root']},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    materialize(p.parse_args().run)

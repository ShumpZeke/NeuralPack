"""Execute new probes in a fresh interpreter against the frozen source tree."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import socket
import sys
import time
from unittest.mock import patch

sha=lambda b:hashlib.sha256(b).hexdigest()


def run(root,output):
    root=root.resolve()
    if output.exists():raise ValueError('Fresh oracle output required')
    plan=json.loads((root/'plan.json').read_bytes())
    assert sha((root/'plan.json').read_bytes())==(root/'plan.sha256').read_text().strip()
    source=root/'sources'
    for name,digest in plan['source_sha256'].items():assert sha((source/name).read_bytes())==digest
    from benchmarks.transport_behavior import TASKS,probe
    assert TASKS==plan['tasks']
    assert sha(Path(sys.modules[probe.__module__].__file__).read_bytes())==plan['behavior_source_sha256']
    assert not any(name in sys.modules for name in plan['packages']), 'Use a fresh oracle process'
    sys.dont_write_bytecode=True;sys.path.insert(0,str(source))
    activity=[]
    def refused(*args,**kw):
        activity.append(True)
        raise AssertionError('Oracle tried to access network or sleep')
    rows=[]
    with patch.object(socket.socket,'connect',refused),patch.object(socket.socket,'connect_ex',refused),patch.object(time,'sleep',refused):
        for task in TASKS:
            expected=probe(task['id'])
            assert not activity, 'Forbidden oracle activity was swallowed'
            json.dumps(expected,allow_nan=False)
            rows.append({'task_id':task['id'],'expected':expected})
    loaded={};external_aliases={}
    for name,module in sys.modules.copy().items():
        if name.split('.')[0] not in plan['packages'] or not getattr(module,'__file__',None):continue
        path=Path(module.__file__).resolve()
        canonical=getattr(module,'__name__',name)
        if not path.is_relative_to(source) and canonical!=name and canonical.split('.')[0] not in plan['packages']:
            # Requests exposes third-party packages under compatibility aliases.
            # Verify object identity and report these dependencies outside the corpus.
            assert sys.modules.get(canonical) is module, 'Unverified external module alias'
            external_aliases[name]={'canonical':canonical,'sha256':sha(path.read_bytes())}
            continue
        assert path.is_relative_to(source), 'Oracle imported non-captured library source'
        rel=path.relative_to(source).as_posix()
        assert rel in plan['source_sha256'] and sha(path.read_bytes())==plan['source_sha256'][rel]
        loaded[name]={'path':rel,'sha256':sha(path.read_bytes())}
    versions={name:sys.modules[name].__version__ for name in plan['packages']}
    assert versions=={name:info['version'] for name,info in plan['packages'].items()}
    result={'status':'COMPLETE','evidence_mode':'LOCAL','generative_calls':0,
            'plan_sha256':sha((root/'plan.json').read_bytes()),'runner_sha256':sha(Path(__file__).read_bytes()),
            'python':platform.python_version(),'implementation':platform.python_implementation(),
            'platform':platform.platform(),'package_versions':versions,'loaded_sources':loaded,'rows':rows,
            'external_dependency_aliases':external_aliases,
            'network_or_sleep_attempts':len(activity),
            'limits':['Expected outputs are interpreter/library behavior, not target-model answers',
                      'Only modules in the three captured libraries have source-bound import checks; external dependencies remain outside the available corpus']}
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'status':'COMPLETE','python':result['python'],'tasks':len(rows),'rows':rows}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.root,a.output)

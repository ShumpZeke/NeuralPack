"""Acquire pinned public Click/CPython source for external-dependency experiments."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import sysconfig
import urllib.request

FILES=[
    'Lib/configparser.py','Lib/difflib.py','Lib/pathlib.py','Lib/enum.py',
    'Lib/fnmatch.py','Lib/shlex.py','Lib/urllib/parse.py','Lib/gettext.py',
    'Lib/re/__init__.py','Lib/re/_parser.py','Lib/re/_compiler.py','Lib/re/_constants.py',
    'Lib/os.py','Lib/posixpath.py','Lib/ntpath.py','Lib/genericpath.py',
    'Lib/functools.py','Lib/collections/__init__.py','Lib/collections/abc.py',
    'Lib/_collections_abc.py','Lib/types.py','Lib/typing.py','Lib/contextlib.py',
    'Doc/library/configparser.rst','Doc/library/difflib.rst','Doc/library/pathlib.rst',
    'Doc/library/enum.rst','Doc/library/fnmatch.rst','Doc/library/shlex.rst',
    'Doc/library/urllib.parse.rst',
]


def digest(body):return hashlib.sha256(body).hexdigest()


def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'NeuralPack-local-research'})
    with urllib.request.urlopen(request,timeout=60) as response:return response.read()


def normalized(body):return body.decode('utf-8').replace('\r\n','\n').replace('\r','\n').encode()


def acquire(root):
    if root.exists():raise ValueError('new corpus directory required')
    assert sys.version_info[:3]==(3,12,10),'oracle interpreter differs from pinned version'
    repo=Path(__file__).resolve().parents[1];root.mkdir(parents=True);source=root/'source';source.mkdir()
    prior=repo/'experiments/runs/repository-click-v1/plan.json';old=json.loads(prior.read_text())
    assert digest(prior.read_bytes())==prior.with_suffix('.sha256').read_text().strip()
    manifest=[]
    for item in old['source_manifest']:
        original=prior.parent/'source/click-8.5.0'/item['path'];body=original.read_bytes()
        assert digest(body)==item['sha256'];target=source/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(body);manifest.append({**item,'source_package':'click','source_version':'8.5.0'})
    ref_url='https://api.github.com/repos/python/cpython/git/ref/tags/v3.12.10'
    reference=json.loads(fetch(ref_url));resolved=reference['object'];tag=None
    if resolved['type']=='tag':tag=json.loads(fetch(resolved['url']));resolved=tag['object']
    assert resolved['type']=='commit';revision=resolved['sha'];assert len(revision)==40
    acquisition={'created_utc':datetime.now(timezone.utc).isoformat(),'ref_url':ref_url,'reference':reference,
                 'tag_object':tag,'commit':revision,'files':[],'click_parent_plan_sha256':digest(prior.read_bytes())}
    def download(relative):
        url=f'https://raw.githubusercontent.com/python/cpython/{revision}/{relative}'
        body=fetch(url);canonical=normalized(body);local_sha=None
        if relative.startswith('Lib/'):
            installed=Path(sysconfig.get_path('stdlib'))/relative[4:]
            local=installed.read_bytes();local_sha=digest(local)
            assert normalized(local)==canonical,'installed oracle library differs from public source'
        return relative,url,body,canonical,local_sha
    with ThreadPoolExecutor(max_workers=4) as pool:
        for relative,url,body,canonical,local_sha in pool.map(download,FILES):
            target=source/'cpython'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(canonical)
            path=target.relative_to(source).as_posix()
            manifest.append({'path':path,'sha256':digest(canonical),'bytes':len(canonical),
                             'source_package':'cpython','source_version':'3.12.10'})
            acquisition['files'].append({'path':path,'url':url,'remote_sha256':digest(body),
                                        'normalized_sha256':digest(canonical),'installed_raw_sha256':local_sha})
            print({'acquired':path,'bytes':len(canonical)},flush=True)
    license_body=fetch(f'https://raw.githubusercontent.com/python/cpython/{revision}/LICENSE')
    (root/'CPYTHON-LICENSE.txt').write_bytes(license_body)
    acquisition.update(source_manifest=manifest,license_sha256=digest(license_body),
                       corpus_tokens=sum(max(1,len((source/r['path']).read_text(encoding='utf-8'))//4) for r in manifest),
                       notes=['Public pinned source; local standard-library oracles match after physical newline normalization',
                              'Explicit selected external modules and docs, not a complete Python execution environment',
                              'No target-model calls and no source code executed during acquisition'])
    raw=json.dumps(acquisition,indent=2).encode();(root/'acquisition.json').write_bytes(raw)
    (root/'acquisition.sha256').write_text(digest(raw))
    print({'files':len(manifest),'corpus_tokens':acquisition['corpus_tokens'],'cpython_commit':revision,'generative_calls':0})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    acquire(p.parse_args().output.resolve())

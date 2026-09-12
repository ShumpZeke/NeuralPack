"""Acquire the pinned library source as an explicit manual-corpus challenger."""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import re
import tarfile
import urllib.request
from benchmarks.prospective_eval import write_json
from benchmarks.source_archive import manifest_sources
from npk.pack.compile import _source_lines
from npk.pack.source_policy import check_source


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def source_members(body):
    """Read only regular library Python members; never extract or import a module."""
    files={}
    with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as archive:
        for member in archive.getmembers():
            path=PurePosixPath(member.name)
            if not member.isfile() or len(path.parts)<4 or path.parts[1:3]!=('lib','sqlalchemy') or path.suffix!='.py':continue
            if path.is_absolute() or '..' in path.parts or ':' in member.name or '\\' in member.name:raise ValueError('Unsafe archive member')
            relative='sqlalchemy/'+str(PurePosixPath(*path.parts[1:]))
            if relative in files:raise ValueError('Duplicate library source')
            stream=archive.extractfile(member);assert stream is not None
            source=stream.read();text=source.decode('utf-8');check_source(text,relative)
            ast.parse(text);files[relative]=source
    if not files:raise ValueError('No Python library source found')
    return files


def inventory(files):
    definitions=[];docstrings=[];directives=[]
    for path,body in sorted(files.items()):
        text=body.decode();lines=_source_lines(text)
        if path.endswith('.py'):
            tree=ast.parse(text)
            def visit(node,scope):
                if isinstance(node,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                    name='.'.join(scope)
                    if not isinstance(node,ast.Module):definitions.append({'path':path,'name':name,'kind':type(node).__name__,'span':[node.lineno,node.end_lineno]})
                    if node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):
                        first=node.body[0];literal='\n'.join(lines[first.lineno-1:first.end_lineno])
                        docstrings.append({'path':path,'name':name or '<module>','span':[first.lineno,first.end_lineno],
                                           'source_sha256':sha(literal.encode()),'source_chars':len(literal)})
                for child in ast.iter_child_nodes(node):
                    visit(child,scope+[child.name] if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) else scope)
            visit(tree,[])
        elif path.endswith('.rst'):
            module=None
            for number,line in enumerate(lines,1):
                match=re.match(r'^\s*\.\.\s+(currentmodule|automodule|autoclass|autofunction|automethod|autoattribute|autodata)::\s*(.*?)\s*$',line)
                if not match:continue
                kind,target=match.groups()
                if kind=='currentmodule':module=target
                else:directives.append({'path':path,'line':number,'kind':kind,'target':target,'currentmodule':module})
    return {'definitions':definitions,'docstrings':docstrings,'autodoc_directives':directives,
            'limitation':'Static inventory only; no import/re-export resolution, inheritance expansion or rendered-Sphinx equivalence'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('New corpus run required')
    previous=read(a.parent/'acquisition.json')
    with urllib.request.urlopen(previous['archive_url'],timeout=60) as response:body=response.read()
    assert sha(body)==previous['archive_sha256'], 'Pinned upstream archive changed'
    added=source_members(body)
    originals={name.removeprefix('source/'):value for name,value in manifest_sources(a.parent/'source',previous['source_manifest'],'source').items()}
    assert not added.keys() & originals.keys();files={**originals,**added}
    a.output.mkdir(parents=True);(a.output/'upstream.tar.gz').write_bytes(body)
    manifest=[]
    for name,value in sorted(files.items()):
        destination=a.output/'source'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(value)
        manifest.append({'path':name,'sha256':sha(value),'bytes':len(value),'language':'python' if name.endswith('.py') else 'rst'})
    license_body=(a.parent/'LICENSE.txt').read_bytes();assert sha(license_body)==previous['license_sha256'];(a.output/'LICENSE.txt').write_bytes(license_body)
    details=inventory(files);write_json(a.output/'source-inventory.json',details)
    record={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','generative_calls':0,
            'repository':previous['repository'],'tag':previous['tag'],'commit':previous['commit'],
            'archive_url':previous['archive_url'],'archive_sha256':sha(body),'license_sha256':previous['license_sha256'],
            'parent_acquisition_sha256':sha((a.parent/'acquisition.json').read_bytes()),'source_manifest':manifest,
            'manual_files':len(originals),'added_python_files':len(added),'added_python_bytes':sum(map(len,added.values())),
            'inventory_sha256':sha((a.output/'source-inventory.json').read_bytes()),
            'selection_rule':'All regular .py files beneath pinned lib/sqlalchemy, plus all original declared manual files',
            'limitations':['Known library selected after prior manual-only failures; not an independently sealed corpus',
                           'No tests, generated rendering, oracle labels, binary extension bodies or runtime state added',
                           'Inventory detects literal docstrings and directives, not semantic completeness or executable dependency closure']}
    write_json(a.output/'acquisition.json',record)
    print({k:record[k] for k in ('manual_files','added_python_files','added_python_bytes','commit')},flush=True)
    print({'definitions':len(details['definitions']),'docstrings':len(details['docstrings']),'directives':len(details['autodoc_directives'])},flush=True)


if __name__=='__main__':main()

"""Source manifests, rather than extension guesses, define required archive files."""
import hashlib
from pathlib import Path, PurePosixPath


def manifest_sources(root, manifest, prefix):
    root=Path(root).resolve();result={};seen=set()
    for item in manifest:
        name=item['path']
        if (not isinstance(name,str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or any(p in ('.','..') for p in name.split('/'))):
            raise ValueError('Invalid source archive path')
        if name in seen:raise ValueError('Duplicate source manifest path')
        seen.add(name);path=(root/name).resolve()
        if not path.is_relative_to(root):raise ValueError('Source archive path escaped root')
        body=path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=item['sha256']:raise ValueError('Source archive bytes differ from manifest')
        result[prefix.rstrip('/')+'/'+name]=body
    return result

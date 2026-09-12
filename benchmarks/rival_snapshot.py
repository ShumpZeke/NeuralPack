"""Freeze a read-only CRISP comparison without importing its mutable checkout."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from npk.pack.source_policy import check_source


def digest(body):
    return hashlib.sha256(body).hexdigest()


def freeze(source, output):
    source = source.resolve()
    if output.exists():
        raise ValueError('A fresh snapshot directory is required')
    paths = set(source.glob('*.md'))
    for directory in ('crisp', 'bench', 'tests', 'corpus/test_src', 'corpus/src'):
        paths.update((source / directory).rglob('*.py'))
    for name in ('tasks_heldout.json', 'tasks_dev.json', 'queries_w2.json'):
        paths.add(source / 'work' / name)
    for package in ('rich-14.2.0', 'jinja2-3.1.6', 'werkzeug-3.1.3', 'click-8.5.0', 'urllib3-2.7.0'):
        paths.update((source / 'corpus' / package).glob('LICENSE*'))
        paths.update((source / 'corpus' / package).glob('PKG-INFO'))
    bodies = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Snapshot source escapes root')
        body = path.read_bytes()
        relative = path.relative_to(source).as_posix()
        check_source(body.decode('utf-8'), relative)
        bodies[relative] = body
    # A second full read detects an actively changing rival checkout.
    for name, body in bodies.items():
        if (source / name).read_bytes() != body:
            raise ValueError('Source changed during snapshot; retry as a new run')
    for name, body in bodies.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(),
                'source_root': str(source), 'evidence_mode': 'LOCAL',
                'generative_calls': 0, 'files': {
                    name: {'sha256': digest(body), 'bytes': len(body)}
                    for name, body in bodies.items()},
                'limitations': ['Read-only copy; rival checkout has no Git history',
                                'Recognized credential-pattern screen is not proof of absence of all secrets',
                                'Rival task sets are now inspected development data, not a new holdout',
                                'No rival source or compiled artifact is a product dependency']}
    raw = json.dumps(manifest, indent=2).encode()
    (output / 'snapshot.json').write_bytes(raw)
    print(json.dumps({'files': len(bodies), 'bytes': sum(map(len, bodies.values())),
                      'manifest_sha256': digest(raw)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze(args.source, args.output)

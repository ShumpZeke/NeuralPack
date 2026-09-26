"""Reuse cached packs across an output-identical compiler change, with proof.

    python -m benchmarks.npkbench.alias --from OLD_FINGERPRINT --split dev-fast --sample 3

Rebuilds a stratified sample of cached packs with the CURRENT compiler and
requires logical equality (every table, FTS5 postings, manifest minus build
metadata) with the cached packs. Only then is the current fingerprint's
directory made a symlink to the old one, and the evidence is written next to
it. Any difference aborts; nothing is aliased.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import data, packs, repos
from .equivalence import differences


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="old", required=True)
    parser.add_argument("--split", default="dev-fast")
    parser.add_argument("--sample", type=int, default=3)
    parser.add_argument("--options", default="{}", help="compile options JSON")
    args = parser.parse_args(argv)
    options = json.loads(args.options)
    old_dir = packs.PACKS / args.old
    new_fp = packs.compiler_fingerprint(options)
    new_dir = packs.PACKS / new_fp
    if new_dir.exists():
        raise SystemExit(f"{new_dir} already exists; refusing to alias")
    tasks = [t for t in data.split(args.split) if (old_dir / f"{t.instance_id}.npk").exists()]
    by_repo = {}
    for task in sorted(tasks, key=lambda t: -(old_dir / f"{t.instance_id}.npk").stat().st_size):
        by_repo.setdefault(task.repo, task)
    sample = list(by_repo.values())[:args.sample]
    from npk.pack import compile_pack
    evidence = []
    scratch = packs.PACKS / f".alias-check-{new_fp}"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        for task in sample:
            tree = repos.scratch_tree(task.repo, task.base_commit)
            try:
                fresh = scratch / f"{task.instance_id}.npk"
                started = time.perf_counter()
                compile_pack(tree, fresh, **options)
                diff = differences(old_dir / f"{task.instance_id}.npk", fresh)
            finally:
                repos.drop_tree(tree)
            evidence.append({"instance_id": task.instance_id, "differences": diff,
                             "compile_s": round(time.perf_counter() - started, 2)})
            if diff:
                print(json.dumps(evidence, indent=1))
                raise SystemExit("logical difference found; not aliasing")
    finally:
        for f in scratch.glob("*"):
            f.unlink()
        scratch.rmdir()
    new_dir.symlink_to(old_dir.name)
    record = {"alias": new_fp, "target": args.old, "options": options, "verified": evidence,
              "date": time.strftime("%Y-%m-%d")}
    (packs.PACKS / f"ALIAS-{new_fp}.json").write_text(json.dumps(record, indent=1))
    print(json.dumps(record, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

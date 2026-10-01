"""Paired compile timing for two code trees (e.g. baseline vs a compiler change).

    python -m benchmarks.npkbench.compile_timing --tree OLD_ROOT --tree NEW_ROOT \
        --task django__django-13768 --repeats 3

Each code tree is imported in a fresh subprocess (so modules never mix), the
same exported source tree is compiled, and runs alternate A/B/A/B to spread
machine drift across both arms. Reports per-run seconds and the median ratio,
and checks the resulting packs for logical equality.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from . import data, repos
from .equivalence import differences

SNIPPET = """
import json, sys, time, warnings
warnings.simplefilter('ignore')
sys.path.insert(0, sys.argv[1])
from npk.pack import compile_pack
started = time.perf_counter()
stats = compile_pack(sys.argv[2], sys.argv[3])
print(json.dumps({'seconds': time.perf_counter() - started, 'blocks': stats.blocks}))
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", action="append", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    task = next(t for t in data.split(args.split) if t.instance_id == args.task)
    source = repos.scratch_tree(task.repo, task.base_commit)
    try:
        removed = repos.remove_compile_blockers(source)
        results = {tree: [] for tree in args.tree}
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {}
            for rep in range(args.repeats):
                for i, tree in enumerate(args.tree):
                    out = Path(tmp) / f"{i}-{rep}.npk"
                    proc = subprocess.run([sys.executable, "-c", SNIPPET, tree, str(source), str(out)],
                                          capture_output=True, text=True, check=True)
                    results[tree].append(json.loads(proc.stdout.strip().splitlines()[-1])["seconds"])
                    outputs[tree] = out
            base = args.tree[0]
            report = {
                "task": task.instance_id, "blockers_removed": removed,
                "seconds": {t: [round(x, 3) for x in v] for t, v in results.items()},
                "median": {t: round(statistics.median(v), 3) for t, v in results.items()},
                "speedup_vs_first": {t: round(statistics.median(results[base]) / statistics.median(v), 3)
                                     for t, v in results.items()},
                "logically_identical_to_first": {t: not differences(outputs[base], outputs[t])
                                                 for t in args.tree},
            }
        print(json.dumps(report, indent=1))
    finally:
        repos.drop_tree(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

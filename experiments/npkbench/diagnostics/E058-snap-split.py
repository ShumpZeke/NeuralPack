"""Tests-target recall by hunk class (suffix) for the default and the E058 arms of one run.

Usage: snap_split.py RUN SPLIT ARM [ARM ...]
Per-issue hunk recall (as the harness defines it) restricted to test hunks whose file ends in
.snap, to the other test hunks, and to all of them, averaged over issues that have such hunks.
"""
import collections
import gzip
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("NPK_BENCH_HOME", "/home/user/npk-data")
from benchmarks.npkbench import data

RUN, SPLIT, ARMS = sys.argv[1], sys.argv[2], sys.argv[3:]
tests = {t.instance_id: t for t in data.split(f"{SPLIT}:tests")}
spans = collections.defaultdict(dict)
with gzip.open(f"{RUN}/rows.jsonl.gz", "rt") as fh:
    for line in fh:
        r = json.loads(line)
        if r["arm"] in ARMS:
            spans[(r["arm"], r["budget"])][r["instance_id"]] = [tuple(s) for s in r["spans"]]
budgets = sorted({b for _, b in spans})
classes = {"all": lambda p: True, ".snap": lambda p: p.endswith(".snap"),
           "non-.snap": lambda p: not p.endswith(".snap")}
print(f"{RUN} tests target ({len(tests)} issues)")
for name, pred in classes.items():
    n_issues = sum(any(pred(h.path) for h in t.hunks) for t in tests.values())
    print(f"  hunk class {name} ({n_issues} issues, {sum(pred(h.path) for t in tests.values() for h in t.hunks)} hunks)")
    for arm in ARMS:
        cells = []
        for b in budgets:
            vals = []
            for iid, t in tests.items():
                hs = [h for h in t.hunks if pred(h.path)]
                if not hs or iid not in spans[(arm, b)]:
                    continue
                sel = spans[(arm, b)][iid]
                vals.append(sum(h.found_by(sel) for h in hs) / len(hs))
            cells.append(f"{b // 1024:>2d}K {sum(vals) / max(1, len(vals)):.3f}")
        print(f"    {arm:22s} " + "  ".join(cells))

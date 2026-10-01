"""Which newly indexed suffixes does a candidate arm select, and what do they cost or gain?

Usage: suffix_attrib.py RUN SPLIT BASE_ARM CAND_ARM
For every (issue, budget): spans selected only by the candidate ("added") grouped by file suffix, with the
number of fix / tests gold hunks each added span covers; and the recall change of the issue per target,
attributed to the suffixes of its added spans.
"""
import collections
import gzip
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("NPK_BENCH_HOME", "/home/user/npk-data")
from benchmarks.npkbench import data

RUN, SPLIT, BASE, CAND = sys.argv[1:5]
fix = {t.instance_id: t for t in data.split(SPLIT)}
tests = {t.instance_id: t for t in data.split(f"{SPLIT}:tests")}
spans = collections.defaultdict(dict)
recall = collections.defaultdict(dict)
with gzip.open(f"{RUN}/rows.jsonl.gz", "rt") as fh:
    for line in fh:
        r = json.loads(line)
        arm = r["arm"].split("@")[0]
        if arm in (BASE, CAND):
            key = (arm, r["arm"].partition("@")[2] or "fix", r["budget"])
            recall[key][r["instance_id"]] = r["hunk_recall"]
            if "@" not in r["arm"]:
                spans[(arm, r["budget"])][r["instance_id"]] = [tuple(s) for s in r["spans"]]


def suffix(path):
    name = os.path.basename(path)
    return os.path.splitext(name)[1].lower() or name


budgets = sorted({b for (_, b) in spans})
NEW = None
total = collections.defaultdict(lambda: collections.Counter())
for b in budgets:
    for iid in fix:
        base_s = set(spans[(BASE, b)].get(iid, []))
        cand_s = set(spans[(CAND, b)].get(iid, []))
        for sp in cand_s - base_s:
            suf = suffix(sp[0])
            c = total[(b, suf)]
            c["added"] += 1
            c["fix_gold"] += sum(h.found_by([sp]) for h in fix[iid].hunks)
            if iid in tests:
                c["tests_gold"] += sum(h.found_by([sp]) for h in tests[iid].hunks)
        for sp in base_s - cand_s:
            suf = suffix(sp[0])
            c = total[(b, suf)]
            c["removed"] += 1
            c["fix_gold_removed"] += sum(h.found_by([sp]) for h in fix[iid].hunks)
            if iid in tests:
                c["tests_gold_removed"] += sum(h.found_by([sp]) for h in tests[iid].hunks)
print(f"{RUN} {SPLIT}: {CAND} against {BASE}")
for b in budgets:
    rows = sorted(((s, c) for (bb, s), c in total.items() if bb == b), key=lambda x: -x[1]["added"])
    print(f"  budget {b}:")
    shown = 0
    for suf, c in rows:
        if c["added"] and shown < 14:
            print(f"    added {suf:12s} spans {c['added']:5d}  fix-gold {c['fix_gold']:3d}  tests-gold {c['tests_gold']:3d}")
            shown += 1
    lost = [(s, c) for s, c in rows if c["fix_gold_removed"] or c["tests_gold_removed"]]
    for suf, c in sorted(lost, key=lambda x: -(x[1]["fix_gold_removed"] + x[1]["tests_gold_removed"]))[:8]:
        print(f"    removed {suf:11s} spans {c['removed']:5d}  fix-gold {c['fix_gold_removed']:3d}  tests-gold {c['tests_gold_removed']:3d}")
# per-issue recall change by target with the suffix classes of the added spans
print("  issues with a change at 8K and 16K (fix, tests): count by sign and suffixes of added spans")
for b in (8192, 16384):
    for target in ("fix", "tests"):
        base_r, cand_r = recall[(BASE, target, b)], recall[(CAND, target, b)]
        for sign, name in ((-1, "loss"), (1, "gain")):
            ids = [i for i in base_r if i in cand_r and (cand_r[i] - base_r[i]) * sign > 1e-9]
            attrib = collections.Counter()
            for iid in ids:
                added = set(spans[(CAND, b)].get(iid, [])) - set(spans[(BASE, b)].get(iid, []))
                for suf in {suffix(sp[0]) for sp in added}:
                    attrib[suf] += 1
            delta = sum(cand_r[i] - base_r[i] for i in ids)
            print(f"    {b // 1024}K {target:5s} {name}: {len(ids):3d} issues (sum of recall change {delta:+.2f}); suffixes among their added spans: {dict(attrib.most_common(8))}")

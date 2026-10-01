"""D4: how often does the test mate cover a gold test hunk but not fit the budget?

For tasks whose default pack is cached and that have test-target gold: select at an unbounded budget
(no escalation), find the evidence placed by the test-mate channel and measure its size, the tokens
placed before it, and whether it covers a gold test hunk. Then count, per budget, the tasks where the
mate covers gold and (a) fits after everything before it, (b) does not fit although the block is
smaller than the budget, (c) is larger than the budget. Usage: mate_diag.py split [split ...]
"""
import collections
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("NPK_BENCH_HOME", "/home/user/npk-data")
from benchmarks.npkbench import data, packs
from npk.pack import PackSelector

# Packs cached before E059 (fingerprint of the compile sources at 0528662); they are identical to the
# current default's for every tree without an env/venv directory.
packs.compiler_fingerprint = lambda options=None: "5effbb3d57dcedd5"

BUDGETS = (1024, 2048, 4096, 8192, 16384)
rows, seen, positions = [], set(), []
for split in sys.argv[1:]:
    tests = {t.instance_id: t for t in data.split(f"{split}:tests")}
    for task in data.split(split):
        if task.instance_id in seen or task.instance_id not in tests:
            continue
        path = packs.pack_path(task)
        if not path.exists():
            continue
        seen.add(task.instance_id)
        gold = tests[task.instance_id]
        with PackSelector(str(path), enable_cache=False, enable_test_mate=True) as selector:
            sel = selector.select(task.query, budget_tokens=10**9, allow_escalation=False)
        before = 0
        mate = None
        for e in sel.evidence:
            lo, hi = e.span.rsplit(":", 1)[1].split("-")
            span = (e.path, int(lo), int(hi))
            tokens = max(1, len(e.text) // 4)
            if "test_mate" in e.channels:
                mate = (span, tokens, before)
                break
            before += tokens
        if mate is None:
            rows.append((task.instance_id, None))
            continue
        span, tokens, before = mate
        covers = any(h.found_by([span]) for h in gold.hunks)
        gold_files = {h.path for h in gold.hunks}
        in_gold_file = span[0] in gold_files
        # oracle: does any block of the mate's file cover a gold hunk?
        from npk.pack.format import load_blocks, open_pack
        with open_pack(path) as con:
            ids = [r[0] for r in con.execute("SELECT b.id FROM blocks b JOIN files f ON f.id=b.file_id WHERE f.path=?", (span[0],))]
            blocks = load_blocks(con, ids)
        oracle = any(h.found_by([(b.path, b.start_line, b.end_line)]) for h in gold.hunks for b in blocks)
        ordered = sorted(blocks, key=lambda b: b.start_line)
        covering = [i for i, b in enumerate(ordered) if any(h.found_by([(b.path, b.start_line, b.end_line)]) for h in gold.hunks)]
        positions.append((task.instance_id, len(ordered), covering, covers, in_gold_file))
        rows.append((task.instance_id, (span, tokens, before, covers, task.repo, in_gold_file, oracle)))
n = len(rows)
with_mate = [r for r in rows if r[1] is not None]
print(f"{n} tasks with test gold and a cached pack; mate placed in {len(with_mate)}")
cov = [r for r in with_mate if r[1][3]]
print(f"mate covers a gold test hunk in {len(cov)} tasks ({len(cov) / max(1, n):.1%} of tasks)")
sizes = sorted(r[1][1] for r in with_mate)
q = lambda p: sizes[min(len(sizes) - 1, int(p * len(sizes)))]
print(f"mate block tokens: p25 {q(.25)} p50 {q(.5)} p75 {q(.75)} p90 {q(.9)} max {sizes[-1]}")
print("covering mates, budget: fits after the blocks before it | block fits alone but not after | block larger than budget")
for b in BUDGETS:
    fits = sum(1 for r in cov if r[1][2] + r[1][1] <= b)
    alone = sum(1 for r in cov if r[1][2] + r[1][1] > b and r[1][1] <= b)
    big = sum(1 for r in cov if r[1][1] > b)
    print(f"  {b // 1024:>2d}K: {fits:3d} | {alone:3d} | {big:3d}   (share of all tasks that a perfect trim could add: <= {(alone + big) / n:.1%})")
ing = [r for r in with_mate if r[1][5]]
orc = [r for r in with_mate if r[1][6]]
print(f"mate file is a gold test file in {len(ing)} of {n} tasks ({len(ing) / n:.1%}); some block of that file covers gold in {len(orc)} ({len(orc) / n:.1%}); the mate block does in {len(cov)} ({len(cov) / n:.1%})")
print(f"  conditional on the mate file being a gold file: mate block hits {sum(1 for r in ing if r[1][3]) / max(1, len(ing)):.1%}")
by_repo = collections.Counter()
for r in cov:
    if r[1][1] > 2048:
        by_repo[r[1][4]] += 1
print("covering mates larger than 2K tokens by repo:", dict(by_repo.most_common(8)))

print()
gold_mate = [x for x in positions if x[4]]
print(f"tasks whose mate file is a gold file: {len(gold_mate)}; blocks per such file: median {sorted(x[1] for x in gold_mate)[len(gold_mate) // 2]}")
miss = [x for x in gold_mate if not x[3]]
print(f"  of which the mate block misses: {len(miss)}")
def tail_rank(x):  # distance of the first covering block from the end (0 = last block)
    return x[1] - 1 - max(x[2]) if x[2] else None
for name, group in (("mate block hits", [x for x in gold_mate if x[3]]), ("mate block misses", miss)):
    ranks = [tail_rank(x) for x in group if x[2]]
    print(f"  {name}: covering block counted from the end of the file: last {sum(r == 0 for r in ranks)}, last two {sum(r <= 1 for r in ranks)}, last three {sum(r <= 2 for r in ranks)} of {len(ranks)};  from the start: first {sum(min(x[2]) == 0 for x in group if x[2])}")
rel = [(min(x[2]) / max(1, x[1] - 1)) for x in miss if x[2]]
bins = [0] * 5
for r in rel:
    bins[min(4, int(r * 5))] += 1
print("  relative position of the first covering block in the file for the misses (quintiles from the start):", bins)

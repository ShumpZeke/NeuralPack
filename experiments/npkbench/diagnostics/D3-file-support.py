"""D3: does file-level support separate the gold block from the other lexical candidates?

Same tasks as D2 (cached default packs). Product lexical ranking to depth DEPTH; orders compared by the
rank of the first gold block: lexical; file support (sum of 1/(60+rank) of the file's candidates);
RRF(lexical, file support); file-first (files by their best candidate, blocks within a file by lexical
rank); RRF(lexical, file-first). Usage: file_diag.py DEPTH split [split ...]
"""
import collections
import importlib
import os
import statistics
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("NPK_BENCH_HOME", "/home/user/npk-data")
from benchmarks.npkbench import data, packs
from npk.pack.format import load_blocks, open_pack

sel = importlib.import_module("npk.pack.select")
DEPTH = int(sys.argv[1])
SPLITS = sys.argv[2:]


def first_gold(order, gold):
    return next((r for r, b in enumerate(order) if b in gold), None)


def rrf_order(lex, other_rank):
    lex_rank = {b: r for r, b in enumerate(lex)}
    return sorted(lex, key=lambda b: -(1 / (60 + lex_rank[b]) + 1 / (60 + other_rank[b])))


rows, seen = [], set()
for split in SPLITS:
    for task in data.split(split):
        if task.instance_id in seen:
            continue
        path = packs.pack_path(task)
        if not path.exists():
            continue
        seen.add(task.instance_id)
        query = sel._strip_issue_template(task.query)
        with open_pack(path) as con:
            lex = sel._lexical_channel(con, query, DEPTH, sel.TITLE_WEIGHT, sel.TF_CAP)
            if not lex:
                continue
            blocks = {b.id: b for b in load_blocks(con, lex)}
        lex = [b for b in lex if b in blocks]
        gold = {b for b in lex if any(h.found_by([(blocks[b].path, blocks[b].start_line, blocks[b].end_line)])
                                      for h in task.hunks)}
        if not gold:
            continue
        lex_rank = {b: r for r, b in enumerate(lex)}
        support = collections.defaultdict(float)
        best = {}
        for b in lex:
            p = blocks[b].path
            support[p] += 1 / (60 + lex_rank[b])
            best.setdefault(p, lex_rank[b])
        by_support = sorted(lex, key=lambda b: (-support[blocks[b].path], lex_rank[b]))
        support_rank = {b: r for r, b in enumerate(by_support)}
        file_first = sorted(lex, key=lambda b: (best[blocks[b].path], lex_rank[b]))
        first_rank = {b: r for r, b in enumerate(file_first)}
        orders = {"lexical": lex, "file support": by_support, "rrf(lex,support)": rrf_order(lex, support_rank),
                  "file-first": file_first, "rrf(lex,file-first)": rrf_order(lex, first_rank)}
        rows.append((task.instance_id, {k: first_gold(v, gold) for k, v in orders.items()}))
print(f"depth={DEPTH}: {len(rows)} tasks with a gold block in the lexical top {DEPTH}")
for name in ("lexical", "file support", "rrf(lex,support)", "file-first", "rrf(lex,file-first)"):
    ranks = [r[1][name] for r in rows]
    print(f"  {name:20s} top1 {sum(x == 0 for x in ranks):3d} top3 {sum(x < 3 for x in ranks):3d} top10 {sum(x < 10 for x in ranks):3d} "
          f"top30 {sum(x < 30 for x in ranks):3d}  median rank {statistics.median(ranks) + 1:.0f}  mean reciprocal {statistics.mean(1 / (x + 1) for x in ranks):.3f}")
for name in ("rrf(lex,support)", "rrf(lex,file-first)", "file-first"):
    better = sum(r[1][name] < r[1]["lexical"] for r in rows)
    worse = sum(r[1][name] > r[1]["lexical"] for r in rows)
    print(f"  {name} vs lexical: better {better}, worse {worse}, equal {len(rows) - better - worse}")

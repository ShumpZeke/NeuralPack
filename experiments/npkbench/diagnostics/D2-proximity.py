"""D2: does term proximity separate the gold block from the other lexical candidates?

For tasks whose pack is cached: take the product's lexical ranking to depth DEPTH, score each
candidate by the largest number of distinct query terms inside any window of W analyzed tokens
(ties keep lexical rank), and compare the rank of the first gold block under lexical order,
proximity order and RRF(lexical, proximity). Usage: prox_diag.py W DEPTH split [split ...]
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
from npk.pack.search import analyzed_terms

sel = importlib.import_module("npk.pack.select")
W, DEPTH = int(sys.argv[1]), int(sys.argv[2])
SPLITS = sys.argv[3:]


def window_score(tokens, terms):
    hits = [(i, t) for i, t in enumerate(tokens) if t in terms]
    if not hits:
        return 0
    best, left = 0, 0
    counts = collections.Counter()
    for right, (pos, term) in enumerate(hits):
        counts[term] += 1
        while pos - hits[left][0] >= W:
            old = hits[left][1]
            counts[old] -= 1
            if not counts[old]:
                del counts[old]
            left += 1
        best = max(best, len(counts))
    return best


def first_gold(order, gold):
    return next((r for r, b in enumerate(order) if b in gold), None)


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
            terms = set(sel._lexical_terms(con, query))
            blocks = {b.id: b for b in load_blocks(con, lex)}
        gold = {b for b in lex if b in blocks and any(
            h.found_by([(blocks[b].path, blocks[b].start_line, blocks[b].end_line)]) for h in task.hunks)}
        if not gold:
            continue
        prox = {b: window_score(analyzed_terms(blocks[b].text), terms) for b in lex if b in blocks}
        lex_rank = {b: r for r, b in enumerate(lex)}
        by_prox = sorted(lex, key=lambda b: (-prox.get(b, 0), lex_rank[b]))
        prox_rank = {b: r for r, b in enumerate(by_prox)}
        rrf = sorted(lex, key=lambda b: -(1 / (60 + lex_rank[b]) + 1 / (60 + prox_rank[b])))
        rows.append((task.instance_id, first_gold(lex, gold), first_gold(by_prox, gold), first_gold(rrf, gold)))
print(f"W={W} depth={DEPTH}: {len(rows)} tasks with a gold block in the lexical top {DEPTH}")
for name, idx in (("lexical", 1), ("proximity", 2), ("rrf(lex,prox)", 3)):
    ranks = [r[idx] for r in rows]
    print(f"  {name:14s} top1 {sum(r == 0 for r in ranks):3d} top3 {sum(r < 3 for r in ranks):3d} top10 {sum(r < 10 for r in ranks):3d} "
          f"top30 {sum(r < 30 for r in ranks):3d}  median rank {statistics.median(ranks) + 1:.0f}  mean reciprocal {statistics.mean(1 / (r + 1) for r in ranks):.3f}")
better = sum(r[3] < r[1] for r in rows); worse = sum(r[3] > r[1] for r in rows)
print(f"  rrf vs lexical: better {better}, worse {worse}, equal {len(rows) - better - worse}")

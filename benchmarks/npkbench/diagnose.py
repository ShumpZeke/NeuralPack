"""Failure analysis for one arm on cached packs: where does the budget go?

    python -m benchmarks.npkbench.diagnose --split dev-fast --arm npk_default --budget 4096

For every task it re-runs the arm's full ranking and classifies each gold hunk:
``selected`` (in the budgeted selection), ``ranked_skipped`` (inside the
budget's rank prefix but not selected -- a packing loss), ``ranked_later``
(ranked, but after the budget is exhausted -- a ranking loss), or ``unranked``
(outside the top-1000 candidates -- a recall loss). It also reports which path
categories consume the selected tokens.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path
from typing import Dict, List

from . import arms as arms_mod
from . import data, packs

CATEGORIES = (
    ("test", re.compile(r"(^|/)(tests?|testing)(/|$)|(^|/)test_[^/]*$|_tests?\.py$|(^|/)conftest\.py$")),
    ("doc", re.compile(r"(^|/)(docs?|doc_src)(/|$)|\.(rst|md|txt)$")),
    ("example", re.compile(r"(^|/)(examples?|galleries|tutorials?|benchmarks?|asv_bench)(/|$)")),
)


def category(path: str) -> str:
    for name, pattern in CATEGORIES:
        if pattern.search(path):
            return name
    return "source"


def analyze(task: data.Task, arm: arms_mod.Arm, budget: int) -> Dict:
    pack = packs.pack_path(task, arm.compile_options)
    selected = arm.run(pack, task, [budget])[budget]
    ranking = arm.ranking(pack, task) or []
    chosen = set(selected.spans)
    prefix: List = []
    spent = 0
    for item in ranking:
        if spent + item[3] > budget:
            break
        prefix.append(item)
        spent += item[3]
    outcome = []
    for hunk in task.hunks:
        if hunk.found_by(list(chosen)):
            outcome.append("selected")
            continue
        rank = next((i for i, (p, lo, hi, _t) in enumerate(ranking) if hunk.found_by([(p, lo, hi)])), None)
        if rank is None:
            outcome.append("unranked")
        elif any(hunk.found_by([(p, lo, hi)]) for p, lo, hi, _t in ranking[:len(prefix) + 1]):
            outcome.append("ranked_skipped")
        else:
            outcome.append("ranked_later")
    tokens_by_cat: Dict[str, int] = collections.Counter()
    by_span = {(p, lo, hi): t for p, lo, hi, t in ranking}
    for span in selected.spans:
        tokens_by_cat[category(span[0])] += by_span.get(span, 0)
    gold_rank = next((i for i, (p, lo, hi, _t) in enumerate(ranking)
                      if any(h.found_by([(p, lo, hi)]) for h in task.hunks)), None)
    gold_file_rank = next((i for i, (p, _lo, _hi, _t) in enumerate(ranking) if p in task.files), None)
    return {"instance_id": task.instance_id, "repo": task.repo, "outcome": outcome,
            "tokens_by_category": dict(tokens_by_cat), "first_gold_rank": gold_rank,
            "first_gold_file_rank": gold_file_rank,
            "gold_block_tokens": [t for p, lo, hi, t in ranking
                                  if any(h.found_by([(p, lo, hi)]) for h in task.hunks)][:3]}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev-fast")
    parser.add_argument("--arm", default="npk_default")
    parser.add_argument("--budget", type=int, default=4096)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    arm = arms_mod.get(args.arm)
    results = []
    for task in data.split(args.split):
        if packs.pack_path(task, arm.compile_options).exists():
            results.append(analyze(task, arm, args.budget))
    outcomes = collections.Counter(o for r in results for o in r["outcome"])
    cats: Dict[str, int] = collections.Counter()
    for r in results:
        cats.update(r["tokens_by_category"])
    total = sum(cats.values()) or 1
    summary = {"tasks": len(results), "budget": args.budget, "hunk_outcomes": dict(outcomes),
               "selected_token_share": {k: round(v / total, 3) for k, v in cats.most_common()},
               "first_gold_rank_median": sorted(r["first_gold_rank"] for r in results
                                                if r["first_gold_rank"] is not None)[len(results) // 2]
               if results else None}
    print(json.dumps(summary, indent=1))
    if args.out:
        args.out.write_text("\n".join(json.dumps(r) for r in results) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

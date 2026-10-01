"""E011: learned re-ranking of the product's candidate pool (pairwise logistic).

Headroom (dev-fast): gold is the top fused candidate for 36% of issues but in
the top-100 pool for 79%. A re-ranker over repository-agnostic features of
each candidate can move it up without new retrieval.

Protocol, fixed before training:
* features never name a repository, path component or identifier;
* pairs come from BOTH gold targets (fix, tests) with equal weight per query,
  so the model cannot win one target by ignoring the other;
* model selection by leave-one-repository-out cross-validation on dev only;
* the held-out split (SWE-bench Verified minus Lite) is scored once.

    python -m benchmarks.npkbench.ltr train --split dev --out weights.json
    python -m benchmarks.npkbench.ltr cv --split dev-fast
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from npk.pack.format import load_blocks, open_pack
from npk.pack.select import (RRF_K, _definition_channel, _lexical_terms, _query_entities,
                             _relation_channel)

from . import data, packs

POOL = 100
TEST = re.compile(r"(^|/)(tests?|testing|__tests__|specs?)(/|$)|(^|/)test_[^/]*$|_tests?\.[A-Za-z0-9]+$"
                  r"|(^|/)tests?\.[A-Za-z0-9]+$|(^|/)conftest\.py$|\.(test|spec)\.[jt]sx?$")
DOC = re.compile(r"(^|/)(docs?|documentation|doc_src)(/|$)|\.(rst|md|txt|adoc)$")
EXAMPLE = re.compile(r"(^|/)(examples?|samples?|demos?|tutorials?|galleries|benchmarks?|asv_bench)(/|$)")
KINDS = ("function", "class", "method", "module", "section", "chunk", "class_context")

FEATURES = (
    ["lex_norm", "lex_rank", "in_lex", "def_score", "def_rank", "in_def", "in_rel", "fused_rank",
     "log_tokens", "name_is_entity", "path_has_entity", "file_pool_count", "file_best_rank",
     "file_def_count", "query_terms", "query_entities"]
    + [f"kind_{k}" for k in KINDS] + ["role_test", "role_doc", "role_example"]
)


def _role(path: str) -> Tuple[float, float, float]:
    if TEST.search(path):
        return (1.0, 0.0, 0.0)
    if DOC.search(path):
        return (0.0, 1.0, 0.0)
    if EXAMPLE.search(path):
        return (0.0, 0.0, 1.0)
    return (0.0, 0.0, 0.0)


def candidates(con, query: str, pool: int = POOL):
    """The product's fused pool plus per-channel evidence for each block."""
    terms = _lexical_terms(con, query)
    lexical: List[Tuple[int, float]] = []
    if terms:
        match = " OR ".join(f'"{t}"' for t in terms)
        lexical = [(r[0], -r[1]) for r in con.execute(
            "SELECT lexical.rowid, bm25(lexical,1.0,1.0,1.0) FROM lexical JOIN blocks b ON b.id=lexical.rowid "
            "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
            "ORDER BY bm25(lexical,1.0,1.0,1.0), f.path COLLATE BINARY, b.ordinal LIMIT ?",
            (match, pool))]
    lex_ids = [b for b, _s in lexical]
    relation = _relation_channel(con, query, pool)
    definition = _definition_channel(con, query, pool, lex_ids)
    fused: Dict[int, float] = {}
    for ordered in (lex_ids, relation, definition):
        for rank, block_id in enumerate(ordered):
            fused[block_id] = fused.get(block_id, 0.0) + 1.0 / (RRF_K + rank)
    order = sorted(fused, key=lambda b: -fused[b])[:pool]
    return order, dict(lexical), {b: i for i, b in enumerate(lex_ids)}, set(relation), \
        {b: i for i, b in enumerate(definition)}, terms


def features(con, query: str, pool: int = POOL):
    order, lex_score, lex_rank, relation, def_rank, terms = candidates(con, query, pool)
    blocks = {b.id: b for b in load_blocks(con, order)}
    entities = set(_query_entities(query))
    lowered = {e.lower() for e in entities}
    top = max(lex_score.values()) if lex_score else 1.0
    per_file: Dict[str, List[int]] = {}
    for rank, b in enumerate(order):
        if b in blocks:
            per_file.setdefault(blocks[b].path, []).append(rank)
    rows, ids = [], []
    for rank, b in enumerate(order):
        blk = blocks.get(b)
        if blk is None:
            continue
        name_tail = (blk.name or "").split(".")[-1].split(" > ")[-1]
        path_parts = set(re.split(r"[/._-]", blk.path.lower()))
        kinds = [1.0 if blk.kind == k else 0.0 for k in KINDS]
        file_defs = sum(1 for r in per_file[blk.path] if order[r] in def_rank)
        rows.append([
            lex_score.get(b, 0.0) / top if top else 0.0,
            math.log1p(lex_rank.get(b, pool)),
            1.0 if b in lex_rank else 0.0,
            1.0 / (1 + def_rank[b]) if b in def_rank else 0.0,
            math.log1p(def_rank.get(b, pool)),
            1.0 if b in def_rank else 0.0,
            1.0 if b in relation else 0.0,
            math.log1p(rank),
            math.log1p(blk.tokens),
            1.0 if name_tail and name_tail in entities else 0.0,
            1.0 if path_parts & lowered else 0.0,
            math.log1p(len(per_file[blk.path])),
            math.log1p(min(per_file[blk.path])),
            math.log1p(file_defs),
            math.log1p(len(terms)),
            math.log1p(len(entities)),
            *kinds, *_role(blk.path),
        ])
        ids.append(blk)
    return ids, rows


def _labels(blocks, task) -> List[int]:
    return [1 if any(h.found_by([(b.path, b.start_line, b.end_line)]) for h in task.hunks) else 0 for b in blocks]


def dataset(split: str, targets: Sequence[str] = ("fix", "tests")):
    """Per task: blocks, feature rows, labels per target."""
    tasks = data.split(split)
    by_target = {t: {x.instance_id: x for x in data.split(f"{split}:{t}")} for t in targets if t != "fix"}
    out = []
    for task in tasks:
        pack = packs.pack_path(task)
        if not pack.exists():
            continue
        with open_pack(pack) as con:
            blocks, rows = features(con, task.query)
        labels = {"fix": _labels(blocks, task)}
        for t, mapping in by_target.items():
            if task.instance_id in mapping:
                labels[t] = _labels(blocks, mapping[task.instance_id])
        out.append({"task": task, "blocks": blocks, "rows": rows, "labels": labels})
    return out


def _standardize(items):
    import numpy as np
    X = np.array([r for it in items for r in it["rows"]], dtype=float)
    mean, std = X.mean(axis=0), X.std(axis=0)
    std[std == 0] = 1.0
    return mean, std


#: Features that encode a file's role or a role proxy (text files are
#: "section"/"chunk" blocks). A role-blind model may not use them, so any gain
#: it shows must come from ranking evidence rather than role preferences.
ROLE_FEATURES = {"role_test", "role_doc", "role_example"} | {f"kind_{k}" for k in KINDS}


def train(items, *, l2: float = 1.0, epochs: int = 300, lr: float = 0.5, targets=("fix", "tests"),
          role_blind: bool = False):
    """Pairwise logistic loss; each (query, target) contributes equal weight."""
    import numpy as np
    mean, std = _standardize(items)
    mask = np.array([0.0 if (role_blind and f in ROLE_FEATURES) else 1.0 for f in FEATURES])
    diffs, weights = [], []
    for it in items:
        X = (np.array(it["rows"], dtype=float) - mean) / std * mask
        for target in targets:
            y = it["labels"].get(target)
            if not y or not any(y) or all(y):
                continue
            pos = [i for i, v in enumerate(y) if v]
            neg = [i for i, v in enumerate(y) if not v]
            d = (X[pos][:, None, :] - X[neg][None, :, :]).reshape(-1, X.shape[1])
            diffs.append(d)
            weights.append(np.full(len(d), 1.0 / len(d)))
    D = np.vstack(diffs)
    W = np.concatenate(weights)
    W = W / W.sum()
    w = np.zeros(D.shape[1])
    for _ in range(epochs):
        margin = D @ w
        p = 1.0 / (1.0 + np.exp(np.clip(margin, -30, 30)))
        grad = -(D * (W * p)[:, None]).sum(axis=0) + l2 * w / len(items)
        w -= lr * grad
    w = w * mask
    return {"features": FEATURES, "mean": mean.tolist(), "std": std.tolist(), "weights": w.tolist(),
            "l2": l2, "epochs": epochs, "pairs": int(len(D)), "queries": len(items),
            "targets": list(targets), "role_blind": role_blind}


def score_rows(model, rows):
    import numpy as np
    X = (np.array(rows, dtype=float) - np.array(model["mean"])) / np.array(model["std"])
    return X @ np.array(model["weights"])


def rerank(model, blocks, rows):
    if not rows:
        return []
    s = score_rows(model, rows)
    return [blocks[i] for i in sorted(range(len(blocks)), key=lambda i: (-s[i], i))]


def recall_at(items, model, budgets=(512, 1024, 2048, 4096), target="fix"):
    """Greedy whole-block fill of the re-ranked pool (no trimming)."""
    out = {b: [] for b in budgets}
    for it in items:
        task_hunks = it["labels"].get(target)
        if task_hunks is None:
            continue
        ordered = rerank(model, it["blocks"], it["rows"]) if model else it["blocks"]
        labels = {b.id: label for b, label in zip(it["blocks"], task_hunks)}
        for budget in budgets:
            used, n, hit = 0, 0, 0
            for b in ordered:
                extra = len(b.text) + (2 if n else 0)
                if max(1, (used + extra) // 4) > budget:
                    continue
                used, n = used + extra, n + 1
                hit |= labels[b.id]
            out[budget].append(hit)
    return {b: round(sum(v) / len(v), 4) for b, v in out.items() if v}


def cv(split: str, **kw):
    items = dataset(split)
    repos = sorted({it["task"].repo for it in items})
    folds = {}
    for repo in repos:
        train_items = [it for it in items if it["task"].repo != repo]
        test_items = [it for it in items if it["task"].repo == repo]
        model = train(train_items, **kw)
        folds[repo] = (test_items, model)
    result = {}
    for target in ("fix", "tests"):
        pooled_base = {b: [] for b in (512, 1024, 2048, 4096)}
        pooled_ltr = {b: [] for b in (512, 1024, 2048, 4096)}
        for repo, (test_items, model) in folds.items():
            for it in test_items:
                y = it["labels"].get(target)
                if y is None:
                    continue
                for label, m, pooled in (("base", None, pooled_base), ("ltr", model, pooled_ltr)):
                    r = recall_at([it], m, target=target)
                    for b, v in r.items():
                        pooled[b].append(v)
        result[target] = {"base_any_gold_block": {b: round(sum(v) / len(v), 4) for b, v in pooled_base.items()},
                          "ltr_any_gold_block": {b: round(sum(v) / len(v), 4) for b, v in pooled_ltr.items()}}
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("cv", "train"))
    parser.add_argument("--split", default="dev-fast")
    parser.add_argument("--l2", type=float, default=1.0)
    parser.add_argument("--targets", default="fix,tests")
    parser.add_argument("--role-blind", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    kw = {"l2": args.l2, "targets": tuple(args.targets.split(",")), "role_blind": args.role_blind}
    if args.command == "cv":
        print(json.dumps(cv(args.split, **kw), indent=1))
    else:
        model = train(dataset(args.split), **kw)
        model["trained_on"] = args.split
        args.out.write_text(json.dumps(model, indent=1))
        print(json.dumps({k: v for k, v in model.items() if k not in ("mean", "std")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

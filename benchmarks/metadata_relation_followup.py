"""Test a native-style raises channel on top of fielded FTS retrieval.

This is a challenger experiment. It uses the frozen side index only to avoid a
format migration before the ranking rule has earned promotion.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import random
import re
import sqlite3
import sys
from unittest.mock import patch

from benchmarks import seed_metadata
from benchmarks.rival_reproduction import attributed_context, retention
from npk.pack import LocalTokenizer, PackSelector, verify
from npk.pack.format import load_blocks, open_pack


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "experiments/runs/packs"
ARMS = ("fields60", "fields_relation_rrf", "fields_relation_prepend")
ACTION_WORDS = frozenset("raise raises raised raising throw throws thrown".split())
BLOCKERS = frozenset("""not no never neither nor without cannot
avoid avoids avoided avoiding prevent prevents prevented preventing
catch catches caught catching handle handles handled handling
suppress suppresses suppressed suppressing
mention mentions mentioned mentioning literal literals string strings""".split())
SURFACE = re.compile(r"(?<!\w)[^\W\d]\w*(?:\.[^\W\d]\w*)*(?!\w)", re.UNICODE)
CONTRACTION = re.compile(r"\b\w+n['\u2019]t\b", re.IGNORECASE)
RRF_K = 60


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _surface(query):
    whole = {m.group(0).lower() for m in SURFACE.finditer(query)}
    return whole, whole | {part for item in whole for part in item.split(".")}


def relation_candidates(side, query, limit):
    """Return selectively matched raise sites under the conservative guard."""
    whole, names = _surface(query)
    if not whole.intersection(ACTION_WORDS):
        return []
    if whole.intersection(BLOCKERS) or CONTRACTION.search(query):
        return []
    known = {row[0] for row in side.execute(
        "SELECT DISTINCT name FROM relations WHERE kind='raises'"
    )}
    arguments = sorted((names & known) - ACTION_WORDS)
    if not arguments:
        return []
    total = side.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    cap = max(1, int(total * 0.02))
    marks = ",".join("?" * len(arguments))
    rows = side.execute(
        "SELECT DISTINCT r.block_id,f.path,b.ordinal "
        "FROM relations r JOIN blocks b ON b.id=r.block_id "
        "JOIN files f ON f.id=b.file_id "
        f"WHERE r.kind='raises' AND r.name IN ({marks}) "
        "AND (SELECT COUNT(DISTINCT x.block_id) FROM relations x "
        "     WHERE x.kind=r.kind AND x.name=r.name)<=?",
        (*arguments, cap),
    ).fetchall()
    packages = {row[0].split("/", 1)[0].lower()
                for row in side.execute("SELECT path FROM files")}
    scope = names & packages
    rows.sort(key=lambda row: (
        bool(scope) and row["path"].split("/", 1)[0].lower() not in scope,
        row["path"], row["ordinal"], row["block_id"],
    ))
    return [row["block_id"] for row in rows[:limit]]


def rrf_merge(*channels):
    scores = {}
    for ordered in channels:
        for rank, block_id in enumerate(ordered):
            scores[block_id] = scores.get(block_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda block_id: -scores[block_id])


def prepend(primary, fallback):
    return list(dict.fromkeys([*primary, *fallback]))


def run(parent, output):
    output.mkdir(parents=True, exist_ok=False)
    parent_plan_path = parent / "plan.json"
    parent_results_path = parent / "results.json"
    parent_plan = json.loads(parent_plan_path.read_text(encoding="utf-8"))
    parent_results = json.loads(parent_results_path.read_text(encoding="utf-8"))
    assert parent_results["status"] == "AUDITED"
    assert parent_results["plan_sha256"] == sha(parent_plan_path)
    champion = parent / "champion.npk"
    assert sha(champion) == parent_plan["inputs"][str(champion.relative_to(ROOT))]
    assert verify(champion)["ok"]
    side_path = PACKS / "cycle28-seed-metadata-v1/features.sqlite"
    old_plan = json.loads(
        (PACKS / "cycle28-seed-metadata-v1/plan.json").read_text(encoding="utf-8")
    )
    asset = PACKS / "cycle28-nim-tokenizer-v1/tokenizer.json"
    assert sha(side_path) == old_plan["side_sha256"]
    assert sha(asset) == old_plan["asset_sha256"]
    tasks = parent_plan["tasks"]
    groups = defaultdict(list)
    for task in tasks:
        groups[task["query"]].append(task)
    budgets = tuple(parent_plan["budgets"])
    source_paths = [
        *sorted((ROOT / "npk").rglob("*.py")),
        Path(__file__),
        ROOT / "benchmarks/seed_metadata.py",
        ROOT / "benchmarks/rival_reproduction.py",
    ]
    plan = {
        "evidence_mode": "LOCAL",
        "generative_calls": 0,
        "arms": ARMS,
        "budgets": budgets,
        "tasks": tasks,
        "distinct_queries": len(groups),
        "parent_plan_sha256": sha(parent_plan_path),
        "parent_results_sha256": sha(parent_results_path),
        "inputs": {
            str(path.relative_to(ROOT)): sha(path)
            for path in (champion, side_path, asset)
        },
        "sources": {
            str(path.relative_to(ROOT)): sha(path) for path in source_paths
        },
        "policy": {
            "action_words": sorted(ACTION_WORDS),
            "blockers": sorted(BLOCKERS),
            "maximum_relation_df_fraction": 0.02,
            "fusion": "equal reciprocal rank with k=60",
        },
        "limitations": [
            "Inspected development annotations; not target answer accuracy",
            "Only syntactic Python raise sites are indexed; they are seeds, not behavior proof",
            "The conservative whole-word guard can suppress valid mixed-clause questions",
            "Source spans and exact NVIDIA context caps are checked independently",
            "The side index avoids a product migration until the challenger earns it",
        ],
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    tokenizer = LocalTokenizer(asset, cache_bytes=16 * 1024 * 1024)
    with open_pack(champion) as con:
        blocks = {block.id: block for block in load_blocks(con)}
    module = importlib.import_module("npk.pack.select")
    rows = []
    with ExitStack() as stack:
        side = sqlite3.connect(side_path.resolve().as_uri() + "?mode=ro", uri=True)
        stack.callback(side.close)
        side.row_factory = sqlite3.Row
        selectors = {
            arm: stack.enter_context(PackSelector(
                champion, tokenizer=tokenizer, candidate_limit=60, enable_cache=False
            ))
            for arm in ARMS
        }
        queries = sorted(groups)
        random.Random(3621).shuffle(queries)
        relation_queries = 0
        for qi, query in enumerate(queries):
            fields = seed_metadata.field_rank(side, query, 60, mode="fields")
            relations = relation_candidates(side, query, 60)
            relation_queries += bool(relations)
            ranks = {
                "fields60": fields,
                "fields_relation_rrf": rrf_merge(fields, relations),
                "fields_relation_prepend": prepend(relations, fields),
            }
            order = list(ARMS)
            random.Random(3621 + qi).shuffle(order)
            for arm in order:
                def rank(_con, q, limit):
                    assert q == query and limit == 60
                    return ranks[arm]

                with patch.object(module, "_lexical_channel", rank):
                    for budget in budgets:
                        result = selectors[arm].select(query, budget_tokens=budget)
                        emitted = result.context_text()
                        recounted = len(tokenizer._backend.encode(
                            emitted, add_special_tokens=False
                        ).ids) if emitted else 0
                        assert recounted == result.total_tokens <= budget
                        evidence = [asdict(item) for item in result.evidence]
                        for item in evidence:
                            original = blocks[item["block_id"]]
                            assert (item["path"], item["span"], item["text"]) == (
                                original.path, original.span, original.text
                            )
                        hits = [
                            task["task_id"] for task in groups[query]
                            if retention(attributed_context(evidence, task), task["needles"])["strict_hit"]
                        ]
                        rows.append({
                            "query": query,
                            "arm": arm,
                            "budget": budget,
                            "hits": hits,
                            "selected_tokens": recounted,
                            "relation_candidates": relations,
                            "evidence": evidence,
                        })
            if qi % 40 == 0:
                print(json.dumps({"queries_done": qi + 1, "records": len(rows)}), flush=True)
    summary = []
    for budget in budgets:
        baseline = {
            task_id for row in rows
            if row["arm"] == "fields60" and row["budget"] == budget
            for task_id in row["hits"]
        }
        for arm in ARMS:
            hits = {
                task_id for row in rows
                if row["arm"] == arm and row["budget"] == budget
                for task_id in row["hits"]
            }
            summary.append({
                "arm": arm,
                "budget": budget,
                "hits": len(hits),
                "tasks": len(tasks),
                "gains_vs_fields": sorted(hits - baseline),
                "losses_vs_fields": sorted(baseline - hits),
            })
    for name, expected in plan["sources"].items():
        assert sha(ROOT / name) == expected, name
    result = {
        "status": "AUDITED",
        "selections": len(rows),
        "relation_queries": relation_queries,
        "summary": summary,
        "plan_sha256": sha(output / "plan.json"),
        "rows": rows,
    }
    (output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "selections": len(rows),
        "relation_queries": relation_queries,
        "summary": summary,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.parent.resolve(), args.output.resolve())

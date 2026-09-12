"""Isolate candidate-limit and field-separation effects for Cycle 36."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import random
import sqlite3
import sys
from unittest.mock import patch

from benchmarks import seed_metadata
from benchmarks.rival_reproduction import attributed_context, retention
from npk.pack import LocalTokenizer, PackSelector, verify
from npk.pack.format import load_blocks, open_pack


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "experiments/runs/packs"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(parent, output):
    output.mkdir(parents=True, exist_ok=False)
    parent_plan_path = parent / "plan.json"
    parent_results_path = parent / "results.json"
    parent_plan = json.loads(parent_plan_path.read_bytes())
    parent_results = json.loads(parent_results_path.read_bytes())
    assert parent_results["status"] == "AUDITED"
    assert parent_results["plan_sha256"] == sha(parent_plan_path)
    champion = parent / "champion.npk"
    prototype = parent / "prototype.npk"
    assert sha(champion) == parent_plan["inputs"][str(champion.relative_to(ROOT))]
    assert sha(prototype) == parent_plan["prototype_sha256"]
    for artifact in (champion, prototype):
        assert verify(artifact)["ok"]
    tasks = parent_plan["tasks"]
    groups = defaultdict(list)
    for task in tasks:
        groups[task["query"]].append(task)
    asset = PACKS / "cycle28-nim-tokenizer-v1/tokenizer.json"
    side_path = PACKS / "cycle28-seed-metadata-v1/features.sqlite"
    old_plan = json.loads((PACKS / "cycle28-seed-metadata-v1/plan.json").read_bytes())
    assert sha(asset) == old_plan["asset_sha256"]
    assert sha(side_path) == old_plan["side_sha256"]
    with open_pack(champion) as con:
        champion_blocks = {b.id: b for b in load_blocks(con)}
    with open_pack(prototype) as con:
        prototype_blocks = {b.id: b for b in load_blocks(con)}
    assert [(b.path, b.ordinal, b.text) for b in champion_blocks.values()] == [
        (b.path, b.ordinal, b.text) for b in prototype_blocks.values()]
    arms = ("header160", "fields60", "crisp_raises60")
    budgets = tuple(parent_plan["budgets"])
    source_paths = [*sorted((ROOT / "npk").rglob("*.py")), Path(__file__),
                    ROOT / "benchmarks/seed_metadata.py",
                    ROOT / "benchmarks/rival_reproduction.py"]
    plan = {
        "evidence_mode": "LOCAL", "generative_calls": 0, "arms": arms,
        "budgets": budgets, "tasks": tasks, "distinct_queries": len(groups),
        "parent_plan_sha256": sha(parent_plan_path),
        "parent_results_sha256": sha(parent_results_path),
        "inputs": {str(p.relative_to(ROOT)): sha(p) for p in
                   (champion, prototype, asset, side_path)},
        "sources": {str(p.relative_to(ROOT)): sha(p) for p in source_paths},
        "python": sys.version, "sqlite": sqlite3.sqlite_version,
        "limitations": ["Inspected development annotations; not target answer accuracy",
                        "Source spans and exact NVIDIA context caps are checked independently",
                        "This continuation isolates candidate-limit and field-separation effects",
                        "Parent body60 rows are immutable baseline evidence from the audited run"],
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    counter = LocalTokenizer(asset, cache_bytes=16 * 1024 * 1024)
    module = importlib.import_module("npk.pack.select")
    original_rank = module._lexical_channel
    rows = []
    with ExitStack() as stack:
        side = sqlite3.connect(side_path.resolve().as_uri() + "?mode=ro", uri=True)
        stack.callback(side.close)
        side.row_factory = sqlite3.Row
        snapshot = PACKS / "cycle28-crisp-snapshot-v1"
        sys.path.insert(0, str(snapshot))
        from crisp.score import Scorer
        scorer = Scorer(side)
        with open_pack(champion) as parent_pack:
            seed_metadata.require_parent(side, parent_pack)
        selectors = {
            "header160": stack.enter_context(PackSelector(
                prototype, tokenizer=counter, candidate_limit=160, enable_cache=False)),
            "fields60": stack.enter_context(PackSelector(
                champion, tokenizer=counter, candidate_limit=60, enable_cache=False)),
            "crisp_raises60": stack.enter_context(PackSelector(
                champion, tokenizer=counter, candidate_limit=60, enable_cache=False)),
        }
        queries = sorted(groups)
        random.Random(3611).shuffle(queries)
        for qi, query in enumerate(queries):
            order = list(arms)
            random.Random(3611 + qi).shuffle(order)
            for arm in order:
                def rank(con, q, limit):
                    if arm == "header160":
                        return original_rank(con, q, limit)
                    if arm == "fields60":
                        return seed_metadata.field_rank(side, q, limit, mode="fields")
                    return [bid for bid, _ in scorer.candidates(scorer.plan(q), limit)]
                with patch.object(module, "_lexical_channel", rank):
                    for budget in budgets:
                        result = selectors[arm].select(query, budget_tokens=budget)
                        emitted = result.context_text()
                        recounted = len(counter._backend.encode(
                            emitted, add_special_tokens=False).ids) if emitted else 0
                        assert recounted == result.total_tokens <= budget
                        evidence = [asdict(e) for e in result.evidence]
                        source = prototype_blocks if arm == "header160" else champion_blocks
                        for item in evidence:
                            b = source[item["block_id"]]
                            assert (item["path"], item["span"], item["text"]) == (
                                b.path, b.span, b.text)
                        hits = [task["task_id"] for task in groups[query]
                                if retention(attributed_context(evidence, task), task["needles"])["strict_hit"]]
                        rows.append({"query": query, "arm": arm, "budget": budget,
                                     "hits": hits, "selected_tokens": recounted,
                                     "seed_failed": result.seed_failed, "evidence": evidence})
            if qi % 40 == 0:
                print(json.dumps({"queries_done": qi + 1, "records": len(rows)}), flush=True)
    summary = []
    for budget in budgets:
        body_hits = {tid for row in parent_results["rows"]
                     if row["arm"] == "body60" and row["budget"] == budget
                     for tid in row["hits"]}
        for arm in arms:
            hits = {tid for row in rows if row["arm"] == arm and row["budget"] == budget
                    for tid in row["hits"]}
            summary.append({"arm": arm, "budget": budget, "hits": len(hits),
                            "tasks": len(tasks), "gains_vs_body": sorted(hits - body_hits),
                            "losses_vs_body": sorted(body_hits - hits)})
    for name, expected in plan["sources"].items():
        assert sha(ROOT / name) == expected, name
    result = {"status": "AUDITED", "selections": len(rows), "summary": summary,
              "plan_sha256": sha(output / "plan.json"), "rows": rows}
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"selections": len(rows), "summary": summary}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.parent.resolve(), args.output.resolve())

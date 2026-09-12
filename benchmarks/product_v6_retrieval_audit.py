"""Compile and audit the format-v6 field/relation challenger in product code."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import sys
import time
from unittest.mock import patch

from benchmarks.rival_reproduction import attributed_context, retention
from npk.pack import LocalTokenizer, PackSelector, compile_pack, verify
from npk.pack.format import load_blocks, open_pack


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "experiments/runs/packs"
ARMS = ("v6_fields", "v6_fields_relations")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(root):
    return {
        path.relative_to(root).as_posix(): sha(path)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def old_blocks(path):
    con = sqlite3.connect(path)
    try:
        return [tuple(row) for row in con.execute(
            "SELECT f.path,b.ordinal,b.kind,b.name,b.start_line,b.end_line,b.text "
            "FROM blocks b JOIN files f ON f.id=b.file_id "
            "ORDER BY f.path,b.ordinal"
        )]
    finally:
        con.close()


def run(parent, relation_run, output):
    output.mkdir(parents=True, exist_ok=False)
    source = PACKS / "cycle28-crisp-snapshot-v1/corpus/test_src"
    asset = PACKS / "cycle28-nim-tokenizer-v1/tokenizer.json"
    parent_plan_path = parent / "plan.json"
    parent_results_path = parent / "results.json"
    parent_plan = json.loads(parent_plan_path.read_text(encoding="utf-8"))
    parent_results = json.loads(parent_results_path.read_text(encoding="utf-8"))
    relation_plan_path = relation_run / "plan.json"
    relation_results_path = relation_run / "results.json"
    relation_plan = json.loads(relation_plan_path.read_text(encoding="utf-8"))
    relation_results = json.loads(relation_results_path.read_text(encoding="utf-8"))
    assert parent_results["status"] == relation_results["status"] == "AUDITED"
    assert parent_results["plan_sha256"] == sha(parent_plan_path)
    assert relation_results["plan_sha256"] == sha(relation_plan_path)
    old = parent / "champion.npk"
    assert sha(old) == parent_plan["inputs"][str(old.relative_to(ROOT))]
    old_asset_plan = json.loads(
        (PACKS / "cycle28-seed-metadata-v1/plan.json").read_text(encoding="utf-8")
    )
    assert sha(asset) == old_asset_plan["asset_sha256"]
    source_before = source_hashes(source)
    artifact = output / "challenger.npk"
    started = time.perf_counter_ns()
    compile_stats = compile_pack(source, artifact, python_members=True).as_dict()
    compile_ms = (time.perf_counter_ns() - started) / 1e6
    checked = verify(artifact)
    assert checked["ok"], checked["errors"]
    with open_pack(artifact) as con:
        current_blocks = [
            (block.path, block.ordinal, block.kind, block.name,
             block.start_line, block.end_line, block.text)
            for block in load_blocks(con)
        ]
        counts = {
            "files": con.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "blocks": con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0],
            "relations": con.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
            "lexical": con.execute("SELECT COUNT(*) FROM lexical").fetchone()[0],
        }
    assert current_blocks == old_blocks(old)
    assert counts["blocks"] == counts["lexical"]
    tasks = parent_plan["tasks"]
    groups = defaultdict(list)
    for task in tasks:
        groups[task["query"]].append(task)
    budgets = tuple(parent_plan["budgets"])
    code_paths = [*sorted((ROOT / "npk").rglob("*.py")), Path(__file__)]
    plan = {
        "evidence_mode": "LOCAL",
        "generative_calls": 0,
        "arms": ARMS,
        "budgets": budgets,
        "tasks": tasks,
        "distinct_queries": len(groups),
        "parent_plan_sha256": sha(parent_plan_path),
        "parent_results_sha256": sha(parent_results_path),
        "relation_plan_sha256": sha(relation_plan_path),
        "relation_results_sha256": sha(relation_results_path),
        "inputs": {
            str(old.relative_to(ROOT)): sha(old),
            str(asset.relative_to(ROOT)): sha(asset),
        },
        "source_corpus": source_before,
        "sources": {str(path.relative_to(ROOT)): sha(path) for path in code_paths},
        "artifact_sha256": sha(artifact),
        "compile": {**compile_stats, "wall_ms": compile_ms},
        "counts": counts,
        "old_size_bytes": old.stat().st_size,
        "v6_size_bytes": artifact.stat().st_size,
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "limitations": [
            "Inspected development annotations; not target answer accuracy",
            "Source blocks are byte/span identical to the immutable format-v5 parent",
            "Exact NVIDIA token caps are independently recounted for every context",
            "The optimization and runtime make no generative calls and network is blocked",
        ],
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    tokenizer = LocalTokenizer(asset, cache_bytes=16 * 1024 * 1024)
    with open_pack(artifact) as con:
        blocks = {block.id: block for block in load_blocks(con)}
    rows = []
    with ExitStack() as stack:
        selectors = {
            "v6_fields": stack.enter_context(PackSelector(
                artifact, tokenizer=tokenizer, enable_relations=False, enable_cache=False
            )),
            "v6_fields_relations": stack.enter_context(PackSelector(
                artifact, tokenizer=tokenizer, enable_relations=True, enable_cache=False
            )),
        }
        queries = sorted(groups)
        random.Random(3631).shuffle(queries)
        with patch("socket.socket.connect", side_effect=AssertionError("unexpected network")):
            for qi, query in enumerate(queries):
                order = list(ARMS)
                random.Random(3631 + qi).shuffle(order)
                for arm in order:
                    for budget in budgets:
                        result = selectors[arm].select(query, budget_tokens=budget)
                        emitted = result.context_text()
                        recounted = len(tokenizer._backend.encode(
                            emitted, add_special_tokens=False
                        ).ids) if emitted else 0
                        assert recounted == result.total_tokens <= budget
                        assert not result.used_generative_llm
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
                            "channels_used": result.channels_used,
                            "evidence": evidence,
                        })
                if qi % 40 == 0:
                    print(json.dumps({"queries_done": qi + 1, "records": len(rows)}), flush=True)
    side_rows = {
        (row["query"], row["budget"], row["arm"]): row
        for row in relation_results["rows"]
    }
    summary = []
    for budget in budgets:
        body = {
            task_id for row in parent_results["rows"]
            if row["arm"] == "body60" and row["budget"] == budget
            for task_id in row["hits"]
        }
        for arm in ARMS:
            selected = [row for row in rows if row["arm"] == arm and row["budget"] == budget]
            hits = {task_id for row in selected for task_id in row["hits"]}
            side_arm = "fields60" if arm == "v6_fields" else "fields_relation_rrf"
            exact_side_contexts = sum(
                [item["block_id"] for item in row["evidence"]]
                == [item["block_id"] for item in side_rows[row["query"], budget, side_arm]["evidence"]]
                for row in selected
            )
            summary.append({
                "arm": arm,
                "budget": budget,
                "hits": len(hits),
                "tasks": len(tasks),
                "gains_vs_body": sorted(hits - body),
                "losses_vs_body": sorted(body - hits),
                "exact_side_contexts": exact_side_contexts,
                "contexts": len(selected),
            })
    assert source_hashes(source) == source_before
    for name, expected in plan["sources"].items():
        assert sha(ROOT / name) == expected, name
    result = {
        "status": "AUDITED",
        "selections": len(rows),
        "summary": summary,
        "plan_sha256": sha(output / "plan.json"),
        "rows": rows,
    }
    (output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "selections": len(rows),
        "compile": plan["compile"],
        "counts": counts,
        "size_ratio_v6_over_v5": artifact.stat().st_size / old.stat().st_size,
        "summary": summary,
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--relation-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.parent.resolve(), args.relation_run.resolve(), args.output.resolve())

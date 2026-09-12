"""Compare the actual Cycle 36 prototype against fixed annotated controls.

No API calls or model answers. These are inspected development source-retention
annotations. More selected blocks is deliberately not a quality metric.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import random
import sqlite3
import sys
import time
from unittest.mock import patch
import zipfile

from benchmarks import seed_metadata
from benchmarks.rival_reproduction import attributed_context, retention
from npk.pack import LocalTokenizer, PackSelector, verify
from npk.pack.format import load_blocks, open_pack


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "experiments/runs/packs"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def captured_compiler(path):
    name = "npk.pack._cycle36_header_compiler"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def run(output, compiler_capture):
    output.mkdir(parents=True, exist_ok=False)
    snapshot = PACKS / "cycle28-crisp-snapshot-v1"
    metadata = PACKS / "cycle28-seed-metadata-v1"
    source = snapshot / "corpus/test_src"
    plan_bytes = (metadata / "plan.json").read_bytes()
    old_plan = json.loads(plan_bytes)
    archive = ROOT / "experiments/results/cycle28-seed-checkpoint.zip"
    champion = output / "champion.npk"
    member = "experiments/runs/packs/cycle28-local-budget-v2/compiled.npk"
    with zipfile.ZipFile(archive) as stream:
        body = stream.read(member)
    assert hashlib.sha256(body).hexdigest() == old_plan["pack_sha256"]
    champion.write_bytes(body)
    asset = PACKS / "cycle28-nim-tokenizer-v1/tokenizer.json"
    feature_index = metadata / "features.sqlite"
    assert digest(champion) == old_plan["pack_sha256"]
    assert digest(asset) == old_plan["asset_sha256"]
    assert digest(feature_index) == old_plan["side_sha256"]
    tasks = old_plan["tasks"]
    groups = defaultdict(list)
    for task in tasks:
        groups[task["query"]].append(task)
        lo, hi = map(int, task["span"].rsplit(":", 1)[1].split("-"))
        body = (source / task["path"]).read_text(encoding="utf-8")
        assert retention("\n".join(body.split("\n")[lo - 1:hi]), task["needles"])["strict_hit"]
    frozen = json.loads((snapshot / "snapshot.json").read_bytes())
    for name, meta in frozen["files"].items():
        assert digest(snapshot / name) == meta["sha256"], name
    counter = LocalTokenizer(asset, cache_bytes=16 * 1024 * 1024)
    compiler = captured_compiler(compiler_capture)
    prototype = output / "prototype.npk"
    started = time.perf_counter()
    built = compiler.compile_pack(source, prototype, python_members=True)
    elapsed = time.perf_counter() - started
    for pack in (champion, prototype):
        assert verify(pack)["ok"], str(pack)
    with open_pack(champion) as con:
        blocks = load_blocks(con)
        originals = [(b.path, b.ordinal, b.text, b.span) for b in blocks]
    with open_pack(prototype) as con:
        after = load_blocks(con)
        assert originals == [(b.path, b.ordinal, b.text, b.span) for b in after]
        current = {b.id: b for b in after}
        # Check full header presence without weakening source identity.
        assert all(row["content"].endswith("\n" + current[row["block_id"]].text)
                   for row in con.execute("SELECT block_id,content FROM lexical"))
    sys.path.insert(0, str(snapshot))
    from crisp.score import Scorer
    module = importlib.import_module("npk.pack.select")
    original_rank = module._lexical_channel
    arms = ("body60", "header60", "fields160", "crisp_raises160")
    budgets = (512, 2048, 8192)
    plan = {
        "evidence_mode": "LOCAL", "generative_calls": 0, "arms": arms, "budgets": budgets,
        "tasks": tasks, "distinct_queries": len(groups),
        "inputs": {str(p.relative_to(ROOT)): digest(p) for p in
                   (champion, archive, asset, feature_index, snapshot / "snapshot.json", compiler_capture)},
        "champion_archive_member": member,
        "sources": {str(p.relative_to(ROOT)): digest(p) for p in
                    [*sorted((ROOT / "npk").rglob("*.py")), Path(__file__),
                     ROOT / "benchmarks/seed_metadata.py", ROOT / "benchmarks/rival_reproduction.py"]},
        "prototype_compile_seconds": elapsed, "prototype_compile_stats": built.as_dict(),
        "prototype_sha256": digest(prototype), "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "limitations": ["Inspected development annotations; not target answer accuracy",
                        "Same literal blocks and exact NVIDIA context caps in every arm",
                        "The fields and CRISP controls use 160 candidates, as in the frozen comparison",
                        "Shared token count cache; selection timings are not latency promotion evidence"],
    }
    (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    rows = []
    with ExitStack() as stack:
        side = sqlite3.connect(feature_index.resolve().as_uri() + "?mode=ro", uri=True)
        stack.callback(side.close)
        side.row_factory = sqlite3.Row
        scorer = Scorer(side)
        with open_pack(champion) as parent:
            seed_metadata.require_parent(side, parent)
        selectors = {arm: stack.enter_context(PackSelector(
            prototype if arm == "header60" else champion,
            tokenizer=counter, candidate_limit=60 if arm.endswith("60") else 160,
            enable_cache=False)) for arm in arms}
        rng = random.Random(3607)
        questions = sorted(groups)
        rng.shuffle(questions)
        for qi, query in enumerate(questions):
            order = list(arms)
            rng.shuffle(order)
            for arm in order:
                def rank(con, q, limit):
                    if arm in ("body60", "header60"):
                        return original_rank(con, q, limit)
                    if arm == "fields160":
                        return seed_metadata.field_rank(side, q, limit, mode="fields")
                    return [bid for bid, _ in scorer.candidates(scorer.plan(q), limit)]
                with patch.object(module, "_lexical_channel", rank):
                    for budget in budgets:
                        result = selectors[arm].select(query, budget_tokens=budget)
                        emitted = result.context_text()
                        # Independent recount (no count-cache reuse).
                        recounted = len(counter._backend.encode(emitted, add_special_tokens=False).ids) if emitted else 0
                        assert recounted == result.total_tokens <= budget
                        evidence = [asdict(e) for e in result.evidence]
                        reference = current if arm == "header60" else {b.id: b for b in blocks}
                        for item in evidence:
                            b = reference[item["block_id"]]
                            assert (item["path"], item["span"], item["text"]) == (b.path, b.span, b.text)
                        hit_ids = [task["task_id"] for task in groups[query]
                                   if retention(attributed_context(evidence, task), task["needles"])["strict_hit"]]
                        rows.append({"query": query, "arm": arm, "budget": budget, "hits": hit_ids,
                                     "selected_tokens": recounted, "seed_failed": result.seed_failed,
                                     "evidence": evidence})
            if qi % 40 == 0:
                print(json.dumps({"queries_done": qi + 1, "records": len(rows)}), flush=True)
    summary = []
    for budget in budgets:
        body_hits = {tid for row in rows if row["arm"] == "body60" and row["budget"] == budget for tid in row["hits"]}
        for arm in arms:
            hits = {tid for row in rows if row["arm"] == arm and row["budget"] == budget for tid in row["hits"]}
            summary.append({"arm": arm, "budget": budget, "hits": len(hits), "tasks": len(tasks),
                            "gains_vs_body": sorted(hits - body_hits), "losses_vs_body": sorted(body_hits - hits)})
    for name, expected in plan["sources"].items():
        assert digest(ROOT / name) == expected, f"source changed: {name}"
    result = {"status": "AUDITED", "selections": len(rows), "summary": summary,
              "plan_sha256": digest(output / "plan.json"), "rows": rows}
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"selections": len(rows), "summary": summary}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler-capture", type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.compiler_capture.resolve())

"""Paired public-runtime diagnostics on one path-preserving compiled corpus.

This is LOCAL evidence retention, never answer accuracy or a sealed test. The
task templates were inspected and tuned previously. All methods see the same
artifact, budget and sources. Matches must occur in the named source files;
finding the same number in an unrelated library no longer earns a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import inspect
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(args):
    # Run the SAME worker against the committed champion or current worktree.
    # Package resolution is explicit; no monkeypatching of production selection.
    sys.path.insert(0, str(Path(args.implementation).resolve()))
    from npk.pack import PackSelector, compile_pack
    from npk.pack.compile import estimate_tokens
    from npk.pack.format import open_pack, load_blocks
    from npk.pack.select import _lexical_channel

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    started = time.perf_counter()
    stats = compile_pack(args.corpus, args.pack, mode=args.mode)
    compile_seconds = time.perf_counter() - started
    with open_pack(args.pack) as con:
        blocks = load_blocks(con)
    available_text = "\n\n".join(b.text for b in blocks)
    available_tokens = estimate_tokens(available_text)

    # A metadata label must not stand in for actual model availability.
    if args.mode == "semantic" and stats.embedded == 0:
        raise RuntimeError("semantic evaluation requested but no local encoder index was built")
    methods = ["neuralpack", "fused_seeds", "bm25"]
    selectors = {
        "neuralpack": PackSelector(args.pack),
        "fused_seeds": PackSelector(args.pack, resolve_conflicts=False,
                                     enable_dependency_expansion=False,
                                     **({"retrieval": "hybrid"} if "retrieval" in inspect.signature(PackSelector).parameters else {})),
    }
    rows = []
    for budget in args.budgets:
        for case_index, case in enumerate(cases):
            # Rotate method order to avoid always giving one method a warm cache.
            order = methods[case_index % len(methods):] + methods[:case_index % len(methods)]
            for method in order:
                started = time.perf_counter()
                if method == "bm25":
                    with open_pack(args.pack) as con:
                        ids = _lexical_channel(con, case["query"], 60)
                        candidates = {b.id: b for b in load_blocks(con, ids)}
                    evidence = []
                    for bid in ids:
                        block = candidates[bid]
                        text = "\n\n".join(b.text for b in evidence + [block])
                        if estimate_tokens(text) <= budget:
                            evidence.append(block)
                    reported_tokens = estimate_tokens("\n\n".join(b.text for b in evidence)) if evidence else 0
                    failed = not evidence
                else:
                    selected = selectors[method].select(case["query"], budget_tokens=budget)
                    evidence = selected.evidence
                    reported_tokens = selected.total_tokens
                    failed = selected.seed_failed
                latency_ms = (time.perf_counter() - started) * 1000
                text = "\n\n".join(b.text for b in evidence)
                actual_estimate = estimate_tokens(text) if evidence else 0
                required = set(case["required_paths"])
                relevant = "\n\n".join(b.text for b in evidence if b.path in required)
                # Every required file must be selected; positive values must occur
                # within those sources, not in arbitrary filler or another task.
                sources_complete = required <= {b.path for b in evidence}
                scoped_retention = sources_complete and all(g in relevant for g in case["gold"])
                rows.append({
                    "task_id": case["id"], "family": case["family"], "method": method,
                    "budget": budget, "available_tokens": available_tokens,
                    "selected_tokens": actual_estimate, "reported_tokens": reported_tokens,
                    "within_budget": actual_estimate <= budget, "seed_failed": failed,
                    "scoped_fixture_retention": scoped_retention,
                    "unscoped_gold_match": all(g in text for g in case["gold"]),
                    # Contradictory text can be useful for a comparison. This
                    # diagnostic is intentionally not folded into correctness.
                    "distractor_text_present": any(f in text for f in case["forbidden"]),
                    "latency_ms": latency_ms,
                    "evidence": [{"path": b.path, "span": b.span,
                                  "sha256": hashlib.sha256(b.text.encode()).hexdigest()}
                                 for b in evidence],
                })
    summary = []
    for budget in args.budgets:
        for method in methods:
            group = [r for r in rows if r["budget"] == budget and r["method"] == method]
            summary.append({"method": method, "budget": budget, "tasks": len(group),
                            "scoped_fixture_retention_pct": 100 * sum(r["scoped_fixture_retention"] for r in group) / len(group),
                            "budget_violations": sum(not r["within_budget"] for r in group),
                            "median_latency_ms": statistics.median(r["latency_ms"] for r in group),
                            "mean_selected_tokens": statistics.mean(r["selected_tokens"] for r in group)})
    result = {"evidence_mode": "LOCAL", "generative_api_calls": 0,
              "split_status": "reused_templates_diagnostic_only", "mode": args.mode,
              "compile_seconds": compile_seconds, "compile_stats": stats.as_dict(),
              "pack_bytes": Path(args.pack).stat().st_size, "summary": summary, "rows": rows}
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--implementation")
    parser.add_argument("--corpus")
    parser.add_argument("--cases")
    parser.add_argument("--pack")
    parser.add_argument("--output", required=True)
    parser.add_argument("--champion", default="2e39d69")
    parser.add_argument("--per-family", type=int, default=8)
    parser.add_argument("--filler-tokens", type=int, default=15000)
    parser.add_argument("--split", choices=["dev", "sealed", "all"], default="sealed")
    parser.add_argument("--mode", choices=["deterministic", "semantic"], default="deterministic")
    parser.add_argument("--budgets", nargs="+", type=int, default=[800, 1500, 3000])
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from benchmarks.tasks_hard import build_task_suite, assert_unambiguous
    from benchmarks.compiled_corpus import build_corpus, context_files

    tasks = [t for t in build_task_suite(per_family=args.per_family, filler_tokens=args.filler_tokens, corpus="real")
             if args.split == "all" or t.split == args.split]
    assert tasks
    assert_unambiguous(tasks)
    champion = subprocess.check_output(["git", "rev-parse", args.champion], cwd=repo, text=True).strip()
    archive = subprocess.check_output(["git", "archive", champion], cwd=repo)
    all_results = {"champion_commit": champion, "evidence_mode": "LOCAL", "mode": args.mode,
                   "limitations": ["Previously inspected synthetic task templates with real-library filler",
                                   "Template observations are correlated; no independent significance claim",
                                   "No target-model answers or dollar costs measured"],
                   "token_estimator": "floor(chars/4), separators included; not provider tokenizer usage"}
    with tempfile.TemporaryDirectory(prefix="npk-validation-") as tmp:
        work = Path(tmp)
        champion_path = work / "champion"
        champion_path.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(champion_path, filter="data")
        corpus = build_corpus(work, tasks)
        cases = []
        for task in tasks:
            files = context_files(task.context)
            names = task.required_blocks if all(n in files for n in task.required_blocks) else list(files)
            cases.append({"id": task.id, "family": task.family, "query": task.query,
                          "gold": task.gold, "forbidden": task.forbidden,
                          "required_paths": [f"{task.id}/{n}" for n in names]})
        case_path = work / "cases.json"
        case_path.write_text(json.dumps(cases), encoding="utf-8")
        all_results["cases"] = cases
        all_results["corpus_manifest"] = [{"path": p.relative_to(corpus).as_posix(), "sha256": digest(p),
                                            "bytes": p.stat().st_size} for p in sorted(corpus.rglob("*")) if p.is_file()]
        all_results["candidate_source_hashes"] = {p.relative_to(repo).as_posix(): digest(p)
                                                  for p in sorted((repo / "npk").rglob("*.py"))}
        all_results["harness_source_hashes"] = {p.relative_to(repo).as_posix(): digest(p)
                                                for p in sorted((repo / "benchmarks").glob("*.py"))}
        for name, implementation in [("champion", champion_path), ("candidate", repo)]:
            output = work / f"{name}.json"
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--implementation", str(implementation),
                       "--corpus", str(corpus), "--cases", str(case_path), "--pack", str(work / f"{name}.npk"),
                       "--output", str(output), "--mode", args.mode, "--budgets", *map(str, args.budgets)]
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
            # Shared installed model cache, without copying weights into snapshots.
            env["HF_HUB_CACHE"] = str(repo / "experiments/models/hf_cache")
            subprocess.run(command, cwd=implementation, env=env, check=True)
            result = json.loads(output.read_text(encoding="utf-8"))
            all_results[name] = result
            print(name, "compile_seconds", round(result["compile_seconds"], 3), flush=True)
            for row in result["summary"]:
                print(row, flush=True)
        for path, expected in all_results["candidate_source_hashes"].items():
            if digest(repo / path) != expected:
                raise RuntimeError(f"candidate changed during measurement: {path}")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(all_results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

"""Paired compile/update/query costs on actual installed public-library source.

LOCAL performance measurements only. No model calls or answer-quality metric.
Updates modify one file, 1% and 10% independently from the same baseline.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


def timed(function):
    started = time.perf_counter()
    result = function()
    return result, (time.perf_counter() - started) * 1000


def worker(args):
    sys.path.insert(0, str(Path(args.implementation).resolve()))
    from npk.pack import PackSelector, compile_pack, update_pack, verify
    from npk.pack.compile import estimate_tokens
    from npk.pack.format import open_pack, load_blocks
    rows = []
    for source in sorted(Path(args.corpus).iterdir()):
        if not source.is_dir():
            continue
        pack = Path(args.output).parent / (source.name + ".npk")
        options = {"python_members": True} if args.python_members else {}
        stats, compile_ms = timed(lambda: compile_pack(source, pack, **options))
        with open_pack(pack) as con:
            blocks = load_blocks(con)
        available = estimate_tokens("\n\n".join(b.text for b in blocks))
        # Use identical top-level names under class-window/member chunking.
        queries = sorted({b.name.split(".")[0] for b in blocks if b.name})[:10]
        if not queries:
            raise ValueError("performance corpus has no named code blocks")
        selector = PackSelector(pack)
        first, first_ms = timed(lambda: selector.select(queries[0], budget_tokens=1500))
        times, selected_counts = [], []
        for _ in range(4):
            for query in queries:
                selected, ms = timed(lambda: selector.select(query, budget_tokens=1500))
                times.append(ms)
                selected_counts.append(selected.total_tokens)
        checked, verify_ms = timed(lambda: verify(pack))
        if not checked["ok"]:
            raise RuntimeError("fresh compiled artifact failed verification")
        unchanged, noop_ms = timed(lambda: update_pack(pack, source))
        if unchanged.files_indexed or unchanged.files_removed:
            raise RuntimeError("unchanged update unexpectedly reindexed files")
        files = sorted(p for p in source.rglob("*") if p.is_file())
        updates = []
        for label, count in (("one_file", 1), ("one_percent", max(1, math.ceil(len(files)*.01))),
                             ("ten_percent", max(1, math.ceil(len(files)*.1)))):
            baseline = Path(str(pack) + ".baseline")
            shutil.copyfile(pack, baseline)
            originals = {p: p.read_bytes() for p in files[:count]}
            try:
                for p, body in originals.items():
                    p.write_bytes(body + b"\n# incremental profile edit\n")
                changed, update_ms = timed(lambda: update_pack(pack, source))
                if changed.files_indexed != count or not verify(pack)["ok"]:
                    raise RuntimeError("incremental update changed unexpected files or failed integrity")
                updates.append({"operation": label, "changed_files": count,
                                "changed_file_fraction":count/len(files), "update_ms": update_ms,
                                "stats": changed.as_dict()})
            finally:
                for p, body in originals.items():
                    p.write_bytes(body)
                shutil.copyfile(baseline, pack)
                baseline.unlink()
        import psutil
        memory = psutil.Process().memory_info()._asdict()
        rows.append({"requested_scale": source.name, "available_tokens": available,
                     "python_members":args.python_members,
                     "files": len(files), "blocks": stats.blocks, "pack_bytes": pack.stat().st_size,
                     "compile_ms": compile_ms, "verify_ms": verify_ms, "first_query_ms": first_ms,
                     "noop_update_ms": noop_ms, "dependency_index": stats.as_dict().get("dependency_index"),
                     "warm_median_ms": statistics.median(times), "warm_p95_ms": sorted(times)[math.ceil(len(times)*.95)-1],
                     "queries": queries, "samples": len(times), "mean_selected_tokens": statistics.mean(selected_counts),
                     "rss_bytes_after_queries": memory["rss"], "process_peak_bytes": memory.get("peak_wset"),
                     "updates": updates})
    Path(args.output).write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--implementation")
    parser.add_argument("--corpus")
    parser.add_argument("--output", required=True)
    parser.add_argument("--champion", default="cbf7c4f")
    parser.add_argument("--python-members",action="store_true",help="Enable experimental member chunks in the candidate only")
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from benchmarks.tasks_hard import real_corpus_blocks
    from benchmarks.compiled_corpus import build_corpus
    from types import SimpleNamespace
    champion = subprocess.check_output(["git", "rev-parse", args.champion], cwd=repo, text=True).strip()
    code_hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (repo / "npk").rglob("*.py")}
    results = {"evidence_mode": "LOCAL", "generative_api_calls": 0,
               "champion_commit": champion, "candidate_source_hashes": code_hashes,
               "limitations": ["One compilation per scale/arm; timing noise is not a speed guarantee",
                               "Query names are source-derived; this measures cost, not answer quality",
                               "Warm repeated queries; process memory includes Python and preceding scales",
                               "Compiler defaults are compared; dependency_index records policy when available"]}
    with tempfile.TemporaryDirectory(prefix="npk-scale-") as tmp:
        root = Path(tmp)
        tasks = [SimpleNamespace(id=f"scale_{size:07d}", context="\n\n".join(real_corpus_blocks(size, seed=97)))
                 for size in (2000,25000,50000,100000,250000)]
        corpus = build_corpus(root, tasks)
        results["source_manifest"] = [{"path": p.relative_to(corpus).as_posix(),
                                       "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
                                      for p in sorted(corpus.rglob("*")) if p.is_file()]
        old = root / "champion"
        old.mkdir()
        archive = subprocess.check_output(["git", "archive", champion], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old, filter="data")
        for name, implementation in (("champion",old), ("candidate",repo)):
            output = root / (name + ".json")
            flags=["--python-members"] if args.python_members and name=="candidate" else []
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--implementation", str(implementation),
                            "--corpus", str(corpus), "--output", str(output),*flags], cwd=implementation, check=True)
            results[name] = json.loads(output.read_text())
            print(name, [{k:r[k] for k in ("available_tokens","compile_ms","warm_median_ms","verify_ms","updates")}
                          for r in results[name]], flush=True)
        for path, expected in code_hashes.items():
            if hashlib.sha256((repo/path).read_bytes()).hexdigest() != expected:
                raise RuntimeError("candidate changed during scale profile")
    Path(args.output).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

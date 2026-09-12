"""Measure runtime hardening, module boundaries, and query throughput gains.

No generative calls. Paired measurements on local artifacts with independent
subprocesses for import isolation. OS caches are uncontrolled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import time

from npk.pack import compile_pack, PackSelector, verify
from npk.pack.format import connect, read_manifest, require_supported, open_pack
from npk.pack.compile import _available_tokens


def measure_import_boundaries(artifact_path):
    # Test in a fresh isolated subprocess
    code = (
        "import sys, json, time, pathlib\n"
        "t0 = time.perf_counter()\n"
        "from npk.pack import PackSelector\n"
        "t_import = (time.perf_counter() - t0) * 1000\n"
        "import_context_mods = [m for m in sys.modules if m.startswith('npk.context')]\n"
        f"selector = PackSelector(pathlib.Path({repr(str(artifact_path))}))\n"
        "t1 = time.perf_counter()\n"
        "res = selector.select('retry policy', budget_tokens=512)\n"
        "t_query = (time.perf_counter() - t1) * 1000\n"
        "query_context_mods = [m for m in sys.modules if m.startswith('npk.context')]\n"
        "print(json.dumps({'import_ms': t_import, 'first_query_ms': t_query, "
        "                  'import_context_mods': import_context_mods, "
        "                  'query_context_mods': query_context_mods}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def measure_query_throughput(artifact_path, queries, iterations=50):
    times_unmanaged = []
    for _ in range(iterations):
        for q in queries:
            t0 = time.perf_counter()
            PackSelector(artifact_path).select(q, budget_tokens=512)
            times_unmanaged.append((time.perf_counter() - t0) * 1000)

    times_managed = []
    with PackSelector(artifact_path) as selector:
        for _ in range(iterations):
            for q in queries:
                t0 = time.perf_counter()
                selector.select(q, budget_tokens=512)
                times_managed.append((time.perf_counter() - t0) * 1000)

    return {
        "unmanaged_median_ms": statistics.median(times_unmanaged),
        "managed_median_ms": statistics.median(times_managed),
        "speedup": statistics.median(times_unmanaged) / statistics.median(times_managed),
        "total_queries_measured": len(times_unmanaged),
    }


def measure_available_tokens(artifact_path, iterations=50):
    with open_pack(artifact_path) as con:
        t_py = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            count, chars = 0, 0
            for row in con.execute("SELECT text FROM blocks"):
                count += 1
                chars += len(row["text"])
            _ = max(1, (chars + max(0, count - 1) * 2) // 4) if count else 0
            t_py.append((time.perf_counter() - t0) * 1000)

        t_sql = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            _ = _available_tokens(con)
            t_sql.append((time.perf_counter() - t0) * 1000)

    return {
        "python_loop_median_ms": statistics.median(t_py),
        "sql_aggregate_median_ms": statistics.median(t_sql),
        "speedup": statistics.median(t_py) / statistics.median(t_sql),
    }


def verify_response_identity(artifact_path, queries, budgets=(512, 2048)):
    comparisons = 0
    with PackSelector(artifact_path) as managed_selector:
        for q in queries:
            for b in budgets:
                r1 = PackSelector(artifact_path).select(q, budget_tokens=b)
                r2 = managed_selector.select(q, budget_tokens=b)
                assert r1.context_text() == r2.context_text()
                assert r1.total_tokens == r2.total_tokens
                assert r1.seed_failed == r2.seed_failed
                assert r1.risk_band == r2.risk_band
                assert [e.span for e in r1.evidence] == [e.span for e in r2.evidence]
                comparisons += 1
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    assert verify(artifact)["ok"]

    queries = ["retry policy", "ExitStack", "callback", "process_data", "unknown_phrase",
               "parameter", "first", "command", "context", "option"]

    imports = measure_import_boundaries(artifact)
    throughput = measure_query_throughput(artifact, queries, iterations=20)
    tokens = measure_available_tokens(artifact, iterations=50)
    identities = verify_response_identity(artifact, queries)

    results = {
        "evidence_mode": "LOCAL",
        "generative_calls": 0,
        "status": "PASS",
        "artifact": str(artifact),
        "import_boundaries": imports,
        "query_throughput": throughput,
        "available_tokens_timing": tokens,
        "identical_response_checks": identities,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

"""Measure the cost of cache isolation repairs against captured Cycle 35 code."""
import argparse
import gc
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

from npk.pack import PackSelector, verify


ROOT = Path(__file__).resolve().parents[1]
QUERIES = ("retry policy", "ExitStack", "callback", "process_data", "RETRY_LIMIT",
           "parameter", "command", "context", "option", "runner")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def captured(path):
    name = "npk.pack._cycle36_cache_before"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module.PackSelector


def stable(result):
    row = result.as_dict()
    row.pop("latency_ms")
    return row


def measure(cls, artifact, *, rounds):
    selector = cls(artifact)
    hits = []
    misses = []
    with selector:
        for query in QUERIES:
            selector.clear_cache()
            begin = time.perf_counter_ns()
            result = selector.select(query, budget_tokens=2048)
            misses.append(time.perf_counter_ns() - begin)
            expected = stable(result)
            assert stable(selector.select(query, budget_tokens=2048)) == expected
        gc.disable()
        try:
            for round_number in range(rounds):
                for query in QUERIES:
                    begin = time.perf_counter_ns()
                    result = selector.select(query, budget_tokens=2048)
                    hits.append(time.perf_counter_ns() - begin)
                    if round_number == rounds - 1:
                        assert result.query == query
        finally:
            gc.enable()
    return {
        "miss_median_ms": statistics.median(misses) / 1e6,
        "hit_median_ms": statistics.median(hits) / 1e6,
        "hit_p95_ms": sorted(hits)[int(len(hits) * .95)] / 1e6,
        "hit_queries": len(hits),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=500)
    args = parser.parse_args()
    assert verify(args.artifact)["ok"]
    old = captured(args.before.resolve())
    with old(args.artifact, enable_cache=False) as before, PackSelector(
            args.artifact, enable_cache=False) as after:
        for query in QUERIES:
            assert stable(before.select(query, budget_tokens=2048)) == stable(
                after.select(query, budget_tokens=2048))
    # Alternate whole passes to reduce host-load bias.
    observations = {"before": [], "after": []}
    for _ in range(3):
        observations["after"].append(measure(PackSelector, args.artifact, rounds=args.rounds))
        observations["before"].append(measure(old, args.artifact, rounds=args.rounds))
    def middle(name):
        return {field: statistics.median(row[field] for row in observations[name])
                for field in ("miss_median_ms", "hit_median_ms", "hit_p95_ms")}
    result = {
        "status": "MEASURED", "evidence_mode": "LOCAL", "generative_calls": 0,
        "artifact_sha256": sha(args.artifact), "before_sha256": sha(args.before),
        "evaluator_sha256": sha(__file__), "python": sys.version,
        "queries": QUERIES, "rounds": args.rounds,
        "uncached_parity_queries": len(QUERIES),
        "observations": observations, "medians": {name: middle(name) for name in observations},
        "limitations": ["Warm managed-connection cache hits on one local artifact",
                        "Correctness attacks are separate regression tests",
                        "Wall time is sensitive to host load; three alternating passes reported"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

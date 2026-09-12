"""Measure artifact size and index cleanliness with language-aware symbol extraction.

Compares baseline symbol extraction against filtered symbol extraction
(excluding language keywords, stop words, and prose bare-word references).
No generative calls. Independent artifacts compiled from identical source.
"""
import argparse
import hashlib
import json
import keyword
from pathlib import Path
import re
import shutil
import sqlite3
import time

from npk.pack import compile_pack, PackSelector, verify
from npk.pack.format import connect, open_pack
import npk.pack.compile as compiler
from npk.pack.select import STOPWORDS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure_arm(source_dir, output_pack, filtered=False):
    original_extract = compiler._extract_symbols
    if filtered:
        kw_set = set(keyword.kwlist) | set(STOPWORDS)
        def clean_extract(block, language="unknown"):
            seen = {}
            for m in compiler.DEF_RE.finditer(block.text):
                seen[m.group(1)] = ("definition", True)
            for m in compiler.CONST_RE.finditer(block.text):
                seen.setdefault(m.group(1), ("constant", True))
            if block.name:
                seen.setdefault(block.name, ("definition", True))
            if language in ("python", "unknown"):
                for m in compiler.IDENT_RE.finditer(block.text):
                    name = m.group(0)
                    if name not in kw_set and name.lower() not in kw_set:
                        seen.setdefault(name, ("reference", False))
            block.symbols = [(n, k, d) for n, (k, d) in seen.items()]
            block.imports = [m.group(1) or m.group(2) for m in compiler.IMPORT_RE.finditer(block.text)]
        compiler._extract_symbols = clean_extract

    try:
        t0 = time.perf_counter()
        stats = compile_pack(source_dir, output_pack)
        compile_ms = (time.perf_counter() - t0) * 1000
    finally:
        compiler._extract_symbols = original_extract

    assert verify(output_pack)["ok"]
    with open_pack(output_pack) as con:
        total_symbols = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
        def_symbols = con.execute("SELECT count(*) FROM symbols WHERE is_def=1").fetchone()[0]
        ref_symbols = con.execute("SELECT count(*) FROM symbols WHERE is_def=0").fetchone()[0]
        top_symbols = [tuple(r) for r in con.execute(
            "SELECT name, count(*) c, sum(is_def) d FROM symbols GROUP BY name ORDER BY c DESC LIMIT 10"
        ).fetchall()]
        symbol_pages = con.execute("SELECT count(*), coalesce(sum(pgsize), 0) FROM dbstat WHERE name LIKE 'symbols%'").fetchone()

    return {
        "compile_ms": compile_ms,
        "pack_bytes": output_pack.stat().st_size,
        "total_symbols": total_symbols,
        "def_symbols": def_symbols,
        "ref_symbols": ref_symbols,
        "symbol_storage_bytes": symbol_pages[1],
        "top_10_symbols": top_symbols,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)

    base_pack = root / "baseline.npk"
    clean_pack = root / "filtered.npk"

    print("Compiling baseline arm...", flush=True)
    base_metrics = measure_arm(source, base_pack, filtered=False)
    print("Compiling filtered arm...", flush=True)
    clean_metrics = measure_arm(source, clean_pack, filtered=True)

    # Compare query equivalence for lexical and hybrid retrieval
    queries = ["retry policy", "ExitStack", "callback", "process_data", "RETRY_LIMIT",
               "parameter", "command", "context", "option", "runner"]
    comparisons = []
    for retrieval in ("lexical", "hybrid"):
        for q in queries:
            for b in (512, 2048):
                s1 = PackSelector(base_pack, retrieval=retrieval).select(q, budget_tokens=b)
                s2 = PackSelector(clean_pack, retrieval=retrieval).select(q, budget_tokens=b)
                comparisons.append({
                    "retrieval": retrieval, "query": q, "budget": b,
                    "base_spans": [e.span for e in s1.evidence],
                    "clean_spans": [e.span for e in s2.evidence],
                    "identical_spans": [e.span for e in s1.evidence] == [e.span for e in s2.evidence],
                    "base_tokens": s1.total_tokens,
                    "clean_tokens": s2.total_tokens,
                })

    identical_count = sum(1 for c in comparisons if c["identical_spans"])
    results = {
        "evidence_mode": "LOCAL",
        "generative_calls": 0,
        "baseline": base_metrics,
        "filtered": clean_metrics,
        "storage_reduction_bytes": base_metrics["pack_bytes"] - clean_metrics["pack_bytes"],
        "storage_reduction_pct": (base_metrics["pack_bytes"] - clean_metrics["pack_bytes"]) / base_metrics["pack_bytes"] * 100,
        "symbol_rows_removed": base_metrics["total_symbols"] - clean_metrics["total_symbols"],
        "symbol_rows_reduction_pct": (base_metrics["total_symbols"] - clean_metrics["total_symbols"]) / base_metrics["total_symbols"] * 100,
        "total_query_comparisons": len(comparisons),
        "identical_selections": identical_count,
        "comparisons": comparisons,
    }

    output_json = root / "results.json"
    output_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({
        "baseline_bytes": base_metrics["pack_bytes"],
        "filtered_bytes": clean_metrics["pack_bytes"],
        "bytes_saved": results["storage_reduction_bytes"],
        "pct_saved": f"{results['storage_reduction_pct']:.1f}%",
        "baseline_symbols": base_metrics["total_symbols"],
        "filtered_symbols": clean_metrics["total_symbols"],
        "symbol_rows_saved": results["symbol_rows_removed"],
        "identical_selections": f"{identical_count}/{len(comparisons)}",
        "baseline_top_symbols": base_metrics["top_10_symbols"],
        "filtered_top_symbols": clean_metrics["top_10_symbols"],
    }, indent=2))


if __name__ == "__main__":
    main()

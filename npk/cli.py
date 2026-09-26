"""CLI for NeuralPack Context Optimization & Source Packaging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .compiler import benchmark_source
from .compiler import compile_pack as legacy_compile_pack
from .compiler import update_pack as legacy_update_pack
from .format import PackError, diff_packs, inspect_pack, query_pack, verify_pack
from .pack import (
    COMPILE_MODES, MODE_DETERMINISTIC, PackSelector, LocalTokenizer,
    compile_pack, pack_stats, update_pack, verify,
)
# v1 and v2 each define their own PackError; keep them distinguishable.
from .pack.format import PackError as PackV2Error
from .telemetry import analyze_traces
from .auditor import audit_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="npk", description="NeuralPack: Universal Context Optimization Layer for AI Models")
    commands = parser.add_subparsers(dest="command", required=True)

    # Product Subcommands
    proxy_p = commands.add_parser("proxy", help="Start OpenAI-compatible reverse proxy gateway")
    proxy_p.add_argument("--host", default="127.0.0.1", help="Host to bind gateway")
    proxy_p.add_argument("--port", type=int, default=8000, help="Port to bind gateway")
    proxy_p.add_argument("--provider", choices=("auto", "openai", "anthropic", "gemini", "nvidia", "compatible", "mock"), default="auto", help="Backend provider")
    proxy_p.add_argument("--mode", choices=("optimized", "baseline", "shadow"), default="optimized", help="Optimization mode")
    proxy_p.add_argument("--model", default="gpt-4o-mini", help="Default model")

    analyze_p = commands.add_parser("analyze", help="Analyze offline LLM execution traces")
    analyze_p.add_argument("trace_file", type=Path, help="Path to traces.jsonl")

    explain_p = commands.add_parser("explain", help="Explain context optimization decisions for a request")
    explain_p.add_argument("request_id", help="Target request ID (e.g. npk-...)")
    explain_p.add_argument("--trace-file", type=Path, default=Path("experiments/traces.jsonl"), help="Path to traces.jsonl")

    audit_p = commands.add_parser("audit-run", help="Check identified raw logs and recompute substring-fixture metrics")
    audit_p.add_argument("run_dir", type=Path, help="Path to experiment run directory")

    # Compiled context artifact (zero generative LLM calls).
    build = commands.add_parser("compile", help="Compile a source tree into a .npk context artifact")
    build.add_argument("source", type=Path)
    build.add_argument("output", nargs="?", type=Path)
    build.add_argument("--mode", choices=COMPILE_MODES, default=MODE_DETERMINISTIC,
                       help="deterministic = CPU only, no models; semantic = also build a local embedding index")
    build_deps = build.add_mutually_exclusive_group()
    build_deps.add_argument("--deps", dest="build_deps", action="store_true",
                            help="build the experimental structural dependency index")
    build_deps.add_argument("--no-deps", dest="build_deps", action="store_false")
    build.set_defaults(build_deps=False)
    build.add_argument("--python-members", action="store_true",
                       help="EXPERIMENTAL: split Python classes at method boundaries")
    build.add_argument("--strict", action="store_true",
                       help="abort on any unindexable file instead of skipping and reporting it")

    update = commands.add_parser("update", help="Incrementally refresh a .npk from its source")
    update.add_argument("pack", type=Path)
    update.add_argument("source", type=Path)
    update.add_argument("--quick", action="store_true", help="Skip re-hashing files whose mtime and size match verified artifact records")
    update.add_argument("--strict", action="store_true",
                        help="abort on any unindexable file instead of skipping and reporting it")
    update_deps = update.add_mutually_exclusive_group()
    update_deps.add_argument("--deps", dest="build_deps", action="store_true")
    update_deps.add_argument("--no-deps", dest="build_deps", action="store_false")
    update.set_defaults(build_deps=None)

    query = commands.add_parser("query", help="Select evidence for a query. Makes no LLM calls.")
    query.add_argument("pack", type=Path)
    query.add_argument("query")
    query.add_argument("--budget", type=int, default=2000, help="evidence budget: exact with --tokenizer-json, otherwise estimated chars/4")
    query.add_argument("--tokenizer-json", type=Path, help="local tokenizer JSON for exact context counts; never downloaded by query")
    query.add_argument("--target-model", default=None, help="advisory only; the artifact is provider-independent")
    query.add_argument("--show-text", action="store_true", help="include the selected evidence text")
    query.add_argument("--expand-deps", action="store_true", help="enable EXPERIMENTAL dependency expansion")
    query.add_argument("--retrieval", choices=["lexical", "hybrid"], default="lexical",
                       help="BM25 default; hybrid is an experimental symbol/lexical/local-embedding fusion")
    query.add_argument("--no-escalation", action="store_true", help="strict single-pass selection")
    query.add_argument("--no-relations", action="store_true",
                       help="disable conservative syntactic raise-site retrieval")
    query.add_argument("--no-definitions", action="store_true",
                       help="do not resolve identifiers named in the query to their definitions")
    query.add_argument("--no-trim", action="store_true",
                       help="skip an oversized top-ranked block instead of emitting its best members")
    query.add_argument("--no-test-mate", action="store_true",
                       help="do not place the mirroring test file's best block after the top implementation block")
    query.add_argument("--map-share", type=float, default=0.0,
                       help="fraction of the budget for a context map: further ranked places "
                            "(path:start-end kind name) listed without their text")

    verify_p = commands.add_parser("verify", help="Integrity-check a .npk")
    verify_p.add_argument("pack", type=Path)

    stats_p = commands.add_parser("stats", help="Show summary statistics for a .npk pack or trace log")
    stats_p.add_argument("target", nargs="?", type=Path, default=Path("experiments/traces.jsonl"))

    # --- legacy v1 byte-level source container ---
    legacy_build = commands.add_parser("legacy-compile", help="[v1] byte-level source container")
    legacy_build.add_argument("source", type=Path)
    legacy_build.add_argument("output", nargs="?", type=Path)
    legacy_build.add_argument("--chunking", choices=("fixed", "cdc"), default="cdc")
    legacy_build.add_argument("--target-size", type=int, default=4096)

    for name in ("inspect", "legacy-verify"):
        command = commands.add_parser(name)
        command.add_argument("pack", type=Path)

    legacy_update = commands.add_parser("legacy-update")
    legacy_update.add_argument("pack", type=Path)
    legacy_update.add_argument("source", type=Path)

    legacy_query = commands.add_parser("legacy-query")
    legacy_query.add_argument("pack", type=Path)
    legacy_query.add_argument("query")
    legacy_query.add_argument("--limit", type=int, default=10)

    diff = commands.add_parser("diff")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)

    benchmark = commands.add_parser("benchmark", help="CPU compile/update benchmark, no inference")
    benchmark.add_argument("source", type=Path)
    benchmark.add_argument("--trials", type=int, default=3)
    benchmark.add_argument("--chunking", choices=("fixed", "cdc"), default="cdc")
    benchmark.add_argument("--target-size", type=int, default=4096)

    args = parser.parse_args(argv)
    try:
        if args.command == "proxy":
            from .gateway import run_gateway
            print(f"Starting NeuralPack Gateway on http://{args.host}:{args.port} [Provider: {args.provider}, Mode: {args.mode}]...")
            server = run_gateway(host=args.host, port=args.port, provider=args.provider, mode=args.mode, default_model=args.model)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nShutting down gateway...")
                server.server_close()
            return 0

        elif args.command == "audit-run":
            result = audit_run(args.run_dir)
        elif args.command == "analyze":
            result = analyze_traces(args.trace_file)

        elif args.command == "explain":
            result = {"error": f"Request {args.request_id} not found in {args.trace_file}"}
            if args.trace_file.exists():
                with args.trace_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                item = json.loads(line)
                                if item.get("request_id") == args.request_id:
                                    result = item
                                    break
                            except Exception:
                                continue

        elif args.command == "stats":
            if str(args.target).endswith(".npk"):
                try:
                    result = pack_stats(args.target)
                except (PackError, PackV2Error):
                    # Older v1 byte-container: report it rather than failing.
                    result = inspect_pack(args.target)
                    result["note"] = "legacy v1 container; recompile with 'npk compile' for v2 features"
            else:
                result = analyze_traces(args.target)

        elif args.command == "compile":
            output = args.output or args.source.absolute().with_suffix(".npk")
            result = compile_pack(args.source, output, mode=args.mode,
                                  build_deps=args.build_deps, python_members=args.python_members,
                                  strict=args.strict).as_dict()
            result["output"] = str(Path(output).absolute())
        elif args.command == "update":
            result = update_pack(args.pack, args.source, build_deps=args.build_deps, quick=args.quick,
                                 strict=args.strict).as_dict()
        elif args.command == "verify":
            result = verify(args.pack)
        elif args.command == "query":
            selector = PackSelector(str(args.pack),
                                    retrieval=args.retrieval,
                                    tokenizer=LocalTokenizer(args.tokenizer_json) if args.tokenizer_json else None,
                                    enable_dependency_expansion=args.expand_deps,
                                    enable_relations=not args.no_relations,
                                    enable_definitions=not args.no_definitions,
                                    enable_trim=not args.no_trim,
                                    enable_test_mate=not args.no_test_mate)
            selection = selector.select(args.query, budget_tokens=args.budget,
                                        target_model=args.target_model,
                                        allow_escalation=not args.no_escalation,
                                        map_share=args.map_share)
            result = selection.as_dict(include_text=args.show_text)

        elif args.command == "legacy-compile":
            output = args.output or args.source.absolute().with_suffix(".npk")
            result = legacy_compile_pack(args.source, output, chunking=args.chunking, target_size=args.target_size)
            result["output"] = str(output.absolute())
        elif args.command == "inspect":
            result = inspect_pack(args.pack)
        elif args.command == "legacy-verify":
            result = verify_pack(args.pack)
        elif args.command == "legacy-update":
            result = legacy_update_pack(args.pack, args.source)
        elif args.command == "diff":
            result = diff_packs(args.old, args.new)
        elif args.command == "legacy-query":
            result = {"index_kind": "lexical FTS5", "results": query_pack(args.pack, args.query, limit=args.limit)}
        else:
            result = benchmark_source(args.source, trials=args.trials, chunking=args.chunking, target_size=args.target_size)
    except (PackError, OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error), "command": args.command}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "verify" and not result.get("ok", False):
        return 1
    if args.command == "query" and result.get("status") == "fallback_required":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Report recorded HF experiments; all transport/amortization curves are models.

Run: python -m benchmarks.report --results experiments/results/baseline
The input directory must contain actual model_baseline outputs. This module never
creates timing observations and does not silently substitute synthetic results.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from npk.optimizer import break_even_requests


LABELS = {"cold_prefill": "Fresh prefill", "hot_prefix": "Resident prefix",
          "cpu_kv": "CPU KV", "persistent_kv": "File KV (page-cache warm)",
          "int8_kv": "INT8 file KV (approximate)"}
COLORS = {"cold_prefill": "#343e48", "hot_prefix": "#007f73", "cpu_kv": "#b07113",
          "persistent_kv": "#2864aa", "int8_kv": "#a14c8e"}
LIMITATIONS = [
    "Hugging Face Transformers, one process, batch size 1; these are not vLLM, "
    "SGLang or LMCache measurements and do not establish serving-system superiority.",
    "Weights/kernels are warm. Fresh prefill means no prefix reuse, not a cold model/server. "
    "TTFT excludes model loading, prompt tokenization, HTTP transport and scheduling queues.",
    "Input is synthetic repeated text with a fixed generated-token budget. Exact output identity "
    "and first-token logits do not establish task accuracy, instruction adherence or long-context quality.",
    "File loads follow file creation and repeated warmups: OS page cache is warm/uncontrolled. "
    "Physical cold-disk bandwidth and process-restart recovery are not measured by this harness.",
    "The measured file path validates the file hash and loads tensors; its preparation time combines "
    "validation, deserialization, conversion and host-to-device transfer. Their separate costs are unavailable.",
    "The current harness provisions resident GPU state only for the hot condition outside request timing. "
    "GPU peaks still include model weights and allocator behavior; they are not incremental cache sizes. "
    "No GPU utilization or energy claim is supported.",
    "Payload and host-to-device counters describe logical file/tensor bytes, not measured physical traffic: "
    "hashing plus loading can access bytes repeatedly. Physical storage reads are explicitly unavailable.",
    "Setup components were measured once per length. Amortization assumes every later request hits, "
    "stationary latency, no eviction and no further validation/invalidation costs beyond measured TTFT.",
    "Transfer curves add an unmeasured serial network hop to the measured warm-file path. No network, "
    "RDMA, cold storage, concurrency, larger-model or other-hardware result is extrapolated as measured.",
    "Median and p95 are descriptive sample statistics, not confidence bounds. Seven trials are insufficient "
    "for a stable tail-latency claim; even more trials do not replace representative workload diversity.",
]


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)


def numeric(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be numeric")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return float(value)


def integer(value, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def measurements(directory: Path):
    names = ("summary.json", "artifacts.json", "environment.json", "config.json", "raw.jsonl")
    missing = [name for name in names if not (directory / name).is_file()]
    if missing:
        raise ValueError("Incomplete benchmark output; missing " + ", ".join(missing))
    summary = load_json(directory / "summary.json")
    artifacts = load_json(directory / "artifacts.json")
    environment = load_json(directory / "environment.json")
    config = load_json(directory / "config.json")
    rows = [json.loads(line, parse_constant=_reject_constant)
            for line in (directory / "raw.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not rows:
        raise ValueError("No recorded measurement rows; refusing to invent a report")
    groups = defaultdict(list)
    for row in rows:
        length = integer(row["context_tokens"], "context_tokens", 1)
        if row["mode"] not in LABELS:
            raise ValueError(f"Unknown benchmark mode: {row['mode']}")
        for metric in ("ttft_ms", "prefill_ms", "end_to_end_ms", "max_abs_logit_error"):
            numeric(row[metric], metric)
        if not isinstance(row["exact_output_match"], bool):
            raise ValueError("exact_output_match must be an explicit boolean")
        integer(row["trial"], "trial")
        groups[length, row["mode"]].append(row)
    warnings = []
    if not environment.get("git", {}).get("commit"):
        warnings.append("EXPLORATORY PROVENANCE: no run-time Git commit was recorded. "
                        "A source-file hash is available, but a later clean, pinned run is needed for published claims.")
    if environment.get("git", {}).get("status"):
        warnings.append("The run recorded an unclean Git tree; preserve input/source hashes and rerun from a pinned clean revision.")
    stats = {}
    for key, group in sorted(groups.items()):
        trials = [row["trial"] for row in group]
        if len(set(trials)) != len(trials):
            raise ValueError(f"Duplicate trial identity for {key}")
        stat = {"n": len(group), "matches": sum(row["exact_output_match"] for row in group)}
        for metric in ("ttft_ms", "prefill_ms", "end_to_end_ms", "max_abs_logit_error"):
            vals = [row[metric] for row in group]
            stat[metric] = {"median": statistics.median(vals),
                            "p95": float(np.percentile(vals, 95)),
                            "variance": statistics.pvariance(vals), "max": max(vals)}
        if stat["n"] < 20:
            warnings.append(f"{key[0]} tokens / {key[1]}: only {stat['n']} trials; p95 is exploratory.")
        if stat["matches"] < stat["n"]:
            warnings.append(f"EXACT OUTPUT FAILURE: {key[0]} tokens / {key[1]}: "
                            f"{stat['n'] - stat['matches']}/{stat['n']} differ from the reference.")
        if config.get("trials") != len(group):
            warnings.append(f"{key}: observed count differs from configured trials={config.get('trials')}.")
        stats[key] = stat
    seen = set()
    for item in summary:
        key = item["context_tokens"], item["mode"]
        if key in seen or key not in stats:
            raise ValueError(f"Duplicate or unmatched summary row: {key}")
        seen.add(key)
        observed = stats[key]
        if (item["trials"] != observed["n"]
                or item["exact_output_matches"] != observed["matches"]):
            raise ValueError(f"Summary/raw trial or output-match disagreement: {key}")
        for metric in ("ttft_ms", "prefill_ms", "end_to_end_ms", "max_abs_logit_error"):
            supplied = numeric(item["metrics"][metric]["median"], f"summary {metric}")
            if not math.isclose(supplied, observed[metric]["median"], rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"Summary/raw median disagreement: {key} {metric}")
    if seen != set(stats):
        raise ValueError("Raw measurements missing from summary")
    artifact_by_length = {}
    for item in artifacts:
        length = integer(item["context_tokens"], "artifact context_tokens", 1)
        if item.get("status"):
            warnings.append(f"Artifact status at {length} tokens: {item['status']}; incomplete lengths omitted.")
            continue
        if length in artifact_by_length:
            raise ValueError(f"Duplicate complete artifact row at {length}")
        for field in ("compile_prefill_ms", "offload_ms", "serialize_hash_fsync_ms", "quantize_ms",
                      "int8_serialize_ms", "kv_file_bytes", "int8_file_bytes"):
            numeric(item[field], field)
        integer(item["kv_file_bytes"], "kv_file_bytes")
        integer(item["int8_file_bytes"], "int8_file_bytes")
        artifact_by_length[length] = item
    for length, mode in stats:
        if length not in artifact_by_length:
            raise ValueError(f"Missing setup/storage artifact evidence at {length} tokens")
        if (length, "cold_prefill") not in stats or (length, "hot_prefix") not in stats:
            warnings.append(f"{length} tokens: missing fresh or resident-prefix control; comparisons unavailable.")
    for length in config.get("context_lengths", []):
        for mode in config.get("modes", []):
            if (length, mode) not in stats:
                warnings.append(f"Configured observation absent: {length} tokens / {mode}.")
    return stats, artifact_by_length, environment, config, warnings


def setup_ms(mode: str, artifact: dict) -> float:
    compile_cost = artifact["compile_prefill_ms"]
    if mode == "cold_prefill":
        return 0.0
    if mode == "hot_prefix":
        return compile_cost
    cost = compile_cost + artifact["offload_ms"]
    if mode == "persistent_kv":
        cost += artifact["serialize_hash_fsync_ms"]
    elif mode == "int8_kv":
        cost += artifact["quantize_ms"] + artifact["int8_serialize_ms"]
    return cost


def save_figure(fig, directory: Path, stem: str):
    fig.savefig(directory / f"{stem}.png", dpi=180, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def plots(stats, artifacts, directory):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none"})
    lengths = sorted({key[0] for key in stats})
    fig, ax = plt.subplots(figsize=(10, 5.4))
    for mode, label in LABELS.items():
        xs = [length for length in lengths if (length, mode) in stats]
        if not xs:
            continue
        medians = [stats[length, mode]["ttft_ms"]["median"] for length in xs]
        p95 = [stats[length, mode]["ttft_ms"]["p95"] for length in xs]
        ax.plot(xs, medians, marker="o", label=label, color=COLORS[mode])
        ax.plot(xs, p95, linestyle=":", alpha=0.55, color=COLORS[mode])
        for x, y in zip(xs, medians):
            if stats[x, mode]["matches"] != stats[x, mode]["n"]:
                ax.scatter([x], [y], marker="x", s=120, color="#b00020", zorder=5)
    ax.set(xlabel="Synthetic prefix tokens", ylabel="Measured TTFT (ms)",
           title="Exploratory HF batch 1 · warm model and file page cache\nSolid: median; dotted: sample p95; red ×: output mismatch")
    ax.set_xscale("log", base=2)
    if all(stat["ttft_ms"]["median"] > 0 for stat in stats.values()):
        ax.set_yscale("log")
    ax.set_xticks(lengths, [f"{value:,}" for value in lengths])
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    save_figure(fig, directory, "ttft_vs_length")

    transfer_lengths = [length for length in lengths
                        if (length, "cold_prefill") in stats and (length, "persistent_kv") in stats]
    columns = min(2, max(1, len(transfer_lengths)))
    nrows = math.ceil(max(1, len(transfer_lengths)) / columns)
    fig, axes = plt.subplots(nrows, columns, figsize=(11, 4 * nrows), squeeze=False)
    bandwidth = np.logspace(-3, 2, 160)
    for ax, length in zip(axes.flat, transfer_lengths):
        cold, file = stats[length, "cold_prefill"], stats[length, "persistent_kv"]
        added_ms = artifacts[length]["kv_file_bytes"] / (bandwidth * 1e9) * 1000
        headroom = cold["ttft_ms"]["median"] - file["ttft_ms"]["median"]
        compute_budget = cold["prefill_ms"]["median"] - file["prefill_ms"]["median"]
        ax.plot(bandwidth, added_ms, color="#2864aa", label="Modeled extra serial-link time")
        if headroom > 0:
            ax.axhline(headroom, color="#007f73", label="Measured complete TTFT saving")
        else:
            ax.text(0.05, 0.05, "No positive complete-path saving", transform=ax.transAxes)
        if compute_budget > 0:
            ax.axhline(compute_budget, color="#b07113", linestyle=":", label="Measured prefill-only saving")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set(xlabel="Assumed serial-link bandwidth (decimal GB/s)", ylabel="Time / available saving (ms)",
               title=f"{length:,} synthetic prefix tokens · {artifacts[length]['kv_file_bytes']:,} file bytes")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=7)
    for ax in list(axes.flat)[len(transfer_lengths):]:
        ax.set_visible(False)
    if not transfer_lengths:
        axes.flat[0].set_visible(True)
        axes.flat[0].text(0.5, 0.5, "No matched file/fresh measurements", transform=axes.flat[0].transAxes, ha="center")
    fig.suptitle("MODEL ONLY · additional link time = measured file bytes / assumed bandwidth\nLink is affordable only below the complete-TTFT saving line; no network measured", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.89))
    save_figure(fig, directory, "transfer_sensitivity_modeled")

    columns = min(2, len(lengths))
    fig, axes = plt.subplots(math.ceil(len(lengths) / columns), columns,
                             figsize=(11, 4 * math.ceil(len(lengths) / columns)), squeeze=False)
    requests = np.arange(1, 101)
    for ax, length in zip(axes.flat, lengths):
        for mode, label in LABELS.items():
            if (length, mode) not in stats:
                continue
            values = setup_ms(mode, artifacts[length]) / requests + stats[length, mode]["ttft_ms"]["median"]
            suffix = " [output mismatch]" if stats[length, mode]["matches"] != stats[length, mode]["n"] else ""
            ax.plot(requests, values, label=label + suffix, color=COLORS[mode])
        ax.set(xlabel="Assumed requests sharing this compiled prefix", ylabel="Modeled amortized TTFT cost (ms/request)",
               title=f"{length:,} synthetic prefix tokens")
        ax.set_xscale("log")
        ax.grid(alpha=0.2)
    for ax in list(axes.flat)[len(lengths):]:
        ax.set_visible(False)
    axes.flat[0].legend(fontsize=7)
    fig.suptitle("MODEL ONLY · one-time setup + N × measured median TTFT\n100% hits; setup includes compile / offload / serialization as applicable", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    save_figure(fig, directory, "amortization_modeled")


def fmt(value):
    return "unavailable" if value is None else f"{value:,.3f}"


def generate(directory: Path) -> Path:
    stats, artifacts, environment, config, warnings = measurements(directory)
    plots(stats, artifacts, directory)
    lines = ["# Baseline measurement report", "",
             "**Scope: measured Hugging Face batch-1 inference on synthetic repeated text. "
             "File page cache is warm/uncontrolled. Native vLLM/LMCache controls are pending.**", "",
             "This report recalculates descriptive statistics from raw.jsonl and checks summary.json "
             "for agreement. It does not generate or replace measurements.", "",
             "## Findings and validity", ""]
    failures = sum(stat["n"] - stat["matches"] for stat in stats.values())
    lines.append(f"**Exact-output mismatches: {failures}.** " + (
        "Affected modes cannot be described as exact-equivalent on this run." if failures else
        "Token outputs matched this reference on these inputs; this does not establish general quality."))
    for length in sorted(artifacts):
        if (length, "cold_prefill") not in stats or (length, "hot_prefix") not in stats:
            continue
        cold = stats[length, "cold_prefill"]["ttft_ms"]["median"]
        hot = stats[length, "hot_prefix"]["ttft_ms"]["median"]
        file = stats.get((length, "persistent_kv"))
        sentence = f"At {length:,} prefix tokens, fresh median TTFT was {cold:.3f} ms and resident-prefix TTFT {hot:.3f} ms."
        if file:
            delta = file["ttft_ms"]["median"] - hot
            sentence += f" File reuse was {abs(delta):.3f} ms {'slower' if delta >= 0 else 'faster'} than resident-prefix reuse."
        lines.extend(["", sentence])
    lines.extend(["", "### Run warnings", ""])
    lines.extend([f"- {warning}" for warning in dict.fromkeys(warnings)] or ["- No count/status warnings."])
    lines.extend(["", "## Measured request timings", "",
                  f"Recorded query length: {config.get('query_tokens', 'unavailable')} tokens; "
                  f"output budget: {config.get('output_tokens', 'unavailable')} tokens; "
                  f"batch size: {config.get('batch_size', 'unavailable')}.", "",
                  "Ratios compare measured medians. A ratio above 1 favors the row over its stated control. "
                  "Resident-prefix is the strongest available reuse control; it excludes cache construction just as other request rows do.", "",
                  "| Prefix tokens | Mode | n | Median TTFT ms | p95 ms | Variance ms² | Fresh / row | Resident / row | Exact outputs | Max logit error |",
                  "|---:|---|---:|---:|---:|---:|---:|---:|---|---:|"])
    for (length, mode), stat in sorted(stats.items()):
        median = stat["ttft_ms"]["median"]
        def ratio(control):
            return stats[length, control]["ttft_ms"]["median"] / median if median and (length, control) in stats else None
        match = f"{stat['matches']}/{stat['n']}"
        if stat["matches"] != stat["n"]:
            match = f"**FAIL {match}**"
        lines.append(f"| {length} | {LABELS[mode]} | {stat['n']} | {fmt(median)} | "
                     f"{fmt(stat['ttft_ms']['p95'])} | {fmt(stat['ttft_ms']['variance'])} | "
                     f"{fmt(ratio('cold_prefill'))} | {fmt(ratio('hot_prefix'))} | {match} | {fmt(stat['max_abs_logit_error']['max'])} |")
    lines.extend(["", "![Measured TTFT](ttft_vs_length.png)", "",
                  "[SVG chart](ttft_vs_length.svg)", "", "## Setup and amortization model", "",
                  "The setup sum is compile-only for resident state; compile + offload for CPU; compile + offload + "
                  "serialize/hash/fsync for file; compile + offload + quantize + INT8 serialization for INT8. "
                  "The unrelated full-precision file serialization is not charged to INT8. Model load and tokenization "
                  "are common/excluded costs. Each setup component is one observation, not a median.", "",
                  "Model: total TTFT cost(N) = setup_ms + N × median_request_TTFT_ms. Strict break-even is the first "
                  "integer N whose modeled total is lower than fresh prefill. This is not observed multi-request throughput "
                  "and excludes subsequent decode. No finite break-even is claimed when the request itself is slower. "
                  "A reported N=1 can reflect a single setup sample below the separately measured cold median, "
                  "different prefill shapes, or timing variation; it is not proof that preparation is free. "
                  "Repeated paired setup+request measurements are needed to confirm that boundary.", "",
                  "| Prefix | Mode | Setup ms | File bytes | Strict N vs fresh | Token-output gate |",
                  "|---:|---|---:|---:|---|---|"])
    for (length, mode), stat in sorted(stats.items()):
        if mode == "cold_prefill" or (length, "cold_prefill") not in stats:
            continue
        artifact = artifacts[length]
        setup = setup_ms(mode, artifact)
        count = break_even_requests(stats[length, "cold_prefill"]["ttft_ms"]["median"], stat["ttft_ms"]["median"], setup)
        byte_count = artifact["int8_file_bytes"] if mode == "int8_kv" else artifact["kv_file_bytes"] if mode == "persistent_kv" else 0
        gate = "FAIL: mismatch" if stat["matches"] != stat["n"] else "matched tested tokens only"
        lines.append(f"| {length} | {LABELS[mode]} | {setup:.3f} | {byte_count:,} | {count if count is not None else 'never under this model'} | {gate} |")
    lines.extend(["", "![Modeled amortization](amortization_modeled.png)", "", "[SVG chart](amortization_modeled.svg)", "",
                  "## Transfer bandwidth sensitivity model", "",
                  "For an additional serial hop: transfer_ms = measured_full_KV_file_bytes / (assumed_GBps × 10⁹) × 1000. "
                  "The declining curve is that modeled added time; horizontal lines are measured "
                  "(fresh TTFT − warm-file TTFT) and (fresh prefill − cached suffix prefill). The latter is an "
                  "optimistic compute-only budget that excludes preparation. An added link is affordable only "
                  "when its curve falls below the complete-TTFT saving line. "
                  "The file path and its preparation remain in the solid model, so transfer is an added hop, not a "
                  "replacement disk-speed estimate. Curves are not empirical network measurements and do not model overlap or congestion.", "",
                  "![Modeled transfer](transfer_sensitivity_modeled.png)", "", "[SVG chart](transfer_sensitivity_modeled.svg)", "",
                  "## Measurement limitations", ""])
    lines.extend(f"- {limitation}" for limitation in LIMITATIONS)
    lines.extend(["", "## Reproduction and provenance", "", "Recorded command:", "", "```text",
                  str(environment.get("command", "not recorded")), "```", "", "Recorded environment:", "", "```json",
                  json.dumps(environment, indent=2, ensure_ascii=False), "```", "", "Recorded configuration:", "", "```json",
                  json.dumps(config, indent=2, ensure_ascii=False), "```", "", "Source/input digests:", "",
                  "| File | SHA-256 |", "|---|---|"])
    for name in ("summary.json", "raw.jsonl", "artifacts.json", "environment.json", "config.json"):
        value = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        lines.append(f"| [{name}]({name}) | `{value}` |")
    lines.append(f"| report generator | `{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}` |")
    target = directory / "report.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate(args.results.resolve())
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(2, f"Report input error: {exc}\n")
    print(result)


if __name__ == "__main__":
    main()

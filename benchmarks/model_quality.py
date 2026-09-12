"""Real-model synthetic quality and causal-edit probes, with explicit cache controls.

python -m benchmarks.model_quality --config experiments/smoke-fixed.json --output PATH
Imports and helper tests do not load a model. CLI execution loads the local model.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import gc
import json
from pathlib import Path
import random
import subprocess
import sys
import time

import torch

from . import corpus, model_baseline, quality
from .model_baseline import (
    Runner, as_cache, cache_tensors, canonical_hash, environment, quantize,
    read_cache, save_cache, sha_file, stats, sync, timed,
)


MODES = ("cold_prefill", "hot_prefix", "persistent_kv", "int8_kv")
EDIT_VARIANTS = ("append", "local_edit", "delete", "reorder")


def common_token_prefix(left: torch.Tensor, right: torch.Tensor) -> int:
    """Length of equal token prefix for two CPU batch-one input streams."""
    if left.ndim != 2 or right.ndim != 2 or left.shape[0] != 1 or right.shape[0] != 1:
        raise ValueError("Expected batch-one token matrices")
    length = min(left.shape[1], right.shape[1])
    mismatches = (left[0, :length] != right[0, :length]).nonzero()
    return int(mismatches[0, 0]) if len(mismatches) else length


def render_task(tokenizer, task: corpus.Task) -> tuple[torch.Tensor, torch.Tensor, str]:
    """Split a *single native chat token stream* before the query.

    Tokenizing context and query separately can change a boundary token. We
    instead take the common token prefix of full and context-only templates.
    The artificial context-only closing template is never passed to the model.
    """
    context_part = task.context + "\n\nQUESTION\n"

    def render(content):
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": content}], tokenize=False,
            add_generation_prompt=True,
        )

    full_text = render(context_part + task.query + "\n\nANSWER\n")
    full = torch.tensor([tokenizer.encode(full_text, add_special_tokens=False)])
    context_ids = torch.tensor([
        tokenizer.encode(render(context_part), add_special_tokens=False)
    ])
    split = min(common_token_prefix(full, context_ids), full.shape[1] - 1)
    if split < 1:
        raise ValueError("Chat template has no reusable context prefix")
    prefix, suffix = full[:, :split].clone(), full[:, split:].clone()
    if not torch.equal(torch.cat((prefix, suffix), 1), full):
        raise AssertionError("Cache split changed native token stream")
    return prefix, suffix, full_text


def cache_identity(fingerprint: str, prefix: torch.Tensor) -> str:
    return canonical_hash({"model_fingerprint": fingerprint,
                           "prefix_ids": prefix.tolist(),
                           "namespace": "model-quality-v1"})


def tensor_schema(tensors: dict[str, torch.Tensor]) -> dict:
    return {key: {"shape": list(value.shape), "dtype": str(value.dtype)}
            for key, value in sorted(tensors.items())}


def load_validated_cache(path: Path, identity: str, expected_schema: dict) -> dict:
    """Integrity/identity come from baseline; dimensions come from caller expectations.

    The supplied schema must originate from the trusted experiment configuration,
    not be accepted from an untrusted artifact as its own validation authority.
    """
    tensors = read_cache(path, identity)
    if tensor_schema(tensors) != expected_schema:
        raise ValueError("Cache tensor schema mismatch")
    if any(not bool(torch.isfinite(value).all()) for value in tensors.values()):
        raise ValueError("Nonfinite cache tensor")
    return tensors


def crop_tensors(tensors: dict[str, torch.Tensor], length: int) -> dict:
    """Crop dense, unquantized legacy K/V to a validated token-prefix length."""
    if type(length) is not int or length < 0:
        raise ValueError("Invalid crop length")
    if any(not (key.endswith(".k") or key.endswith(".v")) for key in tensors):
        raise ValueError("Crop expects unquantized K/V only")
    if any(value.ndim != 4 or length > value.shape[-2] for value in tensors.values()):
        raise ValueError("Crop exceeds dense K/V dimensions")
    return {key: value[:, :, :length, :].contiguous() for key, value in tensors.items()}


def compare_outputs(candidate: dict, logits: torch.Tensor,
                    reference: dict, reference_logits: torch.Tensor) -> dict:
    logp = reference_logits.log_softmax(-1)
    kl = float((logp.exp() * (logp - logits.log_softmax(-1))).sum())
    pairs = zip(candidate["output_ids"], reference["output_ids"])
    denominator = max(len(candidate["output_ids"]), len(reference["output_ids"]), 1)
    return {
        "exact_output_match": candidate["output_ids"] == reference["output_ids"],
        "token_agreement": sum(a == b for a, b in pairs) / denominator,
        "max_abs_logit_error": float((logits - reference_logits).abs().max()),
        "first_token_kl_reference_to_candidate": max(0.0, kl),
        "raw_kl_before_roundoff_clamp": kl,
    }


@torch.inference_mode()
def generate(runner: Runner, ids: torch.Tensor, max_new_tokens: int,
             cache_factory=None) -> tuple[dict, torch.Tensor]:
    """Greedy response, including EOS in IDs but excluding special tokens in text.

    Timings end at generated device tokens/EOS checks, before text decoding.
    This is quality instrumentation, not a repeated latency benchmark.
    """
    if not 1 <= max_new_tokens <= 128:
        raise ValueError("max_new_tokens must be between 1 and 128")
    if ids.shape[1] < 1:
        raise ValueError("At least one uncached token is needed for first logits")
    eos = runner.model.generation_config.eos_token_id
    if eos is None:
        eos = runner.tokenizer.eos_token_id
    eos_ids = set(eos if isinstance(eos, (list, tuple)) else [eos]) - {None}
    sync()
    start = time.perf_counter_ns()
    past, cache_prepare_ms = timed(lambda: cache_factory() if cache_factory else None)
    out, prefill_ms = timed(lambda: runner.model(
        ids.to(runner.device), past_key_values=past, use_cache=True, logits_to_keep=1,
    ))
    first_logits = out.logits[:, -1, :]
    token = first_logits.argmax(-1, keepdim=True)
    first_id = int(token.item())
    sync()
    ttft_ms = (time.perf_counter_ns() - start) / 1e6
    generated = [first_id]
    stopped = first_id in eos_ids
    decode_start = time.perf_counter_ns()
    while not stopped and len(generated) < max_new_tokens:
        out = runner.model(token, past_key_values=out.past_key_values,
                           use_cache=True, logits_to_keep=1)
        token = out.logits[:, -1, :].argmax(-1, keepdim=True)
        next_id = int(token.item())
        generated.append(next_id)
        stopped = next_id in eos_ids
    sync()
    decode_ms = (time.perf_counter_ns() - decode_start) / 1e6
    total_ms = (time.perf_counter_ns() - start) / 1e6
    result = {
        "output_ids": generated,
        "response": runner.tokenizer.decode(generated, skip_special_tokens=True),
        "generated_tokens": len(generated), "stopped_at_eos": stopped,
        "hit_token_limit": not stopped and len(generated) == max_new_tokens,
        "ttft_ms": ttft_ms, "cache_prepare_ms": cache_prepare_ms,
        "prefill_ms": prefill_ms, "decode_ms": decode_ms,
        "engine_end_to_end_ms": total_ms,
    }
    return result, first_logits.float().cpu()


def summarize_rows(rows: list[dict]) -> dict:
    result = {"quality": {}, "causal_edits": {}, "row_count": len(rows)}
    for track, output_key in (("quality", "quality"), ("causal_edit", "causal_edits")):
        buckets = defaultdict(list)
        for row in rows:
            if row["track"] == track:
                buckets[row["mode"]].append(row)
        for mode, group in buckets.items():
            result[output_key][mode] = {
                **quality.summarize(row["evaluation"] for row in group),
                "raw_baseline_failed": sum(not row["baseline_passed"] for row in group),
                "regressions_from_raw_pass": sum(row["regression"] for row in group),
                "improvements_from_raw_fail": sum(row["improvement"] for row in group),
                "exact_output_matches": sum(row["exact_output_match"] for row in group),
                "max_abs_logit_error": max(row["max_abs_logit_error"] for row in group),
                "max_first_token_kl": max(row["first_token_kl_reference_to_candidate"] for row in group),
                "hit_token_limit": sum(row["hit_token_limit"] for row in group),
                "descriptive_ttft_across_tasks_ms": stats([row["ttft_ms"] for row in group]),
                "timing_note": "One observation per distinct task, not repeated latency trials",
            }
    controls = [row for row in rows if row["mode"] == "naive_stale_negative_control"]
    result["negative_control_observable"] = any(
        not row["exact_output_match"] or row["max_abs_logit_error"] > 1e-3
        for row in controls
    ) if controls else None
    return result


def run_experiments(runner, tasks, output, max_new_tokens):
    rows, references, base_caches = [], {}, {}
    rng = random.Random(runner.config["seed"])
    rendered = {}

    def emit(task, track, mode, result, logits, reference, reference_logits, **extra):
        evaluation = quality.evaluate(task, result["response"])
        base_evaluation = quality.evaluate(task, reference["response"])
        row = {"task_id": task.id, "category": task.category, "track": track,
               "mode": mode, **result, **compare_outputs(result, logits, reference, reference_logits),
               "evaluation": evaluation, "baseline_passed": base_evaluation["passed"],
               "regression": base_evaluation["passed"] and not evaluation["passed"],
               "improvement": not base_evaluation["passed"] and evaluation["passed"], **extra}
        rows.append(row)
        with (output / "raw.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        print(json.dumps({"task": task.id, "track": track, "mode": mode,
                          "passed": evaluation["passed"], "regression": row["regression"],
                          "exact_match": row["exact_output_match"]}), flush=True)

    for task in tasks:
        (prefix, suffix, full_text), tokenize_ms = timed(lambda: render_task(runner.tokenizer, task))
        full = torch.cat((prefix, suffix), 1)
        if full.shape[1] + max_new_tokens > runner.model.config.max_position_embeddings:
            raise ValueError(f"Task {task.id} exceeds model positions; probes are never truncated")
        rendered[task.id] = (prefix, full)
        with (output / "inputs.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"task_id": task.id, "rendered_chat": full_text,
                                     "input_ids": full.tolist(), "prefix_tokens": prefix.shape[1],
                                     "suffix_tokens": suffix.shape[1], "tokenization_ms": tokenize_ms},
                                    ensure_ascii=False) + "\n")
        # Raw reference runs without an unrelated resident prefix cache.
        reference, reference_logits = generate(runner, full, max_new_tokens)
        references[task.id] = (reference, reference_logits)
        common = {"input_tokens": full.shape[1], "prefix_tokens": prefix.shape[1],
                  "suffix_tokens": suffix.shape[1], "model_fingerprint": runner.fingerprint}
        emit(task, "quality", "cold_prefill", reference, reference_logits,
             reference, reference_logits, **common)
        pref, compile_ms = timed(lambda: runner.prefill(prefix))
        cpu, offload_ms = timed(lambda pref=pref: {
            key: value.cpu() for key, value in cache_tensors(pref.past_key_values).items()
        })
        del pref
        identity = cache_identity(runner.fingerprint, prefix)
        path = output / "cache" / f"{task.id}.safetensors"
        manifest, save_ms = timed(lambda: save_cache(path, cpu, identity))
        compressed, quantize_ms = timed(lambda: quantize(cpu))
        qpath = output / "cache" / f"{task.id}.int8.safetensors"
        qmanifest, qsave_ms = timed(lambda compressed=compressed: save_cache(qpath, compressed, identity))
        schema, qschema = tensor_schema(cpu), tensor_schema(compressed)
        (output / "cache" / f"{task.id}.recipe.json").write_text(json.dumps({
            "identity": identity, "model_fingerprint": runner.fingerprint,
            "plain_schema": schema, "int8_schema": qschema,
            "int8_recipe": "symmetric int8, one absmax scale per batch/head over token and channel",
            "scale_dtype": "float16", "reconstruction_dtype": str(runner.dtype),
            "decode_attention": "full precision after cache reconstruction",
            "compile_ms": compile_ms, "offload_ms": offload_ms,
            "save_plain_hash_fsync_ms": save_ms, "quantize_ms": quantize_ms,
            "save_int8_hash_fsync_ms": qsave_ms,
            "plain_file_bytes": manifest["bytes"], "int8_file_bytes": qmanifest["bytes"],
        }, indent=2), encoding="utf-8")
        del compressed
        modes = list(MODES[1:])
        rng.shuffle(modes)
        for mode in modes:
            resident = None
            if mode == "hot_prefix":
                resident = {key: value.to(runner.device) for key, value in cpu.items()}

                def factory(resident=resident):
                    return as_cache(resident, runner.device, dtype=runner.dtype)
            else:
                selected_path, selected_schema = (qpath, qschema) if mode == "int8_kv" else (path, schema)

                def factory():
                    tensors = load_validated_cache(selected_path, identity, selected_schema)
                    return as_cache(tensors, runner.device, quantized=mode == "int8_kv", dtype=runner.dtype)

            result, logits = generate(runner, suffix, max_new_tokens, factory)
            emit(task, "quality", mode, result, logits, reference, reference_logits,
                 **common, cache_identity=identity)
            factory = None
            del resident
        if task.metadata["variant"] == "base":
            base_caches[task.category] = (prefix, cpu)
        gc.collect()

    # Intentional stale reuse is isolated here as a research negative control.
    for task in tasks:
        if task.metadata["variant"] not in EDIT_VARIANTS:
            continue
        base_prefix, base_cpu = base_caches[task.category]
        _, full = rendered[task.id]
        reference, reference_logits = references[task.id]
        lcp = min(common_token_prefix(base_prefix, full), full.shape[1] - 1)
        stale_length = min(base_prefix.shape[1], full.shape[1] - 1)
        for mode, reused in (("exact_causal_prefix", lcp),
                             ("naive_stale_negative_control", stale_length)):
            prefix_cpu = crop_tensors(base_cpu, reused)

            def factory():
                return as_cache(prefix_cpu, runner.device, dtype=runner.dtype) if reused else None

            result, logits = generate(runner, full[:, reused:], max_new_tokens, factory)
            emit(task, "causal_edit", mode, result, logits, reference, reference_logits,
                 input_tokens=full.shape[1], reused_tokens=reused,
                 correct_longest_token_prefix=lcp, recomputed_tokens=full.shape[1] - reused,
                 invalid_reused_token_count=max(0, reused - lcp),
                 research_control_only=mode == "naive_stale_negative_control",
                 model_fingerprint=runner.fingerprint)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--padding-blocks", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=None)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    padding = args.padding_blocks if args.padding_blocks is not None else config.get("quality_padding_blocks", 1)
    max_tokens = args.max_new_tokens if args.max_new_tokens is not None else config.get("quality_max_new_tokens", 64)
    if not 1 <= max_tokens <= 128:
        raise ValueError("max-new-tokens must be between 1 and 128")
    tasks = corpus.make_tasks(seed=config["seed"], padding_blocks=padding)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite existing experiment: {output}")
    (output / "cache").mkdir(parents=True, exist_ok=True)
    (output / "corpus.json").write_text(json.dumps(corpus.corpus_manifest(tasks), indent=2,
                                                   ensure_ascii=False), encoding="utf-8")
    meta = environment()
    meta.update({
        "status": "running", "config": config, "padding_blocks": padding,
        "max_new_tokens": max_tokens, "task_count": len(tasks),
        "command": subprocess.list2cmdline([sys.executable, "-m", "benchmarks.model_quality", *sys.argv[1:]]),
        "source_hashes": {"model_quality.py": sha_file(__file__),
                          "model_baseline.py": sha_file(model_baseline.__file__),
                          "corpus.py": sha_file(corpus.__file__), "quality.py": sha_file(quality.__file__)},
        "limitations": [
            "28 authored synthetic probes, not general LLM quality or standard benchmark accuracy",
            "One greedy run per task/mode, no stochastic confidence intervals",
            "Exact arithmetic equivalence may differ numerically across prefill shapes",
            "Int8 is a per-head scalar storage codec reconstructed before full-precision attention, not KIVI",
            "Files are OS-cache warm/uncontrolled; physical cold-disk IO not measured",
            "Naive stale reuse is a deliberate negative control, never a valid runtime route",
            "Tool-call score checks serialized text, not execution of real tools",
            "Timers include EOS checks, exclude final text decoding, and are descriptive only",
        ],
    })
    meta_path = output / "environment.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        runner, load_ms = timed(lambda: Runner(config))
        meta.update(model_fingerprint=runner.fingerprint, model_load_ms=load_ms,
                    effective_dtype=str(runner.dtype), device=runner.device,
                    chat_template_sha256=canonical_hash(runner.tokenizer.chat_template))
        # One generic warm-up, outside task observations. No expected answers are used.
        warm_ids = runner.tokenizer("A short warmup.", return_tensors="pt").input_ids
        warm = runner.prefill(warm_ids)
        del warm
        rows = run_experiments(runner, tasks, output, max_tokens)
        summary = summarize_rows(rows)
        summary["complete"] = len(rows) == 28 * 4 + 4 * 4 * 2
        (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
        meta["status"] = "complete" if summary["complete"] else "incomplete"
        print(json.dumps({"event": meta["status"], "rows": len(rows), "output": str(output)}), flush=True)
    except Exception as exc:
        meta.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

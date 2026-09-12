"""Matched single-request Transformers experiments; not a serving-system comparison.

Run: python -m benchmarks.model_baseline --config experiments/baseline.json
All input tokenization is outside inference timings and measured separately. Cache
retrieval, validation and host-to-device movement are inside cached request timings.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import torch
import transformers
from safetensors.torch import load_file, save_file
from transformers import AutoModelForCausalLM, AutoTokenizer, DynamicCache


def sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def timed(fn):
    sync()
    start = time.perf_counter_ns()
    value = fn()
    sync()
    return value, (time.perf_counter_ns() - start) / 1e6


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stats(values):
    return {"n": len(values), "median": statistics.median(values),
            "p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "mean": statistics.mean(values), "variance": statistics.pvariance(values),
            "min": min(values), "max": max(values)}


def git_state():
    def run(*args):
        result = subprocess.run(["git", *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    return {"commit": run("rev-parse", "HEAD"), "status": run("status", "--porcelain")}


def environment():
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,pci.bus_id",
                              "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        gpu = None
    return {"os": platform.platform(), "python": sys.version, "torch": torch.__version__,
            "transformers": transformers.__version__, "cuda": torch.version.cuda,
            "gpu": gpu, "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total, "git": git_state(),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_hash": sha_file(__file__)}


def cache_tensors(cache):
    return {f"{i:03d}.{kind}": tensor.detach().contiguous()
            for i, pair in enumerate(cache.to_legacy_cache())
            for kind, tensor in zip(("k", "v"), pair)}


def as_cache(tensors, device, quantized=False, dtype=torch.float16):
    pairs = []
    layers = len([key for key in tensors if key.endswith(".k")])
    for i in range(layers):
        pair = []
        for kind in ("k", "v"):
            key = f"{i:03d}.{kind}"
            value = tensors[key].to(device)
            if quantized:
                value = value.to(dtype) * tensors[key + ".scale"].to(device=device, dtype=dtype)
            pair.append(value)
        pairs.append(tuple(pair))
    # DynamicLayer.update concatenates new tensors, preserving shared prefix storage.
    return DynamicCache.from_legacy_cache(tuple(pairs))


def quantize(tensors):
    result = {}
    for key, value in tensors.items():
        scale = value.float().abs().amax(dim=(-2, -1), keepdim=True).clamp_min(1e-8) / 127
        result[key] = (value.float() / scale).round().clamp(-127, 127).to(torch.int8)
        result[key + ".scale"] = scale.to(torch.float16)
    return result


def save_cache(path, tensors, identity):
    save_file(tensors, str(path))
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())
    codec = {"name": "symmetric-int8-per-head" if any(key.endswith(".scale") for key in tensors) else "lossless-tensor",
             "granularity": "one scale per layer, K/V, batch item and KV head",
             "scale_storage_dtype": "float16", "residual": "none",
             "runtime": "restore full precision KV before ordinary attention; no int8 attention kernel"}
    manifest = {"format": 1, "identity": identity, "codec": codec, "sha256": sha_file(path),
                "bytes": path.stat().st_size}
    path.with_suffix(".json").write_text(json.dumps(manifest, indent=2))
    return manifest


def read_cache(path, identity):
    manifest = json.loads(path.with_suffix(".json").read_text())
    if manifest["format"] != 1 or manifest["identity"] != identity:
        raise ValueError("Incompatible cache identity")
    if path.stat().st_size != manifest["bytes"] or sha_file(path) != manifest["sha256"]:
        raise ValueError("Corrupt cache")
    return load_file(str(path), device="cpu")


class Runner:
    def __init__(self, config):
        self.config = config
        torch.manual_seed(config["seed"])
        torch.set_num_threads(config["threads"])
        if config["batch_size"] != 1:
            raise ValueError("This controlled harness currently supports batch size 1")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = getattr(torch, config["dtype"]) if self.device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(config["model_path"], local_files_only=True,
                                                       trust_remote_code=False)
        self.model = AutoModelForCausalLM.from_pretrained(
            config["model_path"], local_files_only=True, trust_remote_code=False,
            dtype=self.dtype, attn_implementation=config["attention"]
        ).eval().to(self.device)
        provenance = json.loads((Path(config["model_path"]) / "download-provenance.json").read_text())
        # Verify model/tokenizer files at model initialization, not on every request.
        for name, record in provenance["files"].items():
            if sha_file(Path(config["model_path"]) / name) != record["sha256"]:
                raise ValueError(f"Model file integrity failure: {name}")
        self.fingerprint = canonical_hash({"provenance": provenance["files"],
            "revision": provenance["revision"], "config": self.model.config.to_dict(),
            "torch": torch.__version__, "transformers": transformers.__version__,
            "dtype": str(self.dtype), "device": self.device, "attention": config["attention"],
            "namespace": "local-experiment"})

    @torch.inference_mode()
    def prefill(self, ids):
        return self.forward_prompt(ids.to(self.device))

    @torch.inference_mode()
    def forward_prompt(self, ids, past=None):
        chunk_size = self.config.get("prefill_chunk_tokens", 0)
        if chunk_size:
            if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
                raise ValueError("Prefill chunk size must be a positive integer")
            for start in range(0, ids.shape[1], chunk_size):
                out = self.model(ids[:, start:start + chunk_size], past_key_values=past,
                                 use_cache=True, logits_to_keep=1)
                past = out.past_key_values
            return out
        return self.model(ids, past_key_values=past, use_cache=True, logits_to_keep=1)

    @torch.inference_mode()
    def request(self, prefix, query, mode, hot, cpu, path, identity):
        sync()
        if self.device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        baseline_gpu_bytes = torch.cuda.memory_allocated() if self.device == "cuda" else 0
        baseline_rss_bytes = psutil.Process().memory_info().rss
        start = time.perf_counter_ns()
        lookup_start = start
        key = canonical_hash({"fingerprint": self.fingerprint,
                              "prefix": prefix.numpy().tobytes().hex()})
        if key != identity:
            raise ValueError("Prefix identity mismatch")
        lookup_ms = (time.perf_counter_ns() - lookup_start) / 1e6
        prep_start = time.perf_counter_ns()
        if mode == "cold_prefill":
            past = None
            input_ids = torch.cat((prefix, query), dim=1).to(self.device)
        else:
            if mode == "hot_prefix":
                tensors = hot
            elif mode == "cpu_kv":
                tensors = cpu
            else:
                tensors = read_cache(path, identity)
            past = as_cache(tensors, self.device, quantized=mode == "int8_kv", dtype=self.dtype)
            input_ids = query.to(self.device)
        sync()
        prep_ms = (time.perf_counter_ns() - prep_start) / 1e6
        out, prefill_ms = timed(lambda: self.forward_prompt(input_ids, past))
        first_logits = out.logits[:, -1, :]
        token = first_logits.argmax(-1, keepdim=True)
        sync()
        ttft_ms = (time.perf_counter_ns() - start) / 1e6
        generated = [token]
        decode_start = time.perf_counter_ns()
        for _ in range(self.config["output_tokens"] - 1):
            out = self.model(token, past_key_values=out.past_key_values,
                             use_cache=True, logits_to_keep=1)
            token = out.logits[:, -1, :].argmax(-1, keepdim=True)
            generated.append(token)
        sync()
        decode_ms = (time.perf_counter_ns() - decode_start) / 1e6
        total_ms = (time.perf_counter_ns() - start) / 1e6
        tokens = torch.cat(generated, 1).cpu().tolist()[0]
        result = {"mode": mode, "ttft_ms": ttft_ms, "prefill_ms": prefill_ms,
            "decode_ms": decode_ms, "end_to_end_ms": total_ms, "lookup_ms": lookup_ms,
            "deserialize_and_transfer_ms": prep_ms,
            "decode_tokens_per_second": (self.config["output_tokens"] - 1) * 1000 / decode_ms,
            "cpu_rss_bytes": psutil.Process().memory_info().rss,
            "cpu_fixture_baseline_rss_bytes": baseline_rss_bytes,
            "gpu_baseline_allocated_bytes": baseline_gpu_bytes,
            "gpu_peak_incremental_bytes": torch.cuda.max_memory_allocated() - baseline_gpu_bytes if self.device == "cuda" else None,
            "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated() if self.device == "cuda" else None,
            "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved() if self.device == "cuda" else None,
            "output_ids": tokens, "output_text": self.tokenizer.decode(tokens),
            "cache_hit": mode != "cold_prefill", "network_bytes": 0,
            "gpu_utilization": None, "energy_joules": None,
            "null_metric_reason": "No reliable per-request utilization/energy sampler; no invented values"}
        return result, first_logits.float().cpu()


def input_ids(tokenizer, length, query_length):
    text = ("Document section: The retrieval system indexes public technical notes. "
            "Requests preserve source provenance, tenant isolation, and exact instruction order.\n")
    unit = tokenizer.encode(text, add_special_tokens=False)
    prefix = (unit * math.ceil(length / len(unit)))[:length]
    query = tokenizer.encode("\nSummarize the requirements for this system in one sentence.\n",
                             add_special_tokens=False)
    query = (query * math.ceil(query_length / len(query)))[:query_length]
    return torch.tensor([prefix]), torch.tensor([query])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    output = Path(config["output_dir"])
    if (output / "raw.jsonl").exists():
        raise SystemExit(f"Refusing to overwrite previous measurements: {output}")
    (output / "cache").mkdir(parents=True, exist_ok=True)
    (output / "config.json").write_text(json.dumps(config, indent=2))
    meta = environment()
    meta["command"] = subprocess.list2cmdline([sys.executable, "-m", "benchmarks.model_baseline", *sys.argv[1:]])
    meta["limitations"] = ["Single-process batch-1 Transformers; not vLLM/LMCache throughput",
        "Weights and kernels warm; raw prefill means no reusable prefix state",
        "Persistent files are OS-page-cache warm/uncontrolled; physical cold-disk not measured",
        "Tokenized synthetic repeated text, not a quality corpus or natural prompt distribution",
        "No network transfer benchmark; cost curves outside this host are modeled"]
    (output / "environment.json").write_text(json.dumps(meta, indent=2))
    runner, model_load_ms = timed(lambda: Runner(config))
    meta.update({"model_load_and_verify_ms": model_load_ms, "fingerprint": runner.fingerprint,
                 "effective_dtype": str(runner.dtype), "device": runner.device})
    (output / "environment.json").write_text(json.dumps(meta, indent=2))
    randomizer = random.Random(config["seed"])
    rows, artifacts = [], []
    def run_request(mode, prefix, query, cpu, path, identity):
        # Provision a resident prefix only for the hot-cache condition, outside request timing.
        # Other conditions do not carry an unrelated GPU cache in their memory footprint.
        resident = {key: value.to(runner.device) for key, value in cpu.items()} if mode == "hot_prefix" else {}
        result = runner.request(prefix, query, mode, resident, cpu, path, identity)
        del resident
        return result
    for length in config["context_lengths"]:
        if length + config["query_tokens"] + config["output_tokens"] > runner.model.config.max_position_embeddings:
            raise ValueError("Requested context plus output exceeds model position capacity")
        (prefix, query), tokenize_ms = timed(lambda: input_ids(runner.tokenizer, length, config["query_tokens"]))
        identity = canonical_hash({"fingerprint": runner.fingerprint, "prefix": prefix.numpy().tobytes().hex()})
        print(json.dumps({"event": "length_start", "length": length}), flush=True)
        try:
            for _ in range(config["warmup_trials"]):
                out = runner.prefill(torch.cat((prefix, query), 1))
                del out
            pref, compile_ms = timed(lambda: runner.prefill(prefix))
            hot = cache_tensors(pref.past_key_values)
            del pref
            cpu, offload_ms = timed(lambda tensors=hot: {key: value.cpu() for key, value in tensors.items()})
            path = output / "cache" / f"{length}.safetensors"
            manifest, serialize_ms = timed(lambda tensors=cpu: save_cache(path, tensors, identity))
            quant, quantize_ms = timed(lambda tensors=cpu: quantize(tensors))
            qpath = output / "cache" / f"{length}.int8.safetensors"
            qmanifest, qserialize_ms = timed(lambda tensors=quant: save_cache(qpath, tensors, identity))
            kv_bytes = sum(value.numel() * value.element_size() for value in hot.values())
            quant_bytes = sum(value.numel() * value.element_size() for value in quant.values())
            artifacts.append({"context_tokens": length, "tokenization_ms": tokenize_ms,
                "compile_prefill_ms": compile_ms, "offload_ms": offload_ms,
                "serialize_hash_fsync_ms": serialize_ms, "quantize_ms": quantize_ms,
                "int8_serialize_ms": qserialize_ms, "kv_file_bytes": manifest["bytes"],
                "int8_file_bytes": qmanifest["bytes"],
                "kv_tensor_bytes": kv_bytes, "int8_tensor_bytes": quant_bytes,
                "context_source": "deterministic repeated technical sentence; token ids defined in harness"})
            del hot, quant
            reference, reference_logits = run_request("cold_prefill", prefix, query, cpu, path, identity)
            # Separate measurement rows; each mode gets a warm-up outside reported trials.
            for mode in config["modes"]:
                run_request(mode, prefix, query, cpu, qpath if mode == "int8_kv" else path, identity)
            for trial in range(config["trials"]):
                order = list(config["modes"])
                randomizer.shuffle(order)
                for mode in order:
                    record, logits = run_request(mode, prefix, query, cpu,
                        qpath if mode == "int8_kv" else path, identity)
                    logp = reference_logits.log_softmax(-1)
                    kl = (logp.exp() * (logp - logits.log_softmax(-1))).sum().item()
                    record.update({"trial": trial, "context_tokens": length,
                        "query_tokens": config["query_tokens"], "output_tokens": config["output_tokens"],
                        "max_abs_logit_error": (logits - reference_logits).abs().max().item(),
                        "first_token_kl_reference_to_candidate": max(0.0, kl),
                        "exact_output_match": record["output_ids"] == reference["output_ids"],
                        "token_agreement": sum(a == b for a, b in zip(record["output_ids"], reference["output_ids"])) / config["output_tokens"],
                        "logical_cache_payload_bytes": (qmanifest["bytes"] if mode == "int8_kv" else manifest["bytes"]) if mode in ("persistent_kv", "int8_kv") else 0,
                        "physical_storage_bytes_read": None,
                        "io_note": "Checksum streams full file, then mmap tensor load; OS-cache physical IO unmeasured",
                        "host_to_device_kv_bytes": (quant_bytes if mode == "int8_kv" else kv_bytes) if runner.device == "cuda" and mode in ("persistent_kv", "int8_kv", "cpu_kv") else 0})
                    rows.append(record)
                    with (output / "raw.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record) + "\n")
                    print(json.dumps({"length": length, "trial": trial, "mode": mode,
                                      "ttft_ms": round(record["ttft_ms"], 3),
                                      "match": record["exact_output_match"]}), flush=True)
            del cpu
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except torch.cuda.OutOfMemoryError as exc:
            artifacts.append({"context_tokens": length, "status": "out_of_memory", "error": str(exc)})
            print(json.dumps({"event": "out_of_memory", "length": length}), flush=True)
            # Do not leave the process in a dubious state and fabricate later measurements.
            break
        finally:
            (output / "artifacts.json").write_text(json.dumps(artifacts, indent=2))
    summaries = []
    for length in config["context_lengths"]:
        for mode in config["modes"]:
            group = [row for row in rows if row["context_tokens"] == length and row["mode"] == mode]
            if not group:
                continue
            metrics = ("ttft_ms", "prefill_ms", "decode_ms", "end_to_end_ms", "lookup_ms",
                       "deserialize_and_transfer_ms", "decode_tokens_per_second", "max_abs_logit_error",
                       "first_token_kl_reference_to_candidate", "token_agreement")
            summaries.append({"context_tokens": length, "mode": mode,
                "metrics": {key: stats([row[key] for row in group]) for key in metrics},
                "exact_output_matches": sum(row["exact_output_match"] for row in group), "trials": len(group)})
    (output / "summary.json").write_text(json.dumps(summaries, indent=2))
    print(json.dumps({"event": "complete", "rows": len(rows), "output": str(output)}), flush=True)


if __name__ == "__main__":
    main()

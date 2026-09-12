---
date: 2026-09-05
type: engineering-log
status: bounded-experiment-complete
---

# Model quality and causal edits

This track implements [model_quality.py](../../benchmarks/model_quality.py) and [CPU cache tests](../../tests/test_cache_runtime.py). It uses the existing local baseline runner and the 28-task authored corpus, with no additional model downloads.

## Actions and design

1. Read the updated baseline helpers, the smoke-fixed configuration, corpus generation and strict answer evaluation.
2. Implemented one full native chat-template stream per task. The cache prefix is the longest common token prefix with the context-only template; its remaining suffix comes directly from the full stream. An assertion checks exact concatenation. Expected answers and corpus metadata are never sent to the model.
3. Added greedy generation with EOS stopping and a configurable 64-token default limit (maximum 128). Outputs retain token IDs, decoded assistant responses, correctness, truncation and first-token logit comparisons.
4. Added raw, fresh hot-cache wrapper, newly loaded SafeTensors and per-head int8 storage comparisons. Compressed state is reconstructed into the runner's dtype before normal attention. This is not a low-bit attention implementation.
5. Added append/edit/delete/reorder comparisons using an exact longest-token-prefix crop. An intentionally stale-cache path is a research negative control and is not exposed as a runtime strategy.
6. Added CPU-only synthetic cache tests, including restart in a fresh Python subprocess, checksum failure, changed model/prefix identity, tensor dimensions, nonfinite values, unknown versions and fresh-wrapper isolation.
7. GPU inference is coordinated with the main baseline run. No model inference is started until the coordinating agent releases the GPU for this track.

## Reproduction

From the repository root with the experiment environment:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_cache_runtime.py -q
.venv\Scripts\python.exe -m benchmarks.model_quality --config experiments/smoke-fixed.json --output experiments/results/model-quality-rerun --padding-blocks 4 --max-new-tokens 64
```

The output directory must be empty. Records include full rendered inputs, task/answer provenance, raw responses, model and source hashes, per-artifact schemas/codec recipes, and summaries. One observation per task is a quality probe, not a repeated latency distribution. Raw failures are separated from regressions on tasks the raw model passed.

## Limits

This suite tests small synthetic prompts and one local model; it cannot establish broad correctness or long-context quality. EOS checks affect timings, whose purpose here is accounting. Exact causal reuse can produce floating-point differences across different prefill shapes. Persistent files may be in the OS page cache. The test restart validates safe tensor persistence and identity checks; it is not a new-process model-serving benchmark.

The benchmark persistence validator compares dimensions and dtypes against the caller's trusted expected schema after SafeTensors loading. Checksums detect accidental corruption; the sidecar is not authenticated. These helpers are not a resource-bounded parser for arbitrary adversarial packages. No pickle deserialization is used.

## Completed validation

On 2026-09-05, the 11 CPU tests passed, including the fresh Python subprocess read. Ruff passed for both new Python files. No model was loaded by the unit tests. The local model run completed all 144 observations: 28 tasks across four quality modes, and 16 mutations across two causal-reuse modes. There were no run errors. All quality-mode generations reached EOS within 64 tokens; one stale negative control hit the limit.

The observed model was Qwen2.5-0.5B-Instruct, FP16 on an RTX 3050 with 8 GiB VRAM, Windows 11, PyTorch 2.8.0+cu126 and Transformers 4.57.6. The four-padding-block inputs contained 1,168–1,242 native chat tokens. The model fingerprint is `29be661ef4315a8d8ff35a25ce733d7721bf60ec8ebb51051c79686089738812`. Run configuration, exact input text/token IDs, source hashes and raw responses are retained in [environment.json](../../experiments/results/model-quality/environment.json), [inputs.jsonl](../../experiments/results/model-quality/inputs.jsonl), [corpus.json](../../experiments/results/model-quality/corpus.json) and [raw.jsonl](../../experiments/results/model-quality/raw.jsonl).

| Mode | Strict task passes | Generated-token matches to raw | Regressions from a raw pass | Maximum first-token logit absolute error |
|---|---:|---:|---:|---:|
| Raw prefill | 7/28 | Reference | — | 0 |
| Fresh hot prefix wrapper | 7/28 | 28/28 | 0 | 0.0703125 |
| Newly loaded lossless SafeTensors | 7/28 | 28/28 | 0 | 0.0703125 |
| Int8 per-head storage, reconstructed FP16 | 6/28 | 25/28 | 1 | 2.99609375 |
| Exact causal prefix crop | 4/16 | 16/16 | 0 | 0.125 |
| Intentionally stale negative control | 2/16 | 5/16 | 2 | 12.93359375 |

The [machine-readable summary](../../experiments/results/model-quality/summary.json) includes category results and first-token KL. The raw baseline failed 21 of 28 strict tasks. For example, it often added Markdown around JSON or emitted a structured response to an exact-answer request. Preserving those failures is output preservation, not task success. Lossless cache routes matched all generated tokens in this bounded run but did not produce bitwise-identical first-token logits; different prefill shapes can change floating-point results.

The int8 regression occurred on `code.prefix_overlap`: raw emitted `{"batch":71}`, while int8 wrapped the correct value in a Markdown JSON block, violating the requested strict format. The other two int8 output differences occurred on tasks that the baseline already failed. The int8 codec approximately halved on-disk tensor file sizes (plain 14,171,888–15,081,200 bytes; int8 7,091,416–7,546,072 bytes). It does not reduce live attention precision: full FP16 K/V tensors are reconstructed before execution.

The stale path changed logits on all 16 mutations and generated tokens on 11. It regressed two previously correct deletion tasks: `document.delete` changed `MISSING` to `[0000-0]`, and `conversation.delete` changed `UNAPPROVED` to a 64-token continuation of stale context. Even appending raw context required cropping two boundary tokens from the base chat prefix because the base prefix included the question separator. This illustrates why reuse must be validated on the actual complete token stream rather than text block identity alone. These negative controls are evidence against naive stale reuse, not evidence that every stale edit must change the greedy answer.

## Actual attention backend audit

After releasing the completed quality process, a separate warmed real `Runner.prefill` on 1,024 tokens was profiled with `torch.profiler` CPU activities. Although `model.config._attn_implementation` was `sdpa`, the dispatched operators included:

| CPU-dispatched operator | Calls |
|---|---:|
| `aten::scaled_dot_product_attention` | 24 |
| `aten::_scaled_dot_product_attention_math` | 24 |
| `aten::_safe_softmax` | 24 |
| `aten::bmm` | 49 |

No efficient-attention or flash-attention operator appeared. [The complete profiler record](../../experiments/results/model-quality/real-model-attention-profiler.json) contains configuration, model fingerprint and source hash. This is actual-model operator-dispatch evidence, not a CUDA kernel-duration trace. The probe used the same model/configuration without prefill chunking; the coordinating agent had added an unused optional chunking method by then, so its harness source hash differs from the quality run's recorded hash.

Consequently, these quality-track timings cannot establish competitiveness against an optimized fused-attention baseline. They remain descriptive one-shot accounting on a math-attention execution path. The backend flag by itself was insufficient verification; this discovery was sent to the coordinating agent before any long-context baseline rerun. GPU ownership was then released.

## Decision and next boundary

Keep lossless persistence and exact token-prefix invalidation as the correctness default. Label the current int8 experiment as approximate; it failed the zero-regression criterion on this small corpus. Broader quality evaluation requires a model that solves more of the raw tasks, an optimized and profiled reference path, and more independent prompts. No cross-model translation, trained compressor, provider billing, standard benchmark accuracy or server-restart model latency has been measured by this track.

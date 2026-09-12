# 0003: SDPA configuration silently selected math attention

Date: 2026-09-05. This supersedes interpreting the first full-prefill capacity result
as a strong optimized baseline.

**Hypothesis:** `attn_implementation='sdpa'` plus a standalone efficient-attention probe
meant the Qwen model used the same kernel.

**Experiment:** Profile one warmed real 1024-token `Runner.prefill`, collecting dispatched
operator names. Artifact: `experiments/results/model-quality/real-model-attention-profiler.json`.

**Actual:** All 24 layers dispatched `_scaled_dot_product_attention_math`; no efficient
or flash attention event occurred. A standalone equal-head tensor SDPA probe had selected
efficient attention, so that probe did not establish the model path.

**Implementation evidence:** Transformers 4.57.6 `integrations/sdpa_attention.py`
`use_gqa_in_sdpa` enables native GQA on Torch >=2.5 with no explicit attention mask.
The local PyTorch 2.8.0 Windows CUDA wheel has no compiled FlashAttention. The resulting
GQA call falls back to math. Exact fast-kernel capability must be tested for the real shapes.

**Impact:** Baseline and first quality-run latency ratios are diagnostic only. The 16K
OOM tried allocating 14.06 GiB, consistent with materialized attention scores. Native
cache reuse still works, but its apparent advantage was inflated by this baseline.

**Next:** Explicitly expand KV heads before SDPA, preserving native mask semantics via
a registered attention implementation. Verify full and cached attention correctness,
profile the actual model dispatch, then rerun all compared modes under the same backend.
Do not modify installed dependencies or call a backend correction a new reuse technique.

# 0002: Full prefill exceeds local GPU capacity at 16K

Date: 2026-09-05.

**Hypothesis:** Qwen2.5-0.5B full prefill with PyTorch SDPA would fit 16K context on an
8 GB RTX 3050.

**Experiment:** `python -m benchmarks.model_baseline --config experiments/baseline.json`.
PyTorch 2.8.0+cu126, Transformers 4.57.6, fp16, batch 1. Windows's efficient SDPA kernel
is available; FlashAttention is not compiled in this wheel.

**Expected:** Complete 1K, 4K, 16K, and near-32K lengths.

**Actual:** 70 timed trials at 1K/4K completed; warm-up at 16K raised CUDA OOM.
The harness stopped, so 32K was unattempted. The raw exception is preserved in
`experiments/results/baseline/artifacts.json`.

**Interpretation:** This is the memory capacity of this configured execution path,
not proof of a model or architectural limit. No extra hot prefix resided on GPU
during the failing warm-up. Other harness CPU fixtures and allocator behavior are
documented separately.

**Next experiment:** Chunked prefill with 256-token blocks, keeping full causal attention
to preceding tokens, in both prefix construction and cold request paths. Rerun shorter
lengths too so the baseline is not silently changed only where favorable. Check logits
and generation agreement; different kernel partitioning can produce rounding differences.

**Resolution (2026-09-06):** Chunked prefill (256-token blocks) successfully eliminated the OOM at 16K context on the 8 GB RTX 3050.
All 60 trials across 1K, 4K, 8K, and 16K completed cleanly (`experiments/results/chunked`).
At 16K context, chunked cold prefill TTFT was 3,890 ms, while resident hot prefix TTFT was 65.2 ms (59.7x speedup) and persistent file KV TTFT was 286.4 ms (13.6x speedup), with 100% exact output match.

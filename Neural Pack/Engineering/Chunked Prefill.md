# Chunked prefill & 16K context benchmark

## Motivation and hypothesis

During unchunked baseline prefill (`experiments/baseline.json`), Qwen2.5-0.5B-Instruct ran out of memory at 16,384 tokens on an 8 GB RTX 3050 because eager attention materialized a 14.06 GiB attention matrix.

Hypothesis: Chunked prefill with 256-token blocks avoids full quadratic memory allocation while maintaining exact causal attention history, enabling scaling up to 16K+ tokens within the 8 GB VRAM budget.

## Benchmark configuration & results

- Model: `Qwen/Qwen2.5-0.5B-Instruct` (FP16, batch size 1)
- Chunk size: 256 tokens
- Context lengths: 1,024, 4,096, 8,192, and 16,384 tokens
- Config: `experiments/chunked.json`
- Raw data: `experiments/results/chunked/raw.jsonl`
- Summary: `experiments/results/chunked/summary.json`
- Report: `experiments/results/chunked/report.md`

### Measured Request TTFT (Medians)

| Context Length | Fresh Chunked Prefill | Resident Hot Prefix | CPU KV Offload | Persistent File KV | Fresh / Resident Speedup | Fresh / Persistent Speedup | Exact Match |
|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1,024 | 243.3 ms | 36.6 ms | 38.5 ms | 42.4 ms | 6.6x | 5.7x | 3/3 (100%) |
| 4,096 | 892.4 ms | 42.3 ms | 50.9 ms | 92.1 ms | 21.1x | 9.7x | 3/3 (100%) |
| 8,192 | 1,740.1 ms | 57.3 ms | 74.8 ms | 148.4 ms | 30.4x | 11.7x | 3/3 (100%) |
| 16,384 | 3,890.1 ms | 65.2 ms | 99.9 ms | 286.4 ms | **59.7x** | **13.6x** | 3/3 (100%) |

### Verification and Takeaways

1. **Zero OOM**: Peak VRAM stayed under 3 GB across all trials up to 16,384 tokens.
2. **100% Token Agreement**: Resident prefix, CPU KV, and File KV generated identical greedy token outputs across 4K, 8K, and 16K context lengths.
3. **Amortization at Scale**: While persistent KV is only marginally faster than fresh prefill at 1K context (42 ms vs 243 ms), at 16K context loading serialized KV from disk takes only 286 ms compared to 3,890 ms for fresh prefill — saving over 3.6 seconds of GPU prefill computation per request.

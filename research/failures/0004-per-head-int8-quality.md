# 0004: Simple per-head int8 storage fails the strict quality gate

Date: 2026-09-05.

**Hypothesis:** One symmetric int8 scale per layer/KV head would preserve generated
answers while roughly halving stored state.

**Implementation:** Quantize the whole token/head-dimension tensor with max-absolute
scale, store int8 values plus fp16 scale, restore full-precision tensors before attention.
This is not KIVI and uses no int8 attention kernel.

**Results:** Initial repeated-text 1K test changed the 16-token sequence in 7/7 trials;
4K repeated text matched in 7/7 trials. On 28 synthetic task tests, uncached/hot/persisted
state each passed 7; int8 passed 6, with one regression among the seven raw passes and
25/28 token-exact outputs. Maximum first-token KL was ~0.950.

**Interpretation:** Average compression and speed cannot justify promotion. The quality
gate rejects this candidate. The model itself failed 21 tasks, so this does not establish
robust task quality for either baseline or reuse.

**Next:** Keep int8 an explicit experimental candidate. If revisited, compare per-channel
keys/per-token values, residual windows and established KIVI-style methods with held-out
quality checks and full quantize/transfer/dequantize costs.

Raw data: `experiments/results/model-quality/summary.json` and `raw.jsonl`.
Timings from this run used math SDPA and are not optimized performance claims.

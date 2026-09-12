# NeuralPack research log

## 2026-09-05 — Initial investigation

**Question:** What useful context computation remains redundant after strong existing caching?

**Hypothesis:** The reusable portable boundary is source/index artifacts; exact neural state
requires an explicit model/runtime/prefix identity. A compatibility and cost planner may be
more useful than a new cache container.

**Experiment:** Prior-art/code review, hardware discovery, baseline and corpus setup in progress.

**Result:** No benchmark result yet. Existing systems overlap much of the original proposal.

**Interpretation:** Do not claim novelty for serialization, persistent KV or content addressing.

**Next experiment:** Matched cold prefill, in-memory exact prefix reuse, persisted KV and
retrieval preprocessing on a small open-weight model; measure correctness and full costs.

Detailed actions: [Obsidian journal](Neural%20Pack/Journal/2026-09-05.md).

## 2026-09-06 — Model Baselines, Chunked Prefill & Incremental Compilation

**Question:** Can persistent KV reuse beat cold prefill on consumer hardware without quality loss, and does chunk-level content-addressable compilation outperform simple file indexing?

**Hypothesis:** (1) Persistent SafeTensors KV beats fresh prefill at longer contexts (>1K tokens) while matching outputs token-for-token. (2) Chunked prefill solves the 16K OOM bottleneck. (3) Fine-grained chunking imposes metadata overhead that makes simpler file-level indexing faster.

**Experiment:** 
- Ran baseline inference sweep on Qwen2.5-0.5B-Instruct up to 4K tokens.
- Ran chunked prefill (256-token blocks) benchmark up to 16K tokens.
- Ran model quality and causal edit suite on 28 tasks.
- Ran incremental compilation sweep comparing CDC, fixed chunking, and SQLite FTS5 file index across 8 mutation types.

**Result:**
- At 16K context, chunked cold prefill was 3,890 ms vs 286 ms for persistent KV (13.6x speedup) and 65 ms for resident prefix (59.7x speedup), with 100% exact token matches.
- Chunked prefill eliminated the 14 GB attention allocation OOM at 16K tokens, fitting within 3 GB peak VRAM.
- INT8 per-head quantization caused task regressions on 1/7 previously passed tasks and failed the strict quality gate.
- In incremental source compilation, simple file indexing strictly dominated chunking on the Pareto frontier (30.4 ms vs 177-195 ms update; 419 KB vs 729-901 KB storage).

**Interpretation:** Persistent KV is highly effective for amortizing large cold starts (>4K tokens) where prefill computation dominates PCIe/NVMe transfer latency. However, generic chunk-level storage creates unnecessary overhead for source repositories; exact causal prefix caching and file-level lexical indexing provide superior efficiency.

**Next experiment:** Implement and benchmark an integrated runtime Context Execution Planner that dynamically decides between native recompute, persistent KV load, and incremental prefix splicing based on measured hardware transfer bandwidth and sequence length.

## 2026-09-06 — Independent audit, repair, and seed-quality research

**Question:** After a hostile independent audit falsified most prior claims, does
anything differentiated survive — and can a safe, seed-robust context optimizer
beat strong modern retrieval at matched token budgets?

**Hypothesis:** (1) The audited "token reduction" was partly produced by silently
destroying context, so the headline numbers were reward hacking rather than
optimization. (2) Because `Closure_D(∅) = ∅`, dependency expansion cannot rescue
a failed seed stage, so seed quality — not traversal depth — is the binding
constraint. (3) Lexical-only seeding fails on semantic gaps, and rank fusion with
a local embedding model closes that gap.

**Experiment:**
- Reproduced the context-destruction defect, then added hard invariants and a
  scale-free stopping rule; verified by mutation testing with an in-memory
  restore harness.
- Built 11 hard task families (semantic gap, 2–7 hop chains, dynamic imports,
  config indirection, symbol collision, multi-fact, distractors, negative
  constraints, version conflicts) over real third-party Python corpora at 25K and
  100K tokens per task, split dev/sealed by id hash.
- Compared nine seed systems at matched token budgets, using real models
  (`all-MiniLM-L6-v2`, `cross-encoder/ms-marco-MiniLM-L-6-v2`).
- Measured the cost/quality frontier (fewest tokens for full evidence recall) and
  ran live validation on `meta/llama-3.2-11b-vision-instruct`.

**Result:**
- The audited optimizer deleted a 2,510-token context, shipped a bare question,
  and reported 98.84% reduction with `fallback_to_raw: False`. Root cause: an
  absolute `0.05` threshold applied to the scale-dependent `BM25/√tokens`.
- Lexical-only seeding: 77.8% full evidence recall on dev, where tuned BM25, a
  bi-encoder, hybrid RRF and a cross-encoder all reached 100%. All failures were
  semantic gaps.
- Rank fusion (with a 0.35 similarity floor and [0,1] rescaling) lifted that to
  100%.
- **Sealed split:** full evidence recall at 146 tokens (25K contexts) and 153
  tokens (100K) versus 673 and 1,110 for tuned BM25 — 4.6× and 7.3×.
- **Live, 18 sealed tasks:** 100% task accuracy at 243 prompt tokens versus 77.8%
  at 7,803 for full context; full context leaked a superseded value on 11.1% of
  tasks, both retrieval arms 0%.
- Overhead: 3.4 ms at 2K → 154 ms at 100K (warm embedding cache).

**Interpretation:** The differentiation is the **seed stage**, not the dependency
graph. Graph expansion tied with the selector alone on both sealed frontiers
(146 vs 146; 153 vs 153), so the "dependency-aware" framing is not yet earned.
Sending less context also produced *better* answers than sending everything,
because the full context invited distraction between identically-named symbols
and superseded values — a genuine quality argument for reduction, not only a cost
argument. Evidence remains limited: n = 13–18 sealed tasks, one model family, and
synthetic needles over real distractor corpora.

**Next experiment:** Scale the sealed evaluation past 100 tasks across several
model families; decide whether graph expansion can beat a strong seed stage on
any family or should be dropped; calibrate the risk score against measured answer
accuracy; validate the 0.35 embedding floor out of distribution.

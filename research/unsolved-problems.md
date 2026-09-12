# Unsolved problems and falsifiable experiments

Written 2026-09-05. Paper evidence and immutable code references are in [papers](papers.md). **Nothing proposed here is a measured NeuralPack result.** Mathematical statements identify their assumptions; engineering hypotheses remain hypotheses until experiments run.

## U01 — Exact causal reuse ends at the dependency frontier

**Exact condition, mathematical inference.** For a deterministic causal decoder in evaluation mode, with fixed weights, input embeddings, attention masks, positions and model state, identical token prefixes produce identical mathematical K/V prefixes. Induct on layers: each prefix hidden state depends only on earlier/equal prefix states, whose values are unchanged. Appending tokens leaves existing prefix dependencies untouched.

Practical floating-point outputs may differ across kernels, batch layouts or reduction schedules. Equality of the mathematical computation does not guarantee byte-for-byte equality across runtimes or hardware. An exact reuse policy should distinguish numerical equivalence within a declared tolerance from binary identity.

| Mutation | Conservative exact route for a dense causal decoder | What a source DAG may still reuse |
|---|---|---|
| Append token IDs | Keep existing prefix state and prefill appended IDs | All unchanged source units |
| Append raw text | Retokenize the boundary; retain only the longest unchanged token prefix | Most source bytes |
| Replace token at p | Retain positions before p; recompute dependent suffix | Unchanged chunks and index entries |
| Delete/insert at p | Retain prefix before p; recompute suffix with new positions | Unchanged content-addressed chunks |
| Reorder chunks | Retain only the unchanged causal prefix by default | All identical chunk payloads |
| Change system prefix | Recompute downstream dense neural state | Document bytes/structure/index |
| Alter runtime/model/tokenizer | Require compatibility decision; identical source is insufficient | Portable source artifacts |

This is a sufficient conservative rule, not a theorem that every downstream tensor must numerically change after every edit. Zero weights, masked dependencies and symmetry may produce exceptions. Sliding-window, state-space and hybrid models need their own dependency analysis; a flat transformer rule is not universal.

**Small local experiment.** Use a deterministic tiny causal attention model with fixed random weights and save all layer K/V. Test append, single-token replacement, deletion and reorder. Compare (a) full recomputation, (b) longest-prefix reuse and suffix recomputation, (c) naive reuse by chunk hash. Report maximum K/V error by layer/position and final-logit difference. This validates causal implementation, not pretrained task quality. Do not label random-weight results as LLM accuracy.

## U02 — A delta tensor is not an incremental algorithm

For equal shapes, `KV_new = KV_old + (KV_new - KV_old)` is an exact identity. It says nothing about cheaply computing the residual or compressing it. For insertions/deletions, even that identity requires an explicit token/position alignment.

For standard RoPE, if `k_rot(p) = R(p) k_content`, then relocating the **same content vector** to q is `R(q) R(p)^-1 k_rot(p)`. The rotation is exactly invertible in real arithmetic. It does not repair changes to the underlying content vector from preceding attention. Relative-position invariance of a whole isolated sequence under a uniform shift also does not justify adding a new preceding chunk and reusing all deeper states.

**Test.** Compare ordinary suffix rebuild with (1) position correction only, (2) position correction plus a low-rank residual, (3) sparse token repair. Save singular values and physical residual bytes at each layer. Include an edit that reverses a controlling instruction near the start and an edit to an irrelevant late comment. A residual method is worth retaining only if computing/encoding/loading it costs less than recomputation and its continuation quality meets the chosen gate.

**Novelty boundary.** Offset estimation and selective repair already exist (P08/P09). A proposed new delta algorithm must outperform those or expose a clearly different exactness/workload condition.

## U03 — A tokenizer bridge must align information and causality

Tokenizer mismatch is more than differing vocabulary IDs. The same bytes can produce different sequence lengths and boundaries; normalization, byte fallback, whitespace, Unicode composition, special tokens and chat templates all matter. Equal token counts or equal visible strings do not establish compatible positions.

**Proposed portable artifact.** Preserve source bytes and explicit byte spans, a normalization declaration, role boundaries, and per-tokenizer offset maps. Never replace source text with the alignment map. Such a map enables measurement/retrieval; it does not itself produce target hidden states or eliminate target prefill.

**Causality trap.** A source token that spans bytes beyond a target token's boundary can contain information unavailable at the target token's native position. Projecting its state backward into the target sequence may introduce lookahead. Training and evaluation must not accidentally reward leaked future information. Align shared prefix boundaries before comparing target continuation, and record which byte interval every mapped state may depend on.

**No-download test.** Construct two small deterministic tokenizers over an invented vocabulary, with cases for `ab` versus `a|b`, whitespace, emoji/byte splits and repeated delimiters. Measure round-trip byte equality, coverage, dropped spans and causal-boundary violations. A FIRST/LONGEST selection heuristic can be tested without any model. Passing this test is necessary interface hygiene, not proof of neural transfer.

**Later model experiment.** Once existing local checkpoints are available, align at full-text byte boundaries and compare no mapper, per-span pooling, ridge and an explicit causal resampler on held-out text. Keep tokenization cost and target continuation quality separate. Do not feed source vocabulary IDs to an unrelated target embedding table.

## U04 — Lossy latent IR has a task contract

**Information argument.** Suppose an encoder maps every n-bit context into fewer than n bits and a later arbitrary query may request any original bit. Two contexts must share the same representation by the pigeonhole principle; a query at a differing bit cannot be answered correctly for both using only that representation. Therefore universally lossless fixed-size compression for arbitrary contexts/queries is impossible under this finite-bit setup.

This does **not** rule out useful compression on restricted data, task distributions, redundant texts or approximate objectives. It also does not prove a particular source KV cache is non-injective. The practical research question is the supported task contract, not a universal impossibility claim about all neural state.

**Candidate IR.** Source units, symbols, relationships, chronology and instruction/constraint spans can be portable preprocessing artifacts. They may save parsing, retrieval and prompt construction. When an existing model receives this IR as text, interpreting it still incurs prefill. Neural savings require a trained adapter or a runtime that accepts a computational artifact.

**Experiment.** Compare raw source, plain summary, structural IR, retrieval and native cached full context. Queries must be hidden from compilation for query-independent reuse claims. Include rare identifiers, small numbers, negations, exact formatting and chronological corrections. Count compiler time and tokens, not merely the consumer's shorter prompt.

**Keep/discard rule.** Retain source/structure IR as a utility only where reuse amortizes its cost. Promote a latent IR only after it beats a pairwise translator and same-model cache baseline on both held-out models and tasks at an explicitly declared quality level.

## U05 — Translation quality is not reconstruction quality

For a single attention head, `A(Q,K,V) = softmax(QK^T / sqrt(d)) V`. Its sensitivity depends on the receiver's queries, value geometry and softmax distribution. A low average squared K/V error can be concentrated in a critical location; a larger error can be almost invisible to the actual queries.

**Exact sufficient condition.** If the target receives its native K/V and every other execution input/state is fixed, future computation matches mathematically. **Not necessary:** internal symmetries can leave outputs invariant even when cache coordinates differ. For instance, adding the same key vector to every key of an attention head adds an equal scalar to its logits for a fixed query, leaving softmax unchanged (assuming identical eligible positions/mask and no additional key-dependent operation).

**Calibration experiment.** Fit independent K/V ridge, per-head ridge, Procrustes, reduced-rank regression and one small MLP. Select source layers and regularization on calibration/validation splits; reserve task tests for final evaluation. Compare KV R², receiver attention-output cosine, logit KL, cache-conditioned continuation NLL, greedy-answer agreement and task accuracy. Hold out documents, prompt templates and longer lengths. Use adversarial instruction tests as a separate gate, not diluted into average accuracy.

**Negative control.** Randomly permute token alignment or source heads. A benchmark that still reports excellent translation after a destructive control is not measuring the transferred cache properly.

## U06 — Low rank may save bytes and lose time

For a real T×D matrix stored as rank-r factors, factor payload scales as `r(T + D)` entries rather than `TD`, plus any basis/metadata. Ignoring metadata and assuming the same element width, the factors are smaller only when `r < TD/(T+D)`. With a shared fixed basis charged once across many contexts, accounting differs; report the amortization assumption.

Truncated SVD minimizes Frobenius reconstruction error at fixed rank. It does not minimize downstream attention error. A matrix's low rank under one prompt distribution need not persist for another. Reconstruction on every decode step can erase transfer gains. Compression of a stored checkpoint and a changed attention kernel are separate experiments.

**Small test.** Start with synthetic matrices of known ranks and noisy full-rank controls. Measure factorization, serialization, load and reconstruction separately with actual file sizes. Then, when native local KV exists, test rank/bit grids and continuation rather than single-forward perplexity. Include full-precision recent tokens and exact instruction spans as challengers, but charge their overhead and avoid selecting protected spans using hidden answer labels.

## U07 — Mapper economics need the complete path

Let C_fit be one-time calibration and fitting cost, C_source the source-prefill cost, C_load source-cache plus mapper load/transfer, C_map conversion, C_repair any receiver prefill, and C_native native target prefill. A source cache that already exists has zero *marginal* source-prefill cost for that handoff, but a pipeline that computes it only to accelerate the target must include C_source.

For N comparable reuses with sequential costs, break-even requires:

`C_fit + N(C_source_marginal + C_load + C_map + C_repair) < N C_native`.

If the per-reuse saving is nonpositive there is no N that amortizes fitting under these assumptions. In an overlapped pipeline, measure critical-path time and separately sum total resource work; simply adding stage timings can overstate latency. Include target-resident-cache reuse as a competitor: translation generally has no reason to beat an exact hot target cache unless memory pressure or routing changes the situation.

**Experiment.** Sweep context length, rank/head support, mapper hot/cold state, cache tier and reuse count. Report both already-source-prefilled handoff and source-prefill-plus-handoff. Compare native target prefix cache and target persistent cache. Include model loading separately, and never label mapper microseconds as TTFT.

## U08 — Theorem assumptions need geometry and runtime checks

For a stacked K/V linear projection from hidden dimension D to two Hkv×d outputs, full column rank is impossible when `2 Hkv d < D`. This is an elementary rank bound. Thus a theorem assuming invertibility of that projection must be checked against the concrete model geometry; it cannot automatically certify general GQA transfer. Layer normalization and other nonlinear transformations also require care when relating hidden vectors to linear projections. This is a mathematical caveat relevant to P06, not a claim that its empirical results are disproved.

General deployment fingerprints should include immutable weight revisions/hashes, tokenizer assets and normalization, prompt/chat template, adapter identity and activation history, attention layout, position IDs, RoPE type/scaling/factors, KV dtype/quantization scheme, masks, and runtime cache layout. Some fields may be relaxed by a proven adapter; record that proof/evaluation route explicitly.

**Implementation test.** Two configurations with equal layers/heads/dimensions but different weights or tokenizers must not qualify for direct reuse. Unsupported RoPE scaling, malformed tensor metadata, cross-tenant state and unknown schema versions must fail closed. Tensor integrity and authorization are distinct: a matching digest is not permission to read an artifact.

## Prioritized research queue

| Priority | Experiment | Why this can change the decision | Minimum success evidence |
|---|---|---|---|
| Now | Exact causal mutation test | Establishes which incremental promises are valid | Full recompute agreement for allowed routes; naive chunk reuse fails a control |
| Now | Actual serialization/load versus recompute | Determines whether persistent KV is worth transporting | Repeated measured costs with cold/warm labels |
| Now | Tokenizer byte-span and causality tests | Prevents invalid cross-family experiments | No silent missing bytes or future-boundary leakage |
| Next | Small matched-family ridge/head-local mapper | Cheapest credible transfer challenger | Held-out continuation/task quality plus end-to-end path saving |
| Next | Low-rank/quantized cache sweep | Tests whether bandwidth/storage dominates | Physical byte reduction and real continuation measurements |
| Later | Approximate edit repair versus CacheBlend/anchor offsets | Tests non-prefix incremental neural reuse | Quality/latency Pareto improvement over those baselines |
| Later | Shared latent pool versus pairwise mappers | Could reduce pair-count growth | New-model adapter experiment and unseen-pair holdout |
| Conditional | Train a shared-cache architecture | May yield exact compatibility by construction | Training budget justified by earlier controlled experiments |

Do not freeze a universal file format around unproven states. Preserve portable source truth, attach model-specific artifacts with explicit evidence levels, and let a planner choose recomputation whenever reuse is invalid or more expensive.

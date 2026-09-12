# Post-Audit Repair and Re-Validation

**Date:** 2026-09-06
**Baseline:** [`INDEPENDENT_AUDIT.md`](INDEPENDENT_AUDIT.md) and
[`research/math/INDEPENDENT_MATH_AUDIT.md`](research/math/INDEPENDENT_MATH_AUDIT.md).
All pre-audit reports are treated as invalid evidence and were not preserved for
compatibility.

**Classification: PROVEN PROMISING** — justification in §9, from post-fix
evidence only.

---

## 1. P0 security — complete

| Action | Result |
|---|---|
| Real NVIDIA key removed from tracked files | `tests/test_secrets.py` fixtures are now assembled at runtime (`"nvapi-" + "A"*64`), so no key-shaped literal exists on disk |
| Scanner assertion no longer swallowable | Broad `except Exception` removed; only `OSError`/`UnicodeDecodeError` are caught around file reads. An AST-based test rejects any handler catching `Exception`/`BaseException` |
| Git history purged | `git filter-branch` over all refs, `refs/original` deleted, reflog expired, `git gc --prune=now` |
| Independent verification | **All 273 blobs in the object store scanned: 0 contain a credential** |
| Scanner proven functional | `test_scanner_actually_detects_a_planted_secret` — the audited scanner *found* the key and discarded the finding |

The annotated tag `neuralpack-champion-pre-sealed-v1` was re-created as a
lightweight tag on the rewritten commit (annotating requires a git identity,
which I did not configure). `.env` remains untracked and untouched — **rotate the
credential yourself**; I created no replacement.

Caveat: history rewriting changed every commit SHA. There was no remote, so
nothing needed force-pushing.

---

## 2. P0 correctness — complete

### The central defect

Before: a 2,510-token context was deleted entirely, a bare question dispatched,
and the plan reported `98.84% reduction`, `fallback_to_raw: False`,
`quality_risk: 0.015`.

After, same input: `fallback_to_raw: True`, `reduction 0.0%`, needle preserved.

**Root cause.** `InformationGainSelector` broke its greedy loop on an absolute
constant (`efficiency <= 0.05`) applied to `BM25/√tokens` — a scale-dependent
quantity. The best block scored `0.0735/√25 = 0.0147`, so the loop returned `[]`
on iteration 1. `retrieve_relevant_context` returned `""`, and the planner
treated the resulting `dropped > 0` as a large win.

### Invariants now enforced

Implemented in `npk/context/safety.py`, gated in `npk/planner.py` before dispatch:

1. Context-bearing request can never become a bare question.
2. Current user query survives verbatim.
3. System instructions survive.
4. Failed seed stage returns the original context and flags `seed_failed`.
5. Bounded expansion never runs on an empty seed set (`Closure_D(∅) = ∅`).
6. Expansion re-checks the token budget (audited overshoot: 113/135/156/192 against a 100-token budget).
7. `fallback_kind` distinguishes `safety` from `cost_based_passthrough`, `seed_failure_partial`, and `none`.

### Selector threshold — benchmarked, not guessed

The absolute `0.05` was replaced with pluggable, scale-free stopping rules
(`relative`, `budget_fill`, `elbow`, plus `absolute_legacy` retained solely to
quantify the regression). `relative` — keep while efficiency ≥ 25% of the best
observed — is the default, chosen on dev-split measurements.

### Quality risk — derived, and honestly labelled

Hardcoded `0.001 / 0.015 / 0.045` replaced by `assess_risk()` over real signals:
query-term coverage, selection margin, dropped fraction, dynamic-indirection
detection, seed failure. Output is an **ordinal** score in a band prefixed
`uncalibrated:` — it is not a probability, and `risk_calibrated` is `False`.

One correction worth recording: my first risk model penalised token reduction
itself, which made raw passthrough always win — a different way of being useless.
Risk now models *evidence loss*, not compression. Lossless transforms (exact
duplicate removal) score 0.

### Dead flags

`enable_dedup` and `enable_prefix_opt` were assigned in `__init__` and never
read, voiding two rows of the published ablation. Both are now honoured.

### Cost model

`gpt-4o-mini` resolved to `gpt-4o` pricing via bidirectional substring matching —
a 16.7× overcharge on the planner's own default model. Now exact-ID matching
with alias resolution; every entry carries provider, source and `verified_on`;
`strict=True` raises on unknown models. Four unverifiable model entries removed.

### Metrics

`quality_retention_pct = ... if base > 0 else 100.0` deleted; retention is `None`
→ `"N/A"` when undefined. MockProvider pass-rates are named
`fixture_retention_pct`, never accuracy, and carry an explicit caveat. MSC
efficiency refuses mismatched granularities (the source of the impossible
118–154% figures).

---

## 3. Test suite — mutation-verified

| | Before | After |
|---|---|---|
| Tests | 181 passed, 1 skipped | 230 passed, 1 skipped |
| Mutants killed | 3 / 6 | **12 / 13** |
| Surviving real defects | dependency expansion, query preservation, safety fallback | **none** |

Final mutation run (13 injected defects, in-memory restore):

| Injected defect | Result |
|---|---|
| dependency expansion -> identity | CAUGHT |
| query preservation -> empty | CAUGHT |
| safety fallback -> never fires | CAUGHT |
| budget re-check -> ignored | CAUGHT |
| seed-failure guard -> ignored | CAUGHT |
| empty-seed guard -> expand anyway | SURVIVED (equivalent mutant, see below) |
| cost calculation -> always zero | CAUGHT |
| exact pricing -> substring match | CAUGHT |
| deduplication -> no-op | CAUGHT |
| provider registry -> always mock | CAUGHT |
| retention N/A -> fake 100% | CAUGHT |
| mock labelled as accuracy | CAUGHT |
| MSC granularity guard -> ignored | CAUGHT |

The single survivor is an **equivalent mutant**, verified not a coverage gap:
removing the `if not reachable: return reachable` early exit changes nothing,
because an empty seed set produces an empty frontier and the loop body never
executes. Both variants return `set()`. No test can distinguish them.

All `/tmp` counterexamples from the audit are now permanent regressions in
`tests/test_safety_invariants.py` and `tests/test_cost_and_metrics.py`.

**A process error worth recording:** my first mutation harness restored files via
`git checkout --`. My repairs were uncommitted, so it silently reverted five
repaired files and left a MUTANT line in an untracked one. Those results were
invalid and were discarded. The harness now snapshots file bytes in memory and
restores them in a `finally` block, and normalises CRLF so anchors match.

---

## 4. Attacking the real bottleneck: seed quality

The audit's one durable mathematical result — `Closure_D(∅) = ∅`, expansion
cannot recover what seeding missed — made seed quality the research target.

Nine seed systems were built and compared at **matched token budgets**, using
real models (`all-MiniLM-L6-v2`, `cross-encoder/ms-marco-MiniLM-L-6-v2`). No
n-gram vector is called an embedding.

**Finding (dev, 25K real contexts):** lexical-only seeding reached 77.8% full
evidence recall; tuned BM25, the bi-encoder, hybrid RRF and the cross-encoder all
reached 100%. Every failure was a *semantic gap* — the query shared no token with
the answer block ("how many jobs can run at the same time?" vs
`MAX_PARALLEL_WORKERS`).

**Fix:** reciprocal-rank fusion of lexical and local-embedding rankings, with:

* **a similarity floor (0.35)** so a bi-encoder — which returns a ranking for any
  input, including nonsense — cannot destroy the seed-failure signal. Derived
  from measured separation (genuine queries ≥ 0.392 n=8; nonsense ≤ 0.329 n=24).
  An empirical separation on a small sample, not a calibrated threshold.
* **rescaling of fused scores to [0,1]**, because RRF's narrow output band
  (~1/k) flattened the distribution and defeated the relative stopping rule, so
  nothing was pruned.
* **dense-only ranking when lexical carries no signal**, since fusing an
  arbitrary lexical ordering would dilute the only real signal present.

Result: 77.8% → 100% on dev.

---

## 5. Matched-budget frontier — sealed split

Fewest tokens at which each system retained **all** required evidence. Sealed
tasks were never used for tuning.

| System | @25K ctx | @100K ctx |
|---|---:|---:|
| **NeuralPack** | **146** | **153** |
| BM25 + expansion | 428 | 695 |
| hybrid RRF + expansion | 439 | 456 |
| BM25 + cross-encoder rerank | 485 | 567 |
| MiniLM bi-encoder | 656 | 787 |
| hybrid RRF | 670 | 784 |
| tuned BM25 | 673 | 1,110 |
| exact symbol lookup | never | never |

**4.6× fewer tokens than tuned BM25 at 25K; 7.3× at 100K.** The advantage grows
with context size, which is the regime the product targets.

Artifacts: `experiments/runs/frontier-sealed-25k/`, `frontier-sealed-100k/`.
n = 13. Per-task context medians: 25,870 and 101,885 tokens.

---

## 6. Live closed-model validation

`meta/llama-3.2-11b-vision-instruct`, 18 sealed tasks, deterministic grading of
the **model's answer**.

| Arm | Task accuracy | Prompt tokens | Reduction | Wrong-value leak |
|---|---:|---:|---:|---:|
| Full context | 77.8% | 7,803 | — | 11.1% |
| Tuned BM25 | 83.3% | 665 | 91.5% | 0.0% |
| **NeuralPack** | **100.0%** | **243** | **96.9%** | **0.0%** |

Failure detail:

* Full context failed both 7-hop dependency tasks and both symbol-collision tasks
  (distracted by an identically-named symbol in another module), and reported a
  superseded value on 11.1% of tasks.
* BM25 failed a semantic-gap task and both 7-hop tasks.
* NeuralPack: 18/18.

Sending less context produced **better** answers than sending everything.
Artifact: `experiments/runs/live-sealed-002/`.

---

## 7. Overhead — reported with context size

| Context tokens | Blocks | BM25 | Embed (cold) | Graph | Plan e2e |
|---:|---:|---:|---:|---:|---:|
| 2,175 | 3 | 1.0 ms | 67 ms | 0.7 ms | 3.4 ms |
| 27,028 | 10 | 11.1 ms | 197 ms | 6.6 ms | 37.4 ms |
| 50,890 | 20 | 21.5 ms | 385 ms | 12.8 ms | 81.0 ms |
| 101,372 | 35 | 47.4 ms | 684 ms | 25.1 ms | 154.5 ms |

The audited "sub-millisecond" claim came from a 710-token context. End-to-end
figures above assume a warm embedding cache; a cold pass adds the embedding
column. Sub-second at 100K against multi-second closed-model latency, and for a
closed-model optimizer local compute is nearly free against the tokens saved.

---

## 8. Mathematics — retracted and replaced

`research/math/theorems.md` was rewritten. Retracted: NP-completeness (hardness
holds; membership was never established, and the LLM oracle is stochastic and
non-monotone), "independent Top-K guarantees 0% accuracy" (three counterexamples,
including one inside the original proof's own example), "100% critical-context
recall" (circular proof; executed counterexample), the density-bounded
approximation ratio, and the "exact Pareto knee".

Kept and formalised: **Proposition 1**, `Closure_D(∅) = ∅` with monotonicity and
the distance bound — the result that drove this entire repair.

---

## 9. Classification: **PROVEN PROMISING**

Against the definitions: real advantages exist but evidence remains limited.

**For:** every P0 defect is fixed and mutation-verified. On sealed data never used
for tuning, NeuralPack reaches full evidence recall at 4.6–7.3× fewer tokens than
tuned BM25, and beats a real cross-encoder reranker. Under live closed-model
validation it scored 100% task accuracy at 243 prompt tokens where the full
context scored 77.8% at 7,803. The advantage widens with context size.

**Against STRONG VALIDATION:** n = 13–18 sealed tasks, one model family, needles
and queries synthetic even though distractor corpora are real. A one-task swing
moves accuracy ~6 points. The "less context beats full context" effect depends on
the target model being distractible and may shrink on frontier long-context
models.

**Not BREAKTHROUGH CANDIDATE:** nothing here has been independently replicated,
and the one novel-sounding component — dependency-graph expansion — is
**unproven**: it tied with the selector alone on both sealed frontiers (146 vs
146; 153 vs 153). The measured win comes from the seed stage.

### What NeuralPack actually is

A **seed-robust context selector for closed-model prompts**. Its differentiation
is reaching sufficient evidence at a far smaller token budget than strong
retrieval baselines, and doing so with hard safety invariants that make silent
context destruction impossible. It is not, on current evidence, a
"dependency-aware" optimizer — that claim has not earned its place.

---

## 10. Remaining work

1. **Scale the sealed evaluation** to 100+ tasks and several model families.
2. **Decide the fate of graph expansion** — find a family where it beats a strong
   seed stage, or drop the claim from the product narrative.
3. **Calibrate the risk score** against measured answer accuracy so
   `uncalibrated:` can be removed honestly.
4. **Validate the 0.35 embedding floor out of distribution**, or replace it with a
   conformal procedure carrying a coverage guarantee.
5. **Real queries over real repositories** — the current needles are generated.
6. **Re-verify the pricing table** before publishing any dollar figure.

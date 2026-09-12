# Claim register

**Superseded:** the previous version of this file marked 12 capabilities
"VERIFIED", including four that an independent hostile audit subsequently
falsified. It is replaced rather than amended, because its methodology (a
self-audit that accepted the existence of code as evidence that the code worked)
produced the false confidence in the first place.

**Authoritative baseline:** [`INDEPENDENT_AUDIT.md`](../../INDEPENDENT_AUDIT.md)
and [`INDEPENDENT_MATH_AUDIT.md`](../math/INDEPENDENT_MATH_AUDIT.md).

Rules for this file:

1. A claim is **VERIFIED** only when a test or artifact would *fail* if the claim
   were false. Mutation testing is the check: if breaking the feature leaves the
   suite green, the claim is not verified.
2. Every empirical claim states its **evidence mode** (LIVE / LOCAL / MOCK),
   **sample size**, and **per-task** context size. Cumulative token totals are
   never presented as context sizes.
3. MockProvider pass-rates are never called accuracy.

---

## Verified capabilities

| # | Claim | Evidence | Mutation-tested | Status |
|---|---|---|---|---|
| 1 | Provider-independent architecture | 7 adapters + registry | yes — registry mutant caught | **VERIFIED** |
| 2 | Context-destruction is impossible | `tests/test_safety_invariants.py` | yes — invariant + fallback mutants caught | **VERIFIED** |
| 3 | Seed failure ⇒ safe full-context fallback | `test_unmatchable_query_returns_original_context_never_empty` | yes — guard mutant caught | **VERIFIED** |
| 4 | Query survives optimization verbatim | `test_query_survives_optimization_verbatim` | yes — query mutant caught | **VERIFIED** |
| 5 | System instructions survive | `test_system_instruction_survives_optimization` | yes | **VERIFIED** |
| 6 | Dependency expansion respects the token budget | `test_transitive_expansion_respects_token_budget` | yes — budget mutant caught | **VERIFIED** |
| 7 | Dependency expansion actually expands | `test_dependency_expansion_reaches_transitively_connected_block` | yes — identity mutant caught | **VERIFIED** |
| 8 | Exact model-ID pricing (`gpt-4o-mini` ≠ `gpt-4o`) | `tests/test_cost_and_metrics.py` | yes — substring mutant caught | **VERIFIED** |
| 9 | Retention is `N/A`, never a fabricated 100% | `test_retention_is_undefined_when_baseline_is_zero` | yes | **VERIFIED** |
| 10 | Mock results are never labelled accuracy | `test_mock_results_are_never_called_accuracy` | yes | **VERIFIED** |
| 11 | No credential in working tree or git history | `tests/test_secrets.py` (8 tests) | scanner self-test proves detection works | **VERIFIED** |
| 12 | Cross-request isolation | `test_planner_reuse_does_not_leak_context_between_requests` | — | **VERIFIED** |

---

## Empirical results (measurements, not capabilities)

| # | Claim | Mode | n | Per-task context | Artifact | Status |
|---|---|---|---|---|---|---|
| 13 | 100% task accuracy at 243 prompt tokens vs 77.8% at 7,803 (full context) | **LIVE** | 18 sealed | median 10,561 tok | `experiments/runs/live-sealed-002/` | **MEASURED — small n** |
| 14 | Full context leaks a superseded value on 11.1% of tasks; retrieval arms 0% | **LIVE** | 18 sealed | median 10,561 tok | same | **MEASURED — small n** |
| 15 | Full evidence recall at 146 tokens vs 673 for tuned BM25 (25K context) | LOCAL | 13 sealed | median 25,870 tok | `experiments/runs/frontier-sealed-25k/` | **MEASURED — small n** |
| 16 | Full evidence recall at 153 tokens vs 1,110 for tuned BM25 (100K context) | LOCAL | 13 sealed | median 101,885 tok | `experiments/runs/frontier-sealed-100k/` | **MEASURED — small n** |
| 17 | Lexical-only seeding: 77.8% evidence recall vs 100% for every strong baseline | LOCAL | 9 dev | median 25,988 tok | `experiments/runs/pareto-dev-25k/` | **MEASURED** |
| 18 | Rank fusion lifts that 77.8% → 100% | LOCAL | 9 dev | median 25,988 tok | `experiments/runs/pareto-dev-25k-fuse/` | **MEASURED** |
| 19 | Plan overhead: 3.4 ms @ 2K → 154 ms @ 100K (warm cache) | LOCAL | 3 reps | stated per row | `experiments/results/profile-scale-001.json` | **MEASURED** |

---

## Explicitly NOT claimed

| Claim | Status | Why |
|---|---|---|
| Dependency-graph expansion improves recall | **UNPROVEN** | Tied with the selector alone on sealed data (146 vs 146; 153 vs 153). Helped on dev only. |
| `quality_risk` is a failure probability | **NO** | Ordinal signal, labelled `uncalibrated:*`. Never calibrated against measured accuracy. |
| Minimum Sufficient Context is NP-complete | **RETRACTED** | NP-hardness holds; NP-membership was never established. See math audit. |
| Independent Top-K guarantees 0% accuracy | **FALSIFIED** | Three counterexamples, including one in the original proof's own worked example. |
| 100% critical-context recall | **FALSIFIED** | Executed counterexample: 0 of 43 blocks selected, needle lost at every depth. |
| Operates at the exact Pareto knee | **RETRACTED** | No frontier was enumerated. A measured operating point is reported instead. |
| Embedding floor of 0.35 generalises | **NO** | Fitted to one corpus, n=32. Needs out-of-distribution validation. |

---

## Standing risks

1. **Small samples.** Every headline rests on 13–18 sealed tasks and one model
   family. A 1-task swing moves the accuracy figures by ~6 points.
2. **Task suite is partly synthetic.** Distractor corpora are real third-party
   Python, but the needles and queries are generated. Real user queries over real
   repositories remain untested.
3. **Single target model.** All LIVE evidence is `llama-3.2-11b-vision-instruct`.
   Results may not transfer to frontier models with stronger long-context
   handling — notably the "less context beats full context" effect, which depends
   on the baseline model being distractible.
4. **Pricing table needs re-verification** before any dollar figure is published;
   entries carry a `verified_on` date for exactly this reason.

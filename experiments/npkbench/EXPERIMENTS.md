# NPK-Bench experiment history

Generated from `EXPERIMENTS.jsonl` by `python -m benchmarks.npkbench.expdb render`.
Do not edit by hand.

| ID | Date | Title | Status | Reason |
|---|---|---|---|---|
| E000 | 2026-09-26 | Baseline: product as received on NPK-Bench dev-fast | **kept** | Reference point. Ranking (not packing) is the dominant loss; ~45% of selected tokens are docs/tests; 46/103 snapshots need blocker removal to compile. |
| E001 | 2026-09-26 | Compile speed: parse Python once, statement-only raise walk, memoized term analysis | **kept** | 1.49x faster (not the >=2x expected: cProfile overstated pure-Python call overhead) with logically identical packs on real Django; kept. |
| E001b | 2026-09-26 | Cache joined per-word analysis strings in analyzed_text | **rejected** | No measurable gain without the profiler (within noise). Reverted to keep the simpler code. Lesson: confirm profiler-guided micro-optimizations with uninstrumented paired timing. |
| E003 | 2026-09-26 | File-level evidence aggregation (block score + alpha * file top-3 sum) | **rejected** | No significant gain at any budget; alpha 1.0 hurts at 16K. Discarded. File recall even drops at 4K+ (0.524 vs 0.592). |
| E004 | 2026-09-26 | Skip and report never-indexed unindexable files instead of aborting the build | **kept** | Product can now compile every dev-fast snapshot, with explicit per-file reports and identical retrieval. |
| E005 | 2026-09-26 | Rank coarse blocks, emit only the best-matching K method-level children of large blocks | **rejected** | Helps only at 1K; loses 5-10 pts at 2K-16K on the fix target: trimming blocks that would have fit drops gold lines (non-top children, class-level lines, class-end insertions) more often than the freed budget recovers. Follow-up E005c trims only blocks that no longer fit. |
| E005c | 2026-09-26 | Top-block fit-or-trim: an oversized top-ranked Python block degrades to its best member spans | **kept** | Strict improvement on dev-fast: +13.9 / +7.3 points at 512 / 1K on the fix target, +0.7 / +0.5 on tests, identical selections at 2K-16K. Every emitted span is exact source with its own span; a note records the trim. enable_trim=False restores skipping. |
| E006 | 2026-09-26 | Implementation-first role prior (demote tests/docs/examples by a BM25 factor) | **rejected** | Benchmark gaming, confirmed by attack: the fix-target gain is bought by nearly eliminating recall of where maintainers put regression tests (4K: 0.141 -> 0.034). Not a default. Could only return as an explicit caller-declared intent. |
| E008 | 2026-09-26 | Role portfolio: per-role budget shares (impl/tests/docs), soft shares, pure test reservation | **rejected** | Attack by decomposition: the arms that improve both targets do so by demoting documentation, which NPK-Bench cannot falsify (it has no documentation target); giving docs 10-20% removes most of the gain, and a pure test reservation only transfers recall from fix to tests (two-target mean within noise). Hard shares also lose 10 points at 1K. Not promoted. |
| E009 | 2026-09-26 | Callee expansion from named-definition seeds | **rejected** | Fix-target changes stay within +/-2 points (noise at n=103) and the tests target loses up to 5.5 points. Precise seeds do not rescue graph expansion here; gold is mostly named or lexically matched directly. |
| E010 | 2026-09-26 | Drop very-high-document-frequency terms from long queries | **inconclusive** | ~3x faster lexical stage for long queries with fix-target recall within noise, but up to -3 points on the tests target at 16K. Latency is not a bottleneck at this scale (~30 ms uncontended); not promoted. Revisit for interactive/agent loops on very large repositories. |
| E011 | 2026-09-26 | Learned pairwise re-ranker over the product's candidate pool | **rejected** | With role features the model relearns documentation demotion and a fix->tests transfer (largest weights are role and doc-like kind proxies). Role-blind models do not beat the product's fused ranking (fix within +/-3 points). The remaining ranking headroom needs new evidence (semantic similarity, structure), not reweighting of existing channels. |
| E013 | 2026-09-26 | Sibling/near-duplicate collapse (measured before building) | **rejected** | At most 3.1% of selected tokens could be reclaimed on this workload; not worth a new representation now. Revisit for repetitive/vendored corpora or conversation logs. |
| M000 | 2026-09-26 | Baseline: conversation memory (LongMemEval-S dev, 100 questions) | **kept** | Reference point for the second workload family. Weak spots: multi-session aggregation and implicit preferences. |
| M001 | 2026-09-26 | Source-diverse packing (per-file score decay) for multi-session memory questions | **rejected** | Turn recall falls 10-16 points: fused RRF scores are nearly flat (1/60..1/120), so any per-file decay reorders almost the whole ranking toward weakly matching fresh sessions. Session coverage rises but evidence turns are lost. |
| M002 | 2026-09-26 | Relevance-density ordering (fused score / tokens^alpha) before greedy fill | **rejected** | Aggregate gain is a disguised role prior: it comes from LongMemEval's composition (842/896 evidence turns are user turns) and collapses the question type whose evidence is in long assistant turns (1K: 0.833 -> 0.333). Not a default. Pursue finer units for long turns instead. |
| M003 | 2026-09-26 | Paragraph-level units for long conversation turns (data-level layout test) | **rejected** | Mixed: +1.1/+3.6 at 2K/4K and better session coverage, but -8.9/-1.1/-2.1 at 256/512/1K. Turn-level units stay; no compiler change. |

## E000 — Baseline: product as received on NPK-Bench dev-fast

- **Status:** kept
- **Hypothesis:** Establish reference numbers for the unmodified product (BM25 fields + raise relations, greedy fill).
- **Run:** experiments/npkbench/runs/E000b-rescore-and-e002-devfast (npk_default arm; E000 run uses gold v1.0)
- **Commit:** 6b90748
- **Bench version:** npkbench-1.1
- **Results:**

```json
{
 "file_recall": {
  "16K": 0.777,
  "1K": 0.369,
  "2K": 0.476,
  "4K": 0.592,
  "8K": 0.68
 },
 "hunk_recall": {
  "16K": 0.544,
  "1K": 0.209,
  "2K": 0.301,
  "4K": 0.408,
  "8K": 0.474
 },
 "loss_breakdown_2K": {
  "packing_skip": 8,
  "ranked_later": 83,
  "selected": 43,
  "unranked": 19
 },
 "selected_token_share_2K": {
  "doc": 0.212,
  "example": 0.02,
  "source": 0.56,
  "test": 0.208
 },
 "snapshots_blocked_by_one_file": "46/103",
 "tokens_to_all_median_all_tasks": 19299,
 "tokens_to_first_median": 6427
}
```

- **Decision:** Reference point. Ranking (not packing) is the dominant loss; ~45% of selected tokens are docs/tests; 46/103 snapshots need blocker removal to compile.
- **Follow-ups:** E001 compile speed; E002 entity-aware queries; E004 robust ingestion

## E001 — Compile speed: parse Python once, statement-only raise walk, memoized term analysis

- **Status:** kept
- **Hypothesis:** Two hot spots (a second AST parse+walk per file for raise sites; per-word pure-Python analysis) can be removed without changing artifact contents.
- **Expected:** >=2x faster compile on Django with logically identical packs
- **Commit:** 882fccd
- **Files changed:** `npk/pack/compile.py`, `npk/pack/search.py`
- **Results:**

```json
{
 "check": "benchmarks.npkbench.equivalence: all tables, FTS5 instance postings, docsize, manifest",
 "django_13768_compile_s_median_uncontended": {
  "baseline": 20.748,
  "e001": 13.964
 },
 "logically_identical": true,
 "speedup": 1.486
}
```

- **Tradeoffs:** None measured; SyntaxWarnings from repository code are now suppressed during parsing (diagnostic noise, not output).
- **Decision:** 1.49x faster (not the >=2x expected: cProfile overstated pure-Python call overhead) with logically identical packs on real Django; kept.
- **Follow-ups:** E001b: cache joined per-word analysis strings

## E001b — Cache joined per-word analysis strings in analyzed_text

- **Status:** rejected
- **Hypothesis:** cProfile attributes 5.1 s to analyzed_terms; joining cached per-word strings with a comprehension removes most of it.
- **Results:**

```json
{
 "django_13768_compile_s_median": {
  "e001": 14.6,
  "e001b": 15.072
 },
 "output_identical": true
}
```

- **Decision:** No measurable gain without the profiler (within noise). Reverted to keep the simpler code. Lesson: confirm profiler-guided micro-optimizations with uninstrumented paired timing.

## E003 — File-level evidence aggregation (block score + alpha * file top-3 sum)

- **Status:** rejected
- **Hypothesis:** Several matching blocks in one file corroborate that the file is on topic; boosting its blocks improves ranking.
- **Run:** experiments/npkbench/runs/E000b-rescore-and-e002-devfast
- **Results:**

```json
{
 "hunk_recall": {
  "alpha_0.5": [
   0.228,
   0.33,
   0.409,
   0.487,
   0.55
  ],
  "alpha_1.0": [
   0.191,
   0.311,
   0.409,
   0.458,
   0.502
  ],
  "baseline": [
   0.209,
   0.301,
   0.408,
   0.474,
   0.544
  ]
 },
 "paired_alpha_0.5_vs_baseline": "no budget significant (e.g. 2K +0.029, CI [-0.019,+0.078])"
}
```

- **Decision:** No significant gain at any budget; alpha 1.0 hurts at 16K. Discarded. File recall even drops at 4K+ (0.524 vs 0.592).

## E004 — Skip and report never-indexed unindexable files instead of aborting the build

- **Status:** kept
- **Hypothesis:** Aborting a whole build on one NUL/non-UTF-8/oversized/credential-like file makes the product unusable on real repositories; skipping never-indexed files with an explicit report fixes that without silent evidence loss.
- **Expected:** 0/103 dev-fast snapshots blocked (from 46/103); identical retrieval
- **Run:** experiments/npkbench/runs/E004-rebuild-parity-devfast
- **Commit:** b56e96a
- **Files changed:** `npk/pack/compile.py`, `npk/pack/source_policy.py`, `npk/pack/contracts.py`, `npk/cli.py`, `tests/test_source_boundary.py`, `tests/test_source_scan_failures.py`, `benchmarks/contract_mutations.py`
- **Results:**

```json
{
 "compile_s_mean_4_workers": {
  "E000": 25.82,
  "E001+E004": 14.96
 },
 "skipped_sources_reported": "46/103 tasks; reasons nul 46, non_utf8 15, credential 5",
 "snapshots_needing_harness_removal": {
  "after": "0/103",
  "before": "46/103"
 },
 "span_level_parity_with_E000b": "1545/1545 selections identical",
 "tests": "1228 passed; 5 targeted mutants assertion-killed"
}
```

- **Tradeoffs:** A file that is already indexed and becomes unindexable still aborts an update (no silent evidence loss). strict=True/--strict restores fail-closed builds. Credential text never reaches the artifact or the report.
- **Decision:** Product can now compile every dev-fast snapshot, with explicit per-file reports and identical retrieval.

## E005 — Rank coarse blocks, emit only the best-matching K method-level children of large blocks

- **Status:** rejected
- **Hypothesis:** Gold edits sit in large blocks (median 875 tokens); the gold method is the top-2 lexical child 82% of the time, so emitting children frees budget for more candidates.
- **Run:** experiments/npkbench/runs/E005-cf-role-devfast-{fix,tests}
- **Results:**

```json
{
 "fix_target_hunk_recall": {
  "k1": [
   0.257,
   0.306,
   0.34,
   0.379,
   0.45
  ],
  "k2": [
   0.299,
   0.337,
   0.377,
   0.426,
   0.511
  ],
  "k2_refs": [
   0.299,
   0.333,
   0.382,
   0.435,
   0.502
  ],
  "k3": [
   0.333,
   0.387,
   0.416,
   0.46,
   0.526
  ],
  "product(defs)": [
   0.285,
   0.44,
   0.479,
   0.523,
   0.607
  ]
 },
 "prototype_latency_ms_2K": 800,
 "tests_target_hunk_recall": {
  "k3": [
   0.04,
   0.079,
   0.155,
   0.233,
   0.321
  ],
  "product(defs)": [
   0.035,
   0.064,
   0.141,
   0.24,
   0.309
  ]
 }
}
```

- **Decision:** Helps only at 1K; loses 5-10 pts at 2K-16K on the fix target: trimming blocks that would have fit drops gold lines (non-top children, class-level lines, class-end insertions) more often than the freed budget recovers. Follow-up E005c trims only blocks that no longer fit.
- **Follow-ups:** E005c fit-or-trim (graceful degradation instead of skipping)

## E005c — Top-block fit-or-trim: an oversized top-ranked Python block degrades to its best member spans

- **Status:** kept
- **Hypothesis:** Trimming hurts only when a block would have fit; when the top-ranked block cannot fit at all, emitting its most relevant members (exact line slices) is graceful degradation with no downside at larger budgets.
- **Run:** experiments/npkbench/runs/E005f-product-trim-devfast
- **Files changed:** `npk/pack/select.py`, `tests/test_top_block_trim.py`, `tests/test_python_members.py`, `tests/test_compiled_contracts.py`, `benchmarks/contract_mutations.py`
- **Results:**

```json
{
 "design": "No schema change: the file is rebuilt from its stored blocks (exact spans), parsed once, and members are cut with the compiler's own _class_member_spans; members overlapping the block are clipped (a method straddling a chunk boundary stays eligible); children are ranked by BM25-style overlap with file-local IDF (works under the query_only reader).",
 "fix_hunk_recall_512_1K_2K_4K_8K_16K": {
  "no_trim": [
   0.123,
   0.285,
   0.44,
   0.479,
   0.523,
   0.607
  ],
  "product_trim": [
   0.262,
   0.358,
   0.44,
   0.479,
   0.523,
   0.607
  ],
  "two_pack_prototype": [
   0.254,
   0.367,
   0.44,
   0.479,
   null,
   null
  ]
 },
 "latency_ms_p50_1K": {
  "no_trim": 63,
  "trim": 69
 },
 "tests": "1238 passed; mutants definition_channel_disabled, definition_ambiguity_cap_ignored, top_block_trim_disabled assertion-killed",
 "tests_hunk_recall": {
  "no_trim": [
   0.033,
   0.035,
   0.064,
   0.141,
   0.24,
   0.309
  ],
  "product_trim": [
   0.04,
   0.04,
   0.064,
   0.141,
   0.24,
   0.309
  ]
 }
}
```

- **Decision:** Strict improvement on dev-fast: +13.9 / +7.3 points at 512 / 1K on the fix target, +0.7 / +0.5 on tests, identical selections at 2K-16K. Every emitted span is exact source with its own span; a note records the trim. enable_trim=False restores skipping.

## E006 — Implementation-first role prior (demote tests/docs/examples by a BM25 factor)

- **Status:** rejected
- **Hypothesis:** 57% of baseline tokens go to tests/docs while every fix edits implementation; a soft prior improves localization without dropping anything.
- **Run:** experiments/npkbench/runs/E005-cf-role-devfast-{fix,tests}
- **Results:**

```json
{
 "budgets": "1K/2K/4K/8K/16K, dev-fast",
 "fix_target_hunk_recall": {
  "defs+role0.5": [
   0.314,
   0.463,
   0.552,
   0.591,
   0.691
  ],
  "no_prior": [
   0.285,
   0.44,
   0.479,
   0.523,
   0.607
  ]
 },
 "tests_target_hunk_recall": {
  "defs+role0.5": [
   0.015,
   0.019,
   0.034,
   0.044,
   0.104
  ],
  "no_prior": [
   0.035,
   0.064,
   0.141,
   0.24,
   0.309
  ],
  "role0.5_without_defs": [
   0.015,
   0.019,
   0.029,
   0.053,
   0.111
  ]
 }
}
```

- **Decision:** Benchmark gaming, confirmed by attack: the fix-target gain is bought by nearly eliminating recall of where maintainers put regression tests (4K: 0.141 -> 0.034). Not a default. Could only return as an explicit caller-declared intent.
- **Follow-ups:** If revisited: caller-declared intent (implementation vs tests), never a silent default

## E008 — Role portfolio: per-role budget shares (impl/tests/docs), soft shares, pure test reservation

- **Status:** rejected
- **Hypothesis:** Baseline role mix is lexical accident; explicit shares filled in fused rank order improve both the fix and the tests target.
- **Run:** experiments/npkbench/runs/E008-portfolio-*, E008b-soft-portfolio-*, E008c-test-reservation-devfast
- **Results:**

```json
{
 "hard_shares_i70_t30_d0_fix_1K": 0.184,
 "product_fix": [
  0.285,
  0.44,
  0.479,
  0.523,
  0.607
 ],
 "product_tests": [
  0.035,
  0.064,
  0.141,
  0.24,
  0.309
 ],
 "pure_test_reservation_40": {
  "fix": [
   0.278,
   0.396,
   0.453,
   0.508,
   0.568
  ],
  "tests": [
   0.055,
   0.146,
   0.216,
   0.287,
   0.363
  ]
 },
 "soft_i60_t30_d10": {
  "fix": [
   0.278,
   0.392,
   0.472,
   0.534,
   0.596
  ],
  "tests": [
   0.044,
   0.119,
   0.172,
   0.273,
   0.34
  ]
 },
 "soft_i60_t40_d0": {
  "fix": [
   0.288,
   0.396,
   0.492,
   0.544,
   0.6
  ],
  "tests": [
   0.061,
   0.156,
   0.216,
   0.289,
   0.363
  ]
 }
}
```

- **Decision:** Attack by decomposition: the arms that improve both targets do so by demoting documentation, which NPK-Bench cannot falsify (it has no documentation target); giving docs 10-20% removes most of the gain, and a pure test reservation only transfers recall from fix to tests (two-target mean within noise). Hard shares also lose 10 points at 1K. Not promoted.
- **Follow-ups:** A documentation-target workload is needed before any docs demotion can be evaluated honestly

## E009 — Callee expansion from named-definition seeds

- **Status:** rejected
- **Hypothesis:** Bugs often live one call away from the API an issue names; a channel of unambiguous definitions called by the top definition-channel seeds ranks gold that lexical and definition channels miss.
- **Run:** experiments/npkbench/runs/E009-callee-devfast-{fix,tests}
- **Results:**

```json
{
 "fix": {
  "product": [
   0.285,
   0.44,
   0.479,
   0.523,
   0.607
  ],
  "seeds3": [
   0.275,
   0.43,
   0.484,
   0.532,
   0.617
  ],
  "seeds5_k120": [
   0.275,
   0.43,
   0.479,
   0.542,
   0.617
  ]
 },
 "tests": {
  "product": [
   0.035,
   0.064,
   0.141,
   0.24,
   0.309
  ],
  "seeds3": [
   0.035,
   0.059,
   0.134,
   0.185,
   0.274
  ]
 }
}
```

- **Decision:** Fix-target changes stay within +/-2 points (noise at n=103) and the tests target loses up to 5.5 points. Precise seeds do not rescue graph expansion here; gold is mostly named or lexically matched directly.

## E010 — Drop very-high-document-frequency terms from long queries

- **Status:** inconclusive
- **Hypothesis:** Common OR-terms make most blocks match (58% on Django) while contributing near-zero IDF; pruning them speeds up long queries without changing rankings much.
- **Run:** experiments/npkbench/runs/E010-dfprune-devfast-{fix,tests}
- **Results:**

```json
{
 "fix": {
  "all": [
   0.285,
   0.44,
   0.479,
   0.523,
   0.607
  ],
  "df5": [
   0.285,
   0.426,
   0.479,
   0.524,
   0.605
  ]
 },
 "lexical_stage_ms_p50_p95_under_load": {
  "all_terms": [
   62.0,
   230.0
  ],
  "df<=10%": [
   29.8,
   131.8
  ],
  "df<=5%": [
   21.1,
   80.0
  ]
 },
 "tests": {
  "all": [
   0.035,
   0.064,
   0.141,
   0.24,
   0.309
  ],
  "df5": [
   0.041,
   0.055,
   0.128,
   0.244,
   0.279
  ]
 }
}
```

- **Decision:** ~3x faster lexical stage for long queries with fix-target recall within noise, but up to -3 points on the tests target at 16K. Latency is not a bottleneck at this scale (~30 ms uncontended); not promoted. Revisit for interactive/agent loops on very large repositories.

## E011 — Learned pairwise re-ranker over the product's candidate pool

- **Status:** rejected
- **Hypothesis:** Gold is ranked first for 36% of issues but is in the top-100 pool for 79%; a pairwise logistic re-ranker over repository-agnostic candidate features closes part of that gap.
- **Files changed:** `benchmarks/npkbench/ltr.py`
- **Results:**

```json
{
 "all_features": {
  "fix": {
   "base": [
    0.136,
    0.311,
    0.476,
    0.524
   ],
   "ltr": [
    0.126,
    0.262,
    0.418,
    0.515
   ]
  },
  "tests": {
   "base": [
    0.058,
    0.078,
    0.107,
    0.204
   ],
   "ltr": [
    0.087,
    0.155,
    0.262,
    0.33
   ]
  }
 },
 "protocol": "leave-one-repository-out CV on dev-fast; pairs from both targets with equal query weight; any-gold-block recall with whole-block greedy fill at 512/1K/2K/4K",
 "role_blind_both": {
  "fix": [
   0.126,
   0.301,
   0.447,
   0.524
  ],
  "tests": [
   0.058,
   0.068,
   0.165,
   0.243
  ]
 },
 "role_blind_fix_only": {
  "fix": [
   0.126,
   0.32,
   0.456,
   0.524
  ],
  "tests": [
   0.058,
   0.068,
   0.117,
   0.155
  ]
 },
 "top_weights_all_features": {
  "file_best_rank": -0.566,
  "kind_chunk": -0.414,
  "kind_class": 0.442,
  "kind_section": -0.461,
  "role_doc": -0.631,
  "role_test": 0.509
 }
}
```

- **Decision:** With role features the model relearns documentation demotion and a fix->tests transfer (largest weights are role and doc-like kind proxies). Role-blind models do not beat the product's fused ranking (fix within +/-3 points). The remaining ranking headroom needs new evidence (semantic similarity, structure), not reweighting of existing channels.
- **Follow-ups:** H11: dense embeddings as a new evidence source, with content-addressed vector reuse across snapshots

## E013 — Sibling/near-duplicate collapse (measured before building)

- **Status:** rejected
- **Hypothesis:** Structurally repeated code (same method across DB backends) wastes a material share of the budget; collapsing siblings into one full copy plus references would reclaim it.
- **Results:**

```json
{
 "arm": "npk_default (E000b spans), dev-fast",
 "exact_duplicate_text_share": {
  "16K": 0.0,
  "4K": 0.0
 },
 "share_of_selected_tokens_in_same_name_blocks_across_files": {
  "16K": 0.031,
  "4K": 0.017
 }
}
```

- **Decision:** At most 3.1% of selected tokens could be reclaimed on this workload; not worth a new representation now. Revisit for repetitive/vendored corpora or conversation logs.

## M000 — Baseline: conversation memory (LongMemEval-S dev, 100 questions)

- **Status:** kept
- **Hypothesis:** Establish how well the unchanged product compiler/selector retrieves evidence turns from ~120K-token chat histories materialized as dated markdown sessions.
- **Run:** experiments/npkbench/runs/M000-memory-baseline-dev
- **Results:**

```json
{
 "by_type_turn_recall_1K": {
  "knowledge-update": 0.867,
  "multi-session": 0.552,
  "single-session-assistant": 0.833,
  "single-session-preference": 0.361,
  "single-session-user": 0.929,
  "temporal-reasoning": 0.601
 },
 "compile_s_mean": 0.25,
 "evidence_session_recall": {
  "1K": 0.868,
  "256": 0.756,
  "2K": 0.904,
  "4K": 0.925,
  "512": 0.802,
  "8K": 0.959
 },
 "evidence_turn_recall": {
  "1K": 0.688,
  "256": 0.529,
  "2K": 0.749,
  "4K": 0.795,
  "512": 0.612,
  "8K": 0.838
 },
 "oracle_tokens_mean": 188,
 "pack_mb_mean": 1.61,
 "query_ms_p50": 2.0
}
```

- **Decision:** Reference point for the second workload family. Weak spots: multi-session aggregation and implicit preferences.
- **Follow-ups:** session-diverse packing for multi-session questions; sub-turn granularity for long assistant turns

## M001 — Source-diverse packing (per-file score decay) for multi-session memory questions

- **Status:** rejected
- **Hypothesis:** Multi-session questions need evidence from several sessions; decaying a candidate's score by the number of already-selected blocks from its file spreads the budget and raises evidence recall.
- **Run:** experiments/npkbench/runs/M001-diversity-memory-dev
- **Results:**

```json
{
 "budgets": "256/512/1K/2K/4K/8K",
 "evidence_structure": "evidence turns adjacent in 6/714 cases; multi-evidence questions span >1 session in 283/297; 842 user vs 54 assistant evidence turns",
 "session_recall": {
  "control_1K": 0.868,
  "control_8K": 0.959,
  "penalty_0.5_1K": 0.883,
  "penalty_0.5_8K": 0.995
 },
 "turn_recall": {
  "control": [
   0.529,
   0.612,
   0.688,
   0.749,
   0.795,
   0.838
  ],
  "penalty_0.5": [
   0.509,
   0.542,
   0.53,
   0.583,
   0.629,
   0.719
  ],
  "penalty_1": [
   0.509,
   0.532,
   0.52,
   0.555,
   0.591,
   0.658
  ]
 }
}
```

- **Decision:** Turn recall falls 10-16 points: fused RRF scores are nearly flat (1/60..1/120), so any per-file decay reorders almost the whole ranking toward weakly matching fresh sessions. Session coverage rises but evidence turns are lost.
- **Follow-ups:** If diversity is revisited, apply it on raw BM25 scores with a relevance floor, not on RRF ranks

## M002 — Relevance-density ordering (fused score / tokens^alpha) before greedy fill

- **Status:** rejected
- **Hypothesis:** Conversation evidence sits in short user turns (median 80 tokens) while long assistant turns (p90 632) consume small budgets; preferring compact candidates raises evidence recall.
- **Run:** experiments/npkbench/runs/M002-density-memory-dev
- **Results:**

```json
{
 "budgets": "256/512/1K/2K/4K/8K",
 "single_session_assistant_turn_recall": {
  "alpha_0.25": [
   0.083,
   0.083,
   0.333,
   0.667,
   0.75,
   0.917
  ],
  "control": [
   0.083,
   0.5,
   0.833,
   0.833,
   0.917,
   0.917
  ]
 },
 "turn_recall": {
  "alpha_0.25": [
   0.495,
   0.661,
   0.763,
   0.842,
   0.864,
   0.884
  ],
  "alpha_0.5": [
   0.413,
   0.607,
   0.726,
   0.804,
   0.864,
   0.884
  ],
  "control": [
   0.529,
   0.612,
   0.688,
   0.749,
   0.795,
   0.838
  ]
 }
}
```

- **Decision:** Aggregate gain is a disguised role prior: it comes from LongMemEval's composition (842/896 evidence turns are user turns) and collapses the question type whose evidence is in long assistant turns (1K: 0.833 -> 0.333). Not a default. Pursue finer units for long turns instead.
- **Follow-ups:** paragraph-level splitting of long sections (keeps assistant evidence retrievable)

## M003 — Paragraph-level units for long conversation turns (data-level layout test)

- **Status:** rejected
- **Hypothesis:** Long assistant turns waste small budgets; one block per paragraph (turns > 1,200 chars) keeps assistant evidence retrievable without a length prior.
- **Run:** experiments/npkbench/runs/M003-paragraph-units-memory-dev
- **Results:**

```json
{
 "budgets": "256/512/1K/2K/4K/8K",
 "session_recall_1K": {
  "paragraph_units": 0.901,
  "turn_units": 0.868
 },
 "turn_recall": {
  "paragraph_units": [
   0.44,
   0.601,
   0.667,
   0.76,
   0.831,
   0.838
  ],
  "turn_units": [
   0.529,
   0.612,
   0.688,
   0.749,
   0.795,
   0.838
  ]
 }
}
```

- **Decision:** Mixed: +1.1/+3.6 at 2K/4K and better session coverage, but -8.9/-1.1/-2.1 at 256/512/1K. Turn-level units stay; no compiler change.

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
| E006 | 2026-09-26 | Implementation-first role prior (demote tests/docs/examples by a BM25 factor) | **rejected** | Benchmark gaming, confirmed by attack: the fix-target gain is bought by nearly eliminating recall of where maintainers put regression tests (4K: 0.141 -> 0.034). Not a default. Could only return as an explicit caller-declared intent. |
| E013 | 2026-09-26 | Sibling/near-duplicate collapse (measured before building) | **rejected** | At most 3.1% of selected tokens could be reclaimed on this workload; not worth a new representation now. Revisit for repetitive/vendored corpora or conversation logs. |
| M000 | 2026-09-26 | Baseline: conversation memory (LongMemEval-S dev, 100 questions) | **kept** | Reference point for the second workload family. Weak spots: multi-session aggregation and implicit preferences. |

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

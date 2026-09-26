# NPK-Bench experiment history

Generated from `EXPERIMENTS.jsonl` by `python -m benchmarks.npkbench.expdb render`.
Do not edit by hand.

| ID | Date | Title | Status | Reason |
|---|---|---|---|---|
| E000 | 2026-09-26 | Baseline: product as received on NPK-Bench dev-fast | **kept** | Reference point. Ranking (not packing) is the dominant loss; ~45% of selected tokens are docs/tests; 46/103 snapshots need blocker removal to compile. |
| E001 | 2026-09-26 | Compile speed: parse Python once, statement-only raise walk, memoized term analysis | **kept** | 1.49x faster (not the >=2x expected: cProfile overstated pure-Python call overhead) with logically identical packs on real Django; kept. |
| E001b | 2026-09-26 | Cache joined per-word analysis strings in analyzed_text | **rejected** | No measurable gain without the profiler (within noise). Reverted to keep the simpler code. Lesson: confirm profiler-guided micro-optimizations with uninstrumented paired timing. |
| E002 | 2026-09-26 | Definition channel: identifiers a query names resolve to their defining blocks (held-out confirmed) | **kept** | Largest confirmed improvement: +5.7 to +10.3 points of held-out fix-target recall at every budget and +18.8 points of file recall at 2K, about 3x the tests-target cost; the two-target mean improves at every budget. Kept as default with the tradeoff documented. |
| E003 | 2026-09-26 | File-level evidence aggregation (block score + alpha * file top-3 sum) | **rejected** | No significant gain at any budget; alpha 1.0 hurts at 16K. Discarded. File recall even drops at 4K+ (0.524 vs 0.592). |
| E004 | 2026-09-26 | Skip and report never-indexed unindexable files instead of aborting the build | **kept** | Product can now compile every dev-fast snapshot, with explicit per-file reports and identical retrieval. |
| E005 | 2026-09-26 | Rank coarse blocks, emit only the best-matching K method-level children of large blocks | **rejected** | Helps only at 1K; loses 5-10 pts at 2K-16K on the fix target: trimming blocks that would have fit drops gold lines (non-top children, class-level lines, class-end insertions) more often than the freed budget recovers. Follow-up E005c trims only blocks that no longer fit. |
| E005c | 2026-09-26 | Top-block fit-or-trim: an oversized top-ranked Python block degrades to its best member spans | **kept** | Strict improvement on dev-fast: +13.9 / +7.3 points at 512 / 1K on the fix target, +0.7 / +0.5 on tests, identical selections at 2K-16K. Every emitted span is exact source with its own span; a note records the trim. enable_trim=False restores skipping. |
| E006 | 2026-09-26 | Implementation-first role prior (demote tests/docs/examples by a BM25 factor) | **rejected** | Benchmark gaming, confirmed by attack: the fix-target gain is bought by nearly eliminating recall of where maintainers put regression tests (4K: 0.141 -> 0.034). Not a default. Could only return as an explicit caller-declared intent. |
| E008 | 2026-09-26 | Role portfolio: per-role budget shares (impl/tests/docs), soft shares, pure test reservation | **rejected** | Attack by decomposition: the arms that improve both targets do so by demoting documentation, which NPK-Bench cannot falsify (it has no documentation target); giving docs 10-20% removes most of the gain, and a pure test reservation only transfers recall from fix to tests (two-target mean within noise). Hard shares also lose 10 points at 1K. Not promoted. |
| E009 | 2026-09-26 | Callee expansion from named-definition seeds | **rejected** | Fix-target changes stay within +/-2 points (noise at n=103) and the tests target loses up to 5.5 points. Precise seeds do not rescue graph expansion here; gold is mostly named or lexically matched directly. |
| E010 | 2026-09-26 | Drop very-high-document-frequency terms from long queries | **inconclusive** | ~3x faster lexical stage for long queries with fix-target recall within noise, but up to -3 points on the tests target at 16K. Latency is not a bottleneck at this scale (~30 ms uncontended); not promoted. Revisit for interactive/agent loops on very large repositories. |
| E011 | 2026-09-26 | Learned pairwise re-ranker over the product's candidate pool | **rejected** | With role features the model relearns documentation demotion and a fix->tests transfer (largest weights are role and doc-like kind proxies). Role-blind models do not beat the product's fused ranking (fix within +/-3 points). The remaining ranking headroom needs new evidence (semantic similarity, structure), not reweighting of existing channels. |
| E012 | 2026-09-26 | Dense similarity (MiniLM, bge-small) fused with the product's top-100 pool order | **rejected** | Budget-dependent trade-off that fails the declared rule. bge-small vs product (dev-fast, paired): fix -9.2 [-17.5,-1.0] at 1K and -10.8 [-18.1,-3.9] at 2K, +2.6/+3.1 (n.s.) at 8K/16K; tests +5.3 [+1.6,+9.6] at 1K, +7.5 at 2K, +5.6 at 16K; docs (docs-3 rescored, 13 tasks) 0.000->0.154 at 1K, 0.538->0.692 at 16K. Utility U = -2.7/-2.1/+3.5/+7.6/+9.9 points at 1K-16K: negative at small budgets. Fusing at equal weight with the whole pool order halves every product channel's influence; MiniLM and a sharper dense weight (k=30) are worse on fix. Query-time encoding of 100 blocks costs seconds per query on CPU (37 s p50 cold). |
| E012b | 2026-09-26 | Dense similarity as one channel inside the product's RRF (pool of 100) | **inconclusive** | bge-small passes the quality rule, barely at 1K; the cost keeps it out of the default. bge vs product (dev-fast): fix -3.9/-3.4/-0.5/+4.2/+4.2 (none significant), tests +3.4*/+6.4*/+2.8/+1.8/+2.9, docs (13 tasks) +7.7/+15.4/+7.7/+23.1/+15.4; utility +0.2/+4.3/+3.0/+8.0/+8.4 points. MiniLM fails (fix -5.8*/-7.8* at 1-2K; utility -3.9 at 1K). A product form needs bge vectors for every block (compile time on Django rises from ~15 s to 10+ minutes on CPU) or query-time pool encoding (seconds per cold query). Candidate for an opt-in semantic mode (swap MiniLM for bge-small, pool-channel form); not a default. |
| E013 | 2026-09-26 | Sibling/near-duplicate collapse (measured before building) | **rejected** | At most 3.1% of selected tokens could be reclaimed on this workload; not worth a new representation now. Revisit for repetitive/vendored corpora or conversation logs. |
| E014 | 2026-09-26 | Source scan without pathlib relative_to/is_relative_to (update latency) | **kept** | 1.5-2.5x faster updates on a large repository with identical artifacts. Remaining one-file update cost is the global digest over FTS storage (future: incremental global integrity). |
| E015 | 2026-09-26 | Documentation target for NPK-Bench (docs-1) and first docs-cost measurement | **inconclusive** | Superseded by E015b. Inspection of the docs-1 gold found construction errors: the upstream-commit rule (first commit after base touching every fix file) picked a mass-reformat commit for pytest-5103 (19 doc example files) and a deprecation sweep for matplotlib-24265, and counted CONTRIBUTORS.txt and doc/users/prev_whats_new as topical docs. Directionally, documentation demotion collapsed docs recall (e006_role05: 0.000/0.000/0.000/0.011/0.063 at 1K-16K vs npk_default 0.000/0.092/0.236/0.276/0.425), and definitions+trim cost -9.2 points at 1K (CI [-19.5,-1.1], 0 wins/4 losses) and -6.9 at 8K. docs-3 (patch-overlap commit identification, widening only to the introducing PR merge, prose-only) is the corrected target; docs-2 was built but found to swallow branch-integration merges before any use. |
| E015b | 2026-09-26 | Docs target docs-3: documentation cost of role priors and of the definition channel | **kept** | docs-3 is kept as NPK-Bench's third target. (a) Demotion is decisively harmful: e006_role05 vs product on dev docs -14.1/-30.1/-37.2/-40.4 points at 2K-16K (CIs exclude zero, 0 wins / 5-12 losses), confirming the E006/E008 rejections on evidence rather than suspicion. (b) The definition channel costs docs: dev -10.3 [-21.8,-1.3] at 1K; held-out (33 tasks, confirmation only) -12.1 [-24.2,-3.0] at 2K and -10.1 [-21.2,-1.0] at 4K. Under the declared utility E002 stays net positive (fix gains of 8-10 points dominate the 0.087-weighted docs loss). Top-block trimming is docs-neutral (held-out identical). |
| E016 | 2026-09-26 | Test-mate prototype: insert the test block mirroring the top implementation file | **rejected** | Superseded by E016b. The prototype re-filled the budget itself without top-block trimming, so its -6.3 fix points at 1K were mostly the missing trim, not the insertion; its tests gains (+10.8 [+5.2,+17.0] at 2K for position 1) motivated the product-form E016b. |
| E016b | 2026-09-26 | Test mate in the product selector (placed right after the top implementation block) | **running** | Passes the declared rule on dev-fast (103 tasks, paired vs the same selector with enable_test_mate=False): tests +3.7 [+1.0,+7.3] at 1K (6 wins/0 losses), +7.0 [+2.1,+12.3] at 2K (12/2), +4.9 [0.0,+10.2] at 4K, +2.9/+2.8 at 8K/16K; fix 0.0/-2.4/-1.9/-1.0/-0.5 (none significant); docs 0 except -7.7 at 4K (one task). Utility U = +3.7/+4.5/+2.3/+1.9/+2.2 points. Latency: about +10 ms uncontended on Django after caching parsed test paths and reusing the deep lexical ranking (selections identical on all 515). Held-out confirmation (H001) queued before promotion. |
| E017 | 2026-09-26 | Context map: a budget share for ranked locations listed without text | **kept** | Kept as an opt-in output mode (select(map_share=...), --map-share), not a default: full-text recall falls as the map share grows. With 25% of the budget as a map (dev-fast, paired vs the product's full text): locatable fix recall +5.3/+4.4/+9.6/+11.3/+9.7 points at 1K-16K (all CIs exclude zero), tests +2.1/+8.8/+9.0/+7.4/+6.5, docs (13 tasks) 0.000->0.077 at 1K, 0.231->0.462 at 4K; full-text fix recall -4.6/-5.8/-2.9/-3.4/-3.6. A 25% map at 2K locates 0.484 of fix hunks, the product's full text at 4K 0.479. Map only (100%): 0.515 located at 1K vs 0.358 in text. |
| E018 | 2026-09-26 | Documentation channel on top of reST sectioning (E019) | **rejected** | Built on E019, which was rejected. On docs (dev, 26 tasks) the channel added +10.3/+5.1/+7.7/+3.8/-2.6 points over E019 alone, but the combination only matched the main compiler beyond 1K. The channel alone on the main compiler was tested as E018b. The code-target run of this combination was stopped as superseded. |
| E018b | 2026-09-26 | Documentation channel (named entities -> reST object directives) on the main compiler | **rejected** | Trades code for documentation. Docs (dev, 26 tasks): +14.1 [+2.6,+26.9] points at 1K (5 wins/0 losses), +5.8 at 2K, -2.6/-1.3/0 beyond. Dev-fast code targets vs the same selector without the channel: fix -2.4/-1.0/-5.3 [-9.7,-1.5]/-1.0/0.0 (0 wins/6 losses at 4K), tests -0.2/-1.9/-3.9 [-7.8,-1.0]/-1.6/-0.6. Utility -1.9/-2.2/-9.9/-2.6/-0.6 points: negative at every budget. Django documents nearly every entity, so the channel lifts documentation for most queries at the expense of the code the issue is about; documentation matters for 8.7% of tasks. |
| E019 | 2026-09-26 | Split .txt files with reST section structure as reST (Django documentation) | **rejected** | No gain on any target. docs (dev, 26 tasks): +3.8/-2.6/-10.9/-3.8/-1.3 points at 1K-16K, none significant (2 wins/5 losses at 4K); dev-fast vs the same selector on the main compiler: fix 0.0/-1.9/-1.9/+1.0/0.0, tests -0.5/0.0/-0.5/+1.5/+1.0, docs 0/0/-7.7/0/-7.7 (13 tasks); utility -0.5/-1.9/-3.1/+2.4/+0.3 points. Compile time +15% (17.3 s vs 15.0 s per Django pack) from more, smaller blocks. Smaller named sections do not rank the edited lines better than windows do. |
| E022 | 2026-09-26 | Segment-aware lexical retrieval: separate channels for issue prose and code | **rejected** | Fails the declared rule at 1K. e022_split vs product (dev-fast): fix -2.4/-2.4/+2.4/+2.6/0.0 (none significant), tests +1.8/+4.4/+5.3/+3.3/+5.3 (significant at 16K), docs 0/+7.7/0/+7.7/0; utility -0.7/+2.6/+7.6/+6.6/+5.3 points. Adding only a code or only a prose channel to the full-query channel is weaker (full_plus_prose: fix -4.4 at 2K, significant). The tests gain overlaps what the test mate (E016b) already recovers; not tuned further on dev-fast to avoid fitting variants to it. |
| E023 | 2026-09-26 | Import-aware entity extraction and prose-weighted definition votes | **rejected** | No measurable effect. A reimplementation control reproduced the product exactly (all 515 selections). Import-aware tail extraction vs product (dev-fast): fix -0.5/-0.5/+1.5/-0.5/0.0, tests 0.0/+0.5/0.0/+1.9/-0.5, at most 4 tasks changed per budget; code-half weighting and the combination are equally flat (utility within +-2 points, mixed sign). The ambiguity cap already discards most module-path names, so the traced failure is rare in aggregate. The simpler product stays. |
| M000 | 2026-09-26 | Baseline: conversation memory (LongMemEval-S dev, 100 questions) | **kept** | Reference point for the second workload family. Weak spots: multi-session aggregation and implicit preferences. |
| M001 | 2026-09-26 | Source-diverse packing (per-file score decay) for multi-session memory questions | **rejected** | Turn recall falls 10-16 points: fused RRF scores are nearly flat (1/60..1/120), so any per-file decay reorders almost the whole ranking toward weakly matching fresh sessions. Session coverage rises but evidence turns are lost. |
| M002 | 2026-09-26 | Relevance-density ordering (fused score / tokens^alpha) before greedy fill | **rejected** | Aggregate gain is a disguised role prior: it comes from LongMemEval's composition (842/896 evidence turns are user turns) and collapses the question type whose evidence is in long assistant turns (1K: 0.833 -> 0.333). Not a default. Pursue finer units for long turns instead. |
| M003 | 2026-09-26 | Paragraph-level units for long conversation turns (data-level layout test) | **rejected** | Mixed: +1.1/+3.6 at 2K/4K and better session coverage, but -8.9/-1.1/-2.1 at 256/512/1K. Turn-level units stay; no compiler change. |
| M004 | 2026-09-26 | Dense similarity on conversation memory (pool fusion, bge-small / MiniLM) | **running** | Significant gains on memory-dev (100 questions): bge-small +4.1/+3.4/+4.3/+7.0/+7.7/+5.8 points at 256-8K (CI excludes zero at 2K, 4K, 8K); MiniLM +4.4/+1.4/+1.7/+4.7/+4.4/+4.1 (significant at 4K, 8K). By type (bge): multi-session +8 to +13, single-session-preference +17 to +22, temporal +5 to +13; knowledge-update -3 to -13 at 256-1K. The same fusion hurts code at small budgets (E012), so it cannot be a global default. Productization pending: M006 measures the shipped optional semantic/hybrid mode (MiniLM, whole-corpus channel) on the same questions; E012b tests the one-channel form on code. |

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

## E002 — Definition channel: identifiers a query names resolve to their defining blocks (held-out confirmed)

- **Status:** kept
- **Hypothesis:** Issue text names the code it concerns; resolving code-like identifiers against the definition-only symbol index and fusing their defining blocks into RRF ranks the definition above documentation and tests that repeat the prose.
- **Run:** experiments/npkbench/runs/E002H-heldout (heldout, 407 tasks); dev-fast runs E000b/E002b/E005
- **Commit:** b9f4732
- **Files changed:** `npk/pack/select.py`, `tests/test_definition_channel.py`, `tests/test_compiled_contracts.py`
- **Results:**

```json
{
 "dev_fast_fix": {
  "defs": [
   0.285,
   0.44,
   0.479,
   0.523,
   0.607
  ],
  "no_defs": [
   0.209,
   0.301,
   0.408,
   0.474,
   0.544
  ]
 },
 "heldout_fix_file_recall_2K": {
  "defs": 0.538,
  "no_defs": 0.35
 },
 "heldout_fix_hunk_recall_1K_2K_4K_8K_16K": {
  "defs": [
   0.193,
   0.309,
   0.399,
   0.475,
   0.575
  ],
  "no_defs": [
   0.136,
   0.206,
   0.302,
   0.393,
   0.49
  ]
 },
 "heldout_fix_paired": {
  "16K": "+0.086 CI [+0.059,+0.115] wins 51 losses 11",
  "2K": "+0.103 CI [+0.071,+0.136] wins 66 losses 13"
 },
 "heldout_tests_hunk_recall": {
  "defs": [
   0.058,
   0.105,
   0.149,
   0.22,
   0.287
  ],
  "no_defs": [
   0.082,
   0.138,
   0.183,
   0.265,
   0.324
  ]
 },
 "heldout_tests_paired": {
  "2K": "-0.033 CI [-0.055,-0.012] wins 9 losses 32"
 },
 "note": "The held-out run straddled the output-identical E014 scanner change (two fingerprints; equality verified), so fingerprints_stable=false is expected.",
 "parameter_sweep": "ambiguity cap 3-25, strict/qualified extraction, channel length caps and half weight: within noise or pure fix->tests transfer"
}
```

- **Tradeoffs:** Significant loss on the tests target (-2.4 to -4.5 points held-out): definition blocks displace test blocks. enable_definitions=False restores the old ranking.
- **Decision:** Largest confirmed improvement: +5.7 to +10.3 points of held-out fix-target recall at every budget and +18.8 points of file recall at 2K, about 3x the tests-target cost; the two-target mean improves at every budget. Kept as default with the tradeoff documented.
- **Follow-ups:** E016: recover the tests-target loss structurally (test-mate of the top implementation file)

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

## E012 — Dense similarity (MiniLM, bge-small) fused with the product's top-100 pool order

- **Status:** rejected
- **Hypothesis:** Dense query-block similarity is evidence the lexical/definition/relation channels lack; fusing it into the pool order recovers gold that ranks in the pool but below the budget.
- **Baseline run:** experiments/npkbench/runs/E012-dense-devfast (npk_default, e012_pool_control arms)
- **Run:** experiments/npkbench/runs/E012-dense-devfast
- **Bench version:** npkbench-1.1 + docs-3 (rescored)
- **Results:**

```json
{
 "docs3_hunk_recall_1K_16K_13_tasks": {
  "e012_bge": [
   0.154,
   0.154,
   0.385,
   0.538,
   0.692
  ],
  "npk_default": [
   0.0,
   0.0,
   0.231,
   0.308,
   0.538
  ]
 },
 "fix_hunk_recall_1K_16K": {
  "e012_bge": [
   0.265,
   0.332,
   0.463,
   0.548,
   0.637
  ],
  "e012_minilm": [
   0.215,
   0.303,
   0.38,
   0.498,
   0.657
  ],
  "e012_pool_control": [
   0.28,
   0.45,
   0.489,
   0.532,
   0.613
  ],
  "npk_default": [
   0.358,
   0.44,
   0.479,
   0.523,
   0.607
  ]
 },
 "tests_hunk_recall_1K_16K": {
  "e012_bge": [
   0.093,
   0.139,
   0.179,
   0.27,
   0.365
  ],
  "e012_minilm": [
   0.079,
   0.128,
   0.216,
   0.267,
   0.352
  ],
  "npk_default": [
   0.04,
   0.064,
   0.141,
   0.24,
   0.309
  ]
 },
 "utility_bge_vs_product_1K_16K": [
  -0.027,
  -0.021,
  0.035,
  0.076,
  0.099
 ]
}
```

- **Tradeoffs:** Dense favors natural-language blocks (tests, docs) over code; helps at >=4K, hurts at <=2K.
- **Decision:** Budget-dependent trade-off that fails the declared rule. bge-small vs product (dev-fast, paired): fix -9.2 [-17.5,-1.0] at 1K and -10.8 [-18.1,-3.9] at 2K, +2.6/+3.1 (n.s.) at 8K/16K; tests +5.3 [+1.6,+9.6] at 1K, +7.5 at 2K, +5.6 at 16K; docs (docs-3 rescored, 13 tasks) 0.000->0.154 at 1K, 0.538->0.692 at 16K. Utility U = -2.7/-2.1/+3.5/+7.6/+9.9 points at 1K-16K: negative at small budgets. Fusing at equal weight with the whole pool order halves every product channel's influence; MiniLM and a sharper dense weight (k=30) are worse on fix. Query-time encoding of 100 blocks costs seconds per query on CPU (37 s p50 cold).
- **Follow-ups:** E012b: dense as one more channel inside the product's RRF (one of four), with the product's fill and trimming

## E012b — Dense similarity as one channel inside the product's RRF (pool of 100)

- **Status:** inconclusive
- **Hypothesis:** E012 fused dense at equal weight with the whole product order; as one channel among lexical/definition/relation it should keep the small-budget fix precision while adding tests/docs recall.
- **Run:** experiments/npkbench/runs/E012b-dense-channel-devfast
- **Results:**

```json
{
 "fix_1K_16K": {
  "bge_channel": [
   0.319,
   0.406,
   0.474,
   0.565,
   0.649
  ],
  "minilm_channel": [
   0.299,
   0.362,
   0.464,
   0.544,
   0.644
  ],
  "npk_default": [
   0.358,
   0.44,
   0.479,
   0.523,
   0.607
  ]
 },
 "tests_1K_16K": {
  "bge_channel": [
   0.074,
   0.128,
   0.169,
   0.258,
   0.338
  ],
  "npk_default": [
   0.04,
   0.064,
   0.141,
   0.24,
   0.309
  ]
 },
 "utility_bge": [
  0.002,
  0.043,
  0.03,
  0.08,
  0.084
 ]
}
```

- **Decision:** bge-small passes the quality rule, barely at 1K; the cost keeps it out of the default. bge vs product (dev-fast): fix -3.9/-3.4/-0.5/+4.2/+4.2 (none significant), tests +3.4*/+6.4*/+2.8/+1.8/+2.9, docs (13 tasks) +7.7/+15.4/+7.7/+23.1/+15.4; utility +0.2/+4.3/+3.0/+8.0/+8.4 points. MiniLM fails (fix -5.8*/-7.8* at 1-2K; utility -3.9 at 1K). A product form needs bge vectors for every block (compile time on Django rises from ~15 s to 10+ minutes on CPU) or query-time pool encoding (seconds per cold query). Candidate for an opt-in semantic mode (swap MiniLM for bge-small, pool-channel form); not a default.
- **Follow-ups:** If the shipped semantic mode is revisited (M006), evaluate bge-small in the pool-channel form as its encoder

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

## E014 — Source scan without pathlib relative_to/is_relative_to (update latency)

- **Status:** kept
- **Hypothesis:** A one-file update of Django spends 2.1 of 2.8 s (profiled) in scan_source, mostly pathlib relative_to/is_relative_to; string prefix checks on the same resolved paths are semantically identical and much cheaper.
- **Files changed:** `npk/pack/compile.py`
- **Results:**

```json
{
 "django_3.2K_files_update_seconds_median3": {
  "noop_quick": {
   "after": 0.384,
   "before": 0.978
  },
  "noop_strict": {
   "after": 0.679,
   "before": 1.303
  },
  "one_file_quick": {
   "after": 0.797,
   "before": 1.219
  },
  "one_file_strict": {
   "after": 1.052,
   "before": 1.531
  }
 },
 "fresh_compile_logically_identical": true,
 "security_contract": "every file is still resolved (Path.resolve) and rejected before any read if it escapes the root; tests mocking resolve/stat/read_bytes pass",
 "tests": "1238 passed"
}
```

- **Decision:** 1.5-2.5x faster updates on a large repository with identical artifacts. Remaining one-file update cost is the global digest over FTS storage (future: incremental global integrity).

## E015 — Documentation target for NPK-Bench (docs-1) and first docs-cost measurement

- **Status:** inconclusive
- **Hypothesis:** Documentation demotion (E006/E008 d0 arms) and the definition channel (E002) move recall away from topical documentation; a docs target built from the docs edited by the upstream fix commit makes that cost measurable instead of unfalsifiable.
- **Run:** experiments/npkbench/runs/E015-docs-target-dev
- **Bench version:** npkbench-1.1 + docs-1
- **Results:**

```json
{
 "docs_hunk_recall_dev_29": {
  "budgets": [
   1024,
   2048,
   4096,
   8192,
   16384
  ],
  "e002_defs_role05": [
   0.0,
   0.0,
   0.0,
   0.011,
   0.098
  ],
  "e006_role05": [
   0.0,
   0.0,
   0.0,
   0.011,
   0.063
  ],
  "e008b_soft_i60_t30_d10": [
   0.046,
   0.132,
   0.247,
   0.316,
   0.362
  ],
  "e008c_test40": [
   0.035,
   0.035,
   0.161,
   0.247,
   0.356
  ],
  "npk_default": [
   0.0,
   0.092,
   0.236,
   0.276,
   0.425
  ],
  "npk_nodefs": [
   0.092,
   0.109,
   0.247,
   0.345,
   0.425
  ],
  "npk_notrim": [
   0.035,
   0.092,
   0.236,
   0.276,
   0.425
  ]
 }
}
```

- **Decision:** Superseded by E015b. Inspection of the docs-1 gold found construction errors: the upstream-commit rule (first commit after base touching every fix file) picked a mass-reformat commit for pytest-5103 (19 doc example files) and a deprecation sweep for matplotlib-24265, and counted CONTRIBUTORS.txt and doc/users/prev_whats_new as topical docs. Directionally, documentation demotion collapsed docs recall (e006_role05: 0.000/0.000/0.000/0.011/0.063 at 1K-16K vs npk_default 0.000/0.092/0.236/0.276/0.425), and definitions+trim cost -9.2 points at 1K (CI [-19.5,-1.1], 0 wins/4 losses) and -6.9 at 8K. docs-3 (patch-overlap commit identification, widening only to the introducing PR merge, prose-only) is the corrected target; docs-2 was built but found to swallow branch-integration merges before any use.
- **Follow-ups:** E015b: re-run on docs-3 gold (dev) and E015c (heldout) for the definition channel's docs cost; E019: Django documents in .txt reST, which the compiler cuts into 60-line windows; split by sections; E018: resolve named entities to the reST object directives that document them

## E015b — Docs target docs-3: documentation cost of role priors and of the definition channel

- **Status:** kept
- **Hypothesis:** With a corrected documentation target, (a) documentation demotion costs documentation recall, and (b) the definition channel's code-first ranking displaces topical docs.
- **Run:** experiments/npkbench/runs/E015b-docs3-dev, experiments/npkbench/runs/E015c-docs3-heldout
- **Bench version:** npkbench-1.1 + docs-3
- **Results:**

```json
{
 "dev_docs_1K_16K": {
  "e002_defs_role05": [
   0.0,
   0.0,
   0.0,
   0.013,
   0.147
  ],
  "e006_role05": [
   0.0,
   0.0,
   0.0,
   0.013,
   0.109
  ],
  "e008b_soft_i60_t30_d10": [
   0.051,
   0.186,
   0.353,
   0.391,
   0.442
  ],
  "npk_default": [
   0.0,
   0.141,
   0.301,
   0.385,
   0.513
  ],
  "npk_nodefs": [
   0.103,
   0.16,
   0.314,
   0.462,
   0.513
  ],
  "npk_notrim": [
   0.038,
   0.141,
   0.301,
   0.385,
   0.513
  ]
 },
 "heldout_docs_1K_16K": {
  "npk_default": [
   0.137,
   0.165,
   0.305,
   0.517,
   0.602
  ],
  "npk_nodefs": [
   0.095,
   0.286,
   0.406,
   0.537,
   0.617
  ]
 }
}
```

- **Decision:** docs-3 is kept as NPK-Bench's third target. (a) Demotion is decisively harmful: e006_role05 vs product on dev docs -14.1/-30.1/-37.2/-40.4 points at 2K-16K (CIs exclude zero, 0 wins / 5-12 losses), confirming the E006/E008 rejections on evidence rather than suspicion. (b) The definition channel costs docs: dev -10.3 [-21.8,-1.3] at 1K; held-out (33 tasks, confirmation only) -12.1 [-24.2,-3.0] at 2K and -10.1 [-21.2,-1.0] at 4K. Under the declared utility E002 stays net positive (fix gains of 8-10 points dominate the 0.087-weighted docs loss). Top-block trimming is docs-neutral (held-out identical).
- **Follow-ups:** E019 (reST sections for .txt) and E018 (documentation channel) aim to recover the definition channel's docs cost

## E016 — Test-mate prototype: insert the test block mirroring the top implementation file

- **Status:** rejected
- **Hypothesis:** The definition channel's tests-target cost (E002) can be recovered structurally: the test file that mirrors the top-ranked implementation file by path convention holds the regression test.
- **Run:** experiments/npkbench/runs/E016-testmate-devfast
- **Decision:** Superseded by E016b. The prototype re-filled the budget itself without top-block trimming, so its -6.3 fix points at 1K were mostly the missing trim, not the insertion; its tests gains (+10.8 [+5.2,+17.0] at 2K for position 1) motivated the product-form E016b.
- **Follow-ups:** E016b: product-form test mate inside the selector

## E016b — Test mate in the product selector (placed right after the top implementation block)

- **Status:** running
- **Hypothesis:** Placing the best query-matching block of the mirroring test file right after the top implementation block, inside the product's fill and trimming, recovers tests-target recall without a significant fix-target cost.
- **Run:** experiments/npkbench/runs/E016b-test-mate-product-devfast
- **Files changed:** `npk/pack/select.py`, `benchmarks/npkbench/arms.py`, `tests/test_test_mate.py`
- **Results:**

```json
{
 "fix_1K_16K": {
  "mate": [
   0.358,
   0.416,
   0.46,
   0.513,
   0.602
  ],
  "nomate": [
   0.358,
   0.44,
   0.479,
   0.523,
   0.607
  ]
 },
 "tests_1K_16K": {
  "mate": [
   0.077,
   0.134,
   0.19,
   0.27,
   0.337
  ],
  "nomate": [
   0.04,
   0.064,
   0.141,
   0.24,
   0.309
  ]
 },
 "utility_1K_16K": [
  0.0368,
  0.0446,
  0.0228,
  0.0191,
  0.0223
 ]
}
```

- **Decision:** Passes the declared rule on dev-fast (103 tasks, paired vs the same selector with enable_test_mate=False): tests +3.7 [+1.0,+7.3] at 1K (6 wins/0 losses), +7.0 [+2.1,+12.3] at 2K (12/2), +4.9 [0.0,+10.2] at 4K, +2.9/+2.8 at 8K/16K; fix 0.0/-2.4/-1.9/-1.0/-0.5 (none significant); docs 0 except -7.7 at 4K (one task). Utility U = +3.7/+4.5/+2.3/+1.9/+2.2 points. Latency: about +10 ms uncontended on Django after caching parsed test paths and reusing the deep lexical ranking (selections identical on all 515). Held-out confirmation (H001) queued before promotion.
- **Follow-ups:** H001: held-out confirmation (tests, docs, fix) together with E005c trimming

## E017 — Context map: a budget share for ranked locations listed without text

- **Status:** kept
- **Hypothesis:** Callers that can open files need to know where relevant code is more than they need its text; a one-line-per-place map (path:start-end kind name, Python classes as members) of the ranking beyond the text selection locates more gold per token than full text.
- **Run:** experiments/npkbench/runs/E017-context-map-devfast
- **Files changed:** `npk/pack/select.py`, `npk/pack/__init__.py`, `npk/cli.py`, `tests/test_context_map.py`
- **Results:**

```json
{
 "fix_located_1K_16K": {
  "map10": [
   0.409,
   0.455,
   0.498,
   0.599,
   0.675
  ],
  "map100": [
   0.515,
   0.583,
   0.665,
   0.704,
   0.714
  ],
  "map25": [
   0.411,
   0.484,
   0.574,
   0.636,
   0.704
  ],
  "map50": [
   0.46,
   0.529,
   0.607,
   0.694,
   0.704
  ]
 },
 "fix_text_1K_16K": {
  "map0": [
   0.358,
   0.44,
   0.479,
   0.523,
   0.607
  ],
  "map25": [
   0.312,
   0.382,
   0.45,
   0.489,
   0.571
  ],
  "map50": [
   0.262,
   0.358,
   0.44,
   0.479,
   0.523
  ]
 },
 "tests_located_1K_16K": {
  "map0": [
   0.04,
   0.064,
   0.141,
   0.24,
   0.309
  ],
  "map25": [
   0.061,
   0.152,
   0.231,
   0.315,
   0.375
  ]
 }
}
```

- **Tradeoffs:** Located is not read: the caller must open the listed spans. Useful for agents with file access; for a single-call context the text-only default stays better.
- **Decision:** Kept as an opt-in output mode (select(map_share=...), --map-share), not a default: full-text recall falls as the map share grows. With 25% of the budget as a map (dev-fast, paired vs the product's full text): locatable fix recall +5.3/+4.4/+9.6/+11.3/+9.7 points at 1K-16K (all CIs exclude zero), tests +2.1/+8.8/+9.0/+7.4/+6.5, docs (13 tasks) 0.000->0.077 at 1K, 0.231->0.462 at 4K; full-text fix recall -4.6/-5.8/-2.9/-3.4/-3.6. A 25% map at 2K locates 0.484 of fix hunks, the product's full text at 4K 0.479. Map only (100%): 0.515 located at 1K vs 0.358 in text.
- **Follow-ups:** Held-out confirmation of the located gain; Measure agent task success with and without the map (needs an agent harness)

## E018 — Documentation channel on top of reST sectioning (E019)

- **Status:** rejected
- **Hypothesis:** reST object directives (.. method::, .. setting::, .. class:: ...) declare which entity a page documents; resolving the entities an issue names to those directives (a second definition-style channel over 'documents' symbols) would recover the definition channel's documentation cost (E015b) without demoting anything.
- **Run:** experiments/npkbench/runs/E018-doc-entities-dev-docs
- **Decision:** Built on E019, which was rejected. On docs (dev, 26 tasks) the channel added +10.3/+5.1/+7.7/+3.8/-2.6 points over E019 alone, but the combination only matched the main compiler beyond 1K. The channel alone on the main compiler was tested as E018b. The code-target run of this combination was stopped as superseded.

## E018b — Documentation channel (named entities -> reST object directives) on the main compiler

- **Status:** rejected
- **Hypothesis:** reST object directives (.. method::, .. setting::, .. class:: ...) declare which entity a page documents; resolving the entities an issue names to those directives (a second definition-style channel over 'documents' symbols) would recover the definition channel's documentation cost (E015b) without demoting anything.
- **Baseline run:** experiments/npkbench/runs/E015b-docs3-dev, experiments/npkbench/runs/E016b-test-mate-product-devfast (npk_nomate)
- **Run:** experiments/npkbench/runs/E018b-doc-channel-dev-docs, experiments/npkbench/runs/E018b-doc-channel-devfast
- **Files changed:** `npk/pack/compile.py`, `npk/pack/select.py`, `tests/test_doc_entity_channel.py`
- **Decision:** Trades code for documentation. Docs (dev, 26 tasks): +14.1 [+2.6,+26.9] points at 1K (5 wins/0 losses), +5.8 at 2K, -2.6/-1.3/0 beyond. Dev-fast code targets vs the same selector without the channel: fix -2.4/-1.0/-5.3 [-9.7,-1.5]/-1.0/0.0 (0 wins/6 losses at 4K), tests -0.2/-1.9/-3.9 [-7.8,-1.0]/-1.6/-0.6. Utility -1.9/-2.2/-9.9/-2.6/-0.6 points: negative at every budget. Django documents nearly every entity, so the channel lifts documentation for most queries at the expense of the code the issue is about; documentation matters for 8.7% of tasks.

## E019 — Split .txt files with reST section structure as reST (Django documentation)

- **Status:** rejected
- **Hypothesis:** Django writes its documentation as reST in .txt files, which the compiler cut into anonymous 60-line windows; section blocks named by heading path would rank topical documentation better.
- **Baseline run:** experiments/npkbench/runs/E015b-docs3-dev, experiments/npkbench/runs/E016b-test-mate-product-devfast (npk_nomate)
- **Run:** experiments/npkbench/runs/E019-rst-text-dev-docs, experiments/npkbench/runs/E019-rst-text-devfast
- **Files changed:** `npk/pack/compile.py`
- **Decision:** No gain on any target. docs (dev, 26 tasks): +3.8/-2.6/-10.9/-3.8/-1.3 points at 1K-16K, none significant (2 wins/5 losses at 4K); dev-fast vs the same selector on the main compiler: fix 0.0/-1.9/-1.9/+1.0/0.0, tests -0.5/0.0/-0.5/+1.5/+1.0, docs 0/0/-7.7/0/-7.7 (13 tasks); utility -0.5/-1.9/-3.1/+2.4/+0.3 points. Compile time +15% (17.3 s vs 15.0 s per Django pack) from more, smaller blocks. Smaller named sections do not rank the edited lines better than windows do.

## E022 — Segment-aware lexical retrieval: separate channels for issue prose and code

- **Status:** rejected
- **Hypothesis:** 80/103 issues contain code (median 36% of words); one OR query lets long reproduction scripts outvote the prose. Separate prose and code lexical channels give each an equal RRF vote.
- **Run:** experiments/npkbench/runs/E022-segments-devfast
- **Decision:** Fails the declared rule at 1K. e022_split vs product (dev-fast): fix -2.4/-2.4/+2.4/+2.6/0.0 (none significant), tests +1.8/+4.4/+5.3/+3.3/+5.3 (significant at 16K), docs 0/+7.7/0/+7.7/0; utility -0.7/+2.6/+7.6/+6.6/+5.3 points. Adding only a code or only a prose channel to the full-query channel is weaker (full_plus_prose: fix -4.4 at 2K, significant). The tests gain overlaps what the test mate (E016b) already recovers; not tuned further on dev-fast to avoid fitting variants to it.

## E023 — Import-aware entity extraction and prose-weighted definition votes

- **Status:** rejected
- **Hypothesis:** Failure analysis (django-11964): module paths of import statements in reproduction code (django.utils.translation) become entities and give strong definition votes to unrelated blocks (trans_real.translation, OGRGeomType.django, TestCase). Dropping import module paths and lowercase non-final dotted parts, and halving votes for names that occur only in code segments, would sharpen the definition channel.
- **Run:** experiments/npkbench/runs/E023-entities-devfast
- **Decision:** No measurable effect. A reimplementation control reproduced the product exactly (all 515 selections). Import-aware tail extraction vs product (dev-fast): fix -0.5/-0.5/+1.5/-0.5/0.0, tests 0.0/+0.5/0.0/+1.9/-0.5, at most 4 tasks changed per budget; code-half weighting and the combination are equally flat (utility within +-2 points, mixed sign). The ambiguity cap already discards most module-path names, so the traced failure is rare in aggregate. The simpler product stays.

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

## M004 — Dense similarity on conversation memory (pool fusion, bge-small / MiniLM)

- **Status:** running
- **Hypothesis:** Conversation-memory questions are natural-language and paraphrase their evidence (21 of 191 evidence turns at 2K are never retrieved lexically); dense similarity fused with the lexical pool order recovers evidence.
- **Run:** experiments/npkbench/runs/M004-dense-memory-dev
- **Results:**

```json
{
 "bge_minus_default_ci95": {
  "1024": [
   -0.015,
   0.102
  ],
  "2048": [
   0.028,
   0.116
  ],
  "256": [
   -0.009,
   0.095
  ],
  "4096": [
   0.028,
   0.13
  ],
  "512": [
   -0.044,
   0.109
  ],
  "8192": [
   0.021,
   0.101
  ]
 },
 "hunk_recall_256_8K": {
  "e012_bge": [
   0.571,
   0.646,
   0.73,
   0.819,
   0.872,
   0.895
  ],
  "e012_minilm": [
   0.574,
   0.626,
   0.705,
   0.796,
   0.839,
   0.879
  ],
  "npk_default": [
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

- **Decision:** Significant gains on memory-dev (100 questions): bge-small +4.1/+3.4/+4.3/+7.0/+7.7/+5.8 points at 256-8K (CI excludes zero at 2K, 4K, 8K); MiniLM +4.4/+1.4/+1.7/+4.7/+4.4/+4.1 (significant at 4K, 8K). By type (bge): multi-session +8 to +13, single-session-preference +17 to +22, temporal +5 to +13; knowledge-update -3 to -13 at 256-1K. The same fusion hurts code at small budgets (E012), so it cannot be a global default. Productization pending: M006 measures the shipped optional semantic/hybrid mode (MiniLM, whole-corpus channel) on the same questions; E012b tests the one-channel form on code.
- **Follow-ups:** M006: shipped hybrid mode on memory-dev; If a dense form wins memory without hurting code, make it the recommended mode for conversation/prose packs

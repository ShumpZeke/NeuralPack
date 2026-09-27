# NPK-Bench experiment history

Generated from `EXPERIMENTS.jsonl` by `python -m benchmarks.npkbench.expdb render`.
Do not edit by hand.

| ID | Date | Title | Status | Reason |
|---|---|---|---|---|
| B001 | 2026-09-26 | Standard-RAG baseline: Okapi BM25 over fixed 60-line chunks (whole and split identifiers) | **kept** | Kept as a permanent baseline arm. Held-out (407 issues), fix recall: product 0.230/0.309/0.399/0.475/0.575 vs chunk BM25 0.102/0.146/0.190/0.227/0.262 (+12.8 to +31.4 points) and identifier-split chunk BM25 0.101/0.149/0.217/0.267/0.321 (+12.9 to +25.5); every CI excludes zero. Even the pre-loop product (0.136/0.206/0.302/0.393/0.490) beat both. Tests: split baseline equal at 1-2K, product ahead from 8K (+5.7, +6.6 significant). Docs (33 issues): baseline ahead at 2K (+14.6 split, +21.4 whole; significant), equal from 8K. Dev-fast agrees on fix (+19 to +30 points). Memory-dev at 256-1K is not a fair comparison for 60-line chunks of long chat lines; B002 uses the common ~1,000-character chunker instead. |
| B002 | 2026-09-26 | Standard-RAG baseline with the common ~1,000-character chunker (identifier-split BM25) | **kept** | Kept as a baseline arm. Code (dev-fast): product fix +23.1/+24.6/+21.8/+19.7/+15.9 points at 1K-16K (all significant); tests within noise (baseline slightly ahead at 1-4K, product at 8-16K); docs (13 tasks) baseline far ahead (0.423 vs 0.000 at 2K). Memory (memory-dev): product +20.6 [+10.6,+30.3] at 256 and +13.9 [+5.0,+23.0] at 512, then 1K-4K within +-1 point and -3.8 (n.s.) at 8K; the semantic/hybrid mode leads at every budget (+25.1/+15.3/+6.0/+3.5/+3.4/+3.3). Documentation retrieval is NeuralPack's main open weakness: small prose units match issue text well, and code-first ranking (definition channel) gives docs up. |
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
| E016b | 2026-09-26 | Test mate in the product selector (placed right after the top implementation block) | **kept** | Kept as an opt-in mode (enable_test_mate=True, --test-mate); the held-out confirmation did not support a default change. Dev-fast: tests +3.7/+7.0/+4.9/+2.9/+2.8 points, fix changes not significant. Held-out H001 (407 issues; criteria committed before the run): tests +1.15 [+0.2,+2.3] / +3.8 [+1.6,+6.0] / +4.5 [+2.2,+7.1] / +3.6 [+2.0,+5.4] / +1.7 [+0.7,+2.9] points at 1K-16K (34 wins/6 losses at 2K); fix -1.15 [-2.2,-0.3] / -0.6 / -1.4 [-2.7,-0.2] / -0.3 / -0.6 [-1.3,-0.1]; docs ~0. Utility -0.012/+3.2/+2.8/+3.3/+1.0 points: negative (by 0.012 points) at 1K with a significant fix loss, so the pre-declared rule blocks a default change. A budget-gated variant (mate only at >=2K) is suggested by these numbers but must not be confirmed on the same held-out split. |
| E016c | 2026-09-26 | Budget-gated test mate as the default (on from 2048 tokens) | **kept** | Passes the criteria declared in NEXT_STEPS.md before HB01 (heldout-b, 400 fresh issues). Gated vs product: 1K identical by construction; tests +5.7 [+3.4,+8.1] / +6.0 [+3.7,+8.4] / +3.7 [+2.0,+5.5] / +2.3 [+1.0,+3.7] points at 2K-16K; fix -1.1 [-2.6,+0.3] / -0.9 [-2.0,+0.2] / -0.9 [-1.8,-0.1] / -0.4 [-1.0,-0.0]; utility 0.0/+4.5/+5.0/+2.8/+1.9. Significant fix losses occur only where utility is clearly positive. The new default equals the evaluated composition (mate off at 1K, evaluated mate from 2K) on all 515 dev-fast selections. enable_test_mate: None (default, gated) / True / False; CLI --test-mate auto/always/never; mutant test_mate_gate_ignored is killed. |
| E017 | 2026-09-26 | Context map: a budget share for ranked locations listed without text | **kept** | Kept as an opt-in output mode (select(map_share=...), --map-share), not a default: full-text recall falls as the map share grows. With 25% of the budget as a map (dev-fast, paired vs the product's full text): locatable fix recall +5.3/+4.4/+9.6/+11.3/+9.7 points at 1K-16K (all CIs exclude zero), tests +2.1/+8.8/+9.0/+7.4/+6.5, docs (13 tasks) 0.000->0.077 at 1K, 0.231->0.462 at 4K; full-text fix recall -4.6/-5.8/-2.9/-3.4/-3.6. A 25% map at 2K locates 0.484 of fix hunks, the product's full text at 4K 0.479. Map only (100%): 0.515 located at 1K vs 0.358 in text. |
| E018 | 2026-09-26 | Documentation channel on top of reST sectioning (E019) | **rejected** | Built on E019, which was rejected. On docs (dev, 26 tasks) the channel added +10.3/+5.1/+7.7/+3.8/-2.6 points over E019 alone, but the combination only matched the main compiler beyond 1K. The channel alone on the main compiler was tested as E018b. The code-target run of this combination was stopped as superseded. |
| E018b | 2026-09-26 | Documentation channel (named entities -> reST object directives) on the main compiler | **rejected** | Trades code for documentation. Docs (dev, 26 tasks): +14.1 [+2.6,+26.9] points at 1K (5 wins/0 losses), +5.8 at 2K, -2.6/-1.3/0 beyond. Dev-fast code targets vs the same selector without the channel: fix -2.4/-1.0/-5.3 [-9.7,-1.5]/-1.0/0.0 (0 wins/6 losses at 4K), tests -0.2/-1.9/-3.9 [-7.8,-1.0]/-1.6/-0.6. Utility -1.9/-2.2/-9.9/-2.6/-0.6 points: negative at every budget. Django documents nearly every entity, so the channel lifts documentation for most queries at the expense of the code the issue is about; documentation matters for 8.7% of tasks. |
| E019 | 2026-09-26 | Split .txt files with reST section structure as reST (Django documentation) | **rejected** | No gain on any target. docs (dev, 26 tasks): +3.8/-2.6/-10.9/-3.8/-1.3 points at 1K-16K, none significant (2 wins/5 losses at 4K); dev-fast vs the same selector on the main compiler: fix 0.0/-1.9/-1.9/+1.0/0.0, tests -0.5/0.0/-0.5/+1.5/+1.0, docs 0/0/-7.7/0/-7.7 (13 tasks); utility -0.5/-1.9/-3.1/+2.4/+0.3 points. Compile time +15% (17.3 s vs 15.0 s per Django pack) from more, smaller blocks. Smaller named sections do not rank the edited lines better than windows do. |
| E022 | 2026-09-26 | Segment-aware lexical retrieval: separate channels for issue prose and code | **rejected** | Fails the declared rule at 1K. e022_split vs product (dev-fast): fix -2.4/-2.4/+2.4/+2.6/0.0 (none significant), tests +1.8/+4.4/+5.3/+3.3/+5.3 (significant at 16K), docs 0/+7.7/0/+7.7/0; utility -0.7/+2.6/+7.6/+6.6/+5.3 points. Adding only a code or only a prose channel to the full-query channel is weaker (full_plus_prose: fix -4.4 at 2K, significant). The tests gain overlaps what the test mate (E016b) already recovers; not tuned further on dev-fast to avoid fitting variants to it. |
| E023 | 2026-09-26 | Import-aware entity extraction and prose-weighted definition votes | **rejected** | No measurable effect. A reimplementation control reproduced the product exactly (all 515 selections). Import-aware tail extraction vs product (dev-fast): fix -0.5/-0.5/+1.5/-0.5/0.0, tests 0.0/+0.5/0.0/+1.9/-0.5, at most 4 tasks changed per budget; code-half weighting and the combination are equally flat (utility within +-2 points, mixed sign). The ambiguity cap already discards most module-path names, so the traced failure is rare in aggregate. The simpler product stays. |
| E024 | 2026-09-26 | Bulk integrity leaves (one ordered scan per table) and batched framing | **rejected** | Correct but not worth its complexity. Digests are byte-identical (4 Django packs; new equality test across all local tables; two mutants killed), but paired compile timing gives 1.018x (12.86 -> 12.64 s median) and verify ~3% (9.4-9.8 s -> 8.8-9.3 s). The cold-pack microbenchmark (1.4 s -> 0.5 s) overstated the in-compile gain because sealing reads hot pages; verify is dominated by the deliberate FTS source-parity rebuild. Not merged: +40 lines in integrity-critical code for ~2%. |
| E025 | 2026-09-26 | Parameter sweep: BM25 field weights (E025), candidate depth (E026), RRF constant (E027) | **rejected** | Defaults sit near a local optimum; no setting passes the rule. Field weights: name x2 / path x2 / both x2 change fix by at most +3.2 points (both x2 at 16K, the only significant cell) while costing tests -1.7 at 4K (utility -1.4); halving name/path weights loses up to -2.4. Candidate depth: 30 hurts (fix -3.4 at 4K, significant); 120 and 240 give +0.5 to +1.9 points, never significant (utility +0.2 to +3.1). RRF k=20 costs 1 point at 1-2K; k=120 is identical. A reimplementation control reproduced the product exactly. Held-out was not consulted. |
| E030 | 2026-09-27 | Top-block trimming for every language (ranked line windows of an oversized non-Python top block) | **rejected** | No effect on ood-multi-dev: fix +0.4/-0.1 points at 512/1K for 20-line windows (2 wins/2 losses), -0.1/-0.1 for 40-line windows, identical from 2K; tests +0.6 at 512-1K (one task). Trimming helps only when the top-ranked block holds the fix; outside Python the fix sites rank at median 112-401, so the non-Python gap is ranking, not packing. |
| E031 | 2026-09-27 | Strip issue-template structure (short headings, checklists, HTML comments) from queries | **kept** | Promoted after the fresh heldout-c confirmation (HC01, criteria declared before the run): fix +0.7/+0.9/+1.2 points at 4K/8K/16K and tests +0.4 (1K) / +1.4 (16K), all significant; utility +0.25 to +2.57, no significant loss. Dev (E031b, 300): utility +1.0/+0.7/+1.6/+2.5/+0.4. Mixed on multilingual dev (utility -0.9 at 4K), which is not part of the rule. Product form: PackSelector(enable_query_cleaning=True) by default, CLI --raw-query to disable; cleaning applies once before every channel and Selection.query keeps the caller's text. The product form equals the evaluated prototype on all 515 dev-fast selections; three new mutants (cleaning disabled, title dropped, cleaned query reported) are killed. Benchmark arm npk_rawquery is the previous product. |
| E032 | 2026-09-27 | Bare member names and modifier-prefixed declarations as definition symbols | **rejected** | Mixed outside Python and no effect on Python. ood-multi-dev vs the product (OMD01): fix -0.4/+0.3/-1.2/-0.4/+0.3 points (none significant; wins and losses balanced), tests +0.3 to +0.6; utility -0.1/+0.7/-1.2/+0.2/+0.6 (negative at 1K and 4K). By language at 2K: JS/TS +4.3, Java +1.5, PHP +0.3, Rust -4.8, others 0. dev-fast (Python): all 515 selections identical. More definition candidates displace lexical ones in some languages; a language-specific form would need more data per language than ood-multi-dev has. |
| E033 | 2026-09-27 | Ruby splitter: def/class/module ... end blocks (matched by indentation) instead of 60-line windows | **rejected** | Fails the rule on the 28 Ruby issues of ood-multi-dev: fix +8.3 (1K, 5 wins/1 loss) / -0.4 / -1.4 / -3.6 / -10.9 [-22.8,-0.8] points (the 16K loss is significant: small method blocks lose the incidental coverage of neighboring hunks that windows gave); tests +0.9 / +8.3 / +8.3 / +20.4 [+7.4,+37.0] / +5.6 (minitest methods become findable units); utility +9.2/+7.9/+6.8/+16.6/-5.4. Promising for tests, but 28 issues are too few to tune a variant without fitting noise; a class-level-block design with member trimming (as for Python) would need a larger Ruby dev set. |
| E034 | 2026-09-27 | Weight the issue title's terms in the lexical channel | **kept** | Large dev-fast gains, widening with weight. x1 control identical to the product (515/515). x2: utility +3.6/+6.0/+6.5/+11.8/+9.9 points (tests +5.4* to +8.4* from 2K). x3: fix +1.0/+1.0/+1.8/+6.8*/+4.7, tests +2.9*/+8.7*/+9.8*/+9.3*/+9.5*, docs +15.4 at 1K-8K (2-3 issues); utility +5.2/+10.9/+12.8/+17.3/+14.1, no significant loss. Sweep of x4/x6 and a separate title channel (E034b) queued on dev-fast, then the full dev split; confirmation would use heldout-d. E034b sweep on dev-fast against the new default (with E031 cleaning): x3 utility +4.4/+8.3/+8.6/+12.0/+13.8 (tests significant at every budget, fix never negative); x4 +5.7/+9.6/+8.6/+15.2/+13.6; x6 +5.4/+5.2/+7.5/+15.3/+13.1 (fix -1.5 at 2K); title as its own RRF channel +2.2/+5.8/+15.8/+11.3/+13.6 (fix slightly negative at 1-2K); both +3.3/+4.4/+10.0/+14.0/+14.0 (fix -4.5 at 2K); title-only lexical query -0.7 at 2K (the body matters: weight the title, do not replace the body). x3 and x4 go to the full dev split (E034-E035-E036-dev). Non-Python (ood-multi-dev, 186 issues, 41 repositories' dev half): x3 fix +3.0/+1.9/+6.5*/+6.8*/+8.2* points, tests +3.6*/+0.8/+3.9*/+3.8*/+3.7, utility +6.6/+2.7/+10.4/+10.5/+11.8, no significant loss: the gain generalizes beyond Python. Product form prepared on local branch exp/e034p (title_weight, default 3; equals the prototype on 515/515 dev-fast selections and title_weight=1 equals the previous default on 515/515; two mutants killed). Full dev (300): x3 utility +5.8/+8.8/+10.1/+10.8/+15.4 points, x4 +6.6/+8.7/+10.5/+14.0/+16.4 (fix significant from 2K, tests at every budget, no significant loss); on the 197 issues outside dev-fast x4 is +7.0/+8.1/+10.9/+13.1/+18.2. By the declared rule x4 (higher mean utility) goes to heldout-d (HD01). HD01: x4 passes on heldout-d (fix +2.2 to +5.4 points significant at 2K-16K, tests +2.9 to +10.6 at every budget, mean utility 9.54), but E039 (title x3 with query term frequency) passed with a higher mean utility (9.99) and the declared rule promotes one of two uncombined alternatives; title weighting ships as part of E039 (x3). |
| E035 | 2026-09-27 | Choose the test mate's file with lexical evidence | **rejected** | Full dev (300): mirror_any utility 0/+2.9/+2.9/+1.1/+0.4 points (tests +2.6* at 4K), fused 0/+2.6/+3.7/+0.9/+0.5 (fix +1.2* and tests +2.1* at 4K); 1K is unchanged by construction (mate off). On the 197 issues outside dev-fast (where the rules were not designed) mirror_any stays >= 0 at every budget (0/+2.4/+1.2/+0.8/0) but fused falls to -0.14 at 8K, so by the declared rule mirror_any goes to heldout-d (HD01). HD01 (heldout-d): fails; fix -0.9 points at 4K is a significant loss and utility is -0.14 at 16K (tests +1.8 at 4K). The dev gain did not replicate. |
| E036 | 2026-09-27 | Module header (imports) of the top implementation file | **rejected** | Full dev (300): one file utility +1.1/+0.7/+0.7/+0.8/+3.3 points (fix +1.3* at 1K, +2.2* at 8K, +3.2* at 16K; tests -0.2 to -1.1, not significant); two files +1.1/+1.7/+1.5/+1.9/+3.5. Outside dev-fast the two-file variant falls to -0.3 at 4K with tests -1.6* at 8K, while one file stays +0.9/+0.9/+0.3/+0.4/+3.6, so by the declared rule the one-file header goes to heldout-d (HD01). HD01 (heldout-d): fix +2.8/+2.2/+2.4/+2.9 points at 2K-16K (significant) and utility +1.0 to +2.9, but tests -0.7 at 2K is a significant loss (upper bound -0.00004), which the declared criteria forbid. A header variant that keeps the fix gain without displacing test blocks at 2K (for example placed only from 4K) would need a fresh held-out split. |
| E037 | 2026-09-27 | Morphological query expansion (Snowball stems or plural forms from the pack vocabulary) | **rejected** | Fails the rule on dev-fast. Snowball (up to 3 variants per term; a Django query grows from 73 to 166 terms): fix -2.6/-4.5*/-2.1/+1.8/+0.3 points, tests -1.5/-0.5/-2.4/-5.1*/-6.2*, utility -4.1/-4.4/-3.1/-2.7/-7.2. Plural forms only: fix -1.5/-1.9/-0.5/+1.1/+1.1, tests +0.9/+1.8/-2.6/-1.7/-2.2, utility -0.6/-0.2/-2.4/-1.2/-1.7. Variants add common words (even ~ evening, supports, issues) whose BM25 terms outweigh the rare misspelled identifiers they were meant to reach. The product has no dependencies, so nothing would have shipped without an in-repository rule set anyway. |
| E038 | 2026-09-27 | Static Model2Vec embeddings (potion-base-8M / potion-retrieval-32M) as a semantic channel for code | **rejected** | Fails the rule on dev-fast in every form. Pool-of-100 with potion-base-8M: fix -6.6*/-7.4*/-4.0/-0.5/-2.9 points, utility -3.9/-3.2/-1.4/+5.1/-4.0. Pool with potion-retrieval-32M: fix -4.0/-8.4*/-5.5/-2.4/-4.5, utility -0.6/-3.4/+0.2/0.0/-6.9. Full-pack index (32M): fix -3.2*/-7.4*/-5.8/-4.4/-2.3, tests +4.3* at 1K, utility +1.7/-1.3/-1.4/-2.4/-3.8. Mean-pooled static vectors are too coarse for code: as a fusion channel they displace lexical and definition candidates. The semantic gap for code still needs a contextual encoder (E012b) or a different use of static vectors (not as an RRF channel). |
| E039 | 2026-09-27 | Query term frequency in the lexical channel | **kept** | Promoted after HD01 (heldout-d, 401 unused issues, criteria declared before the run): fix +0.1/+1.4/+2.9/+3.2/+4.6 points (significant from 2K), tests +2.8/+5.8/+8.5/+8.8/+12.2 (significant at every budget), utility +2.9/+7.2/+11.3/+11.9/+16.7, no significant loss; its mean utility (9.99) beat the other passing candidate, E034 title x4 (9.54). Full dev: +6.9/+6.8/+10.5/+11.6/+17.1. Product form: title_weight=3 and tf_cap=3 by default (CLI --title-weight/--tf-cap); each term of a multi-line query repeats min(tf_cap, 1 + floor(log2 tf)) times in the lexical OR plus title_weight - 1 if it is in the first line; single-line queries (chat memory) are unweighted. Equals the evaluated prototype on 515/515 dev-fast selections, and title_weight=1, tf_cap=1 equals the previous default on 515/515. Mutants killed: title_weight_ignored, query_tf_ignored, single_line_queries_weighted, title_weight_whole_query. Benchmark arms npk_unweighted (E039 off) and npk_query_baseline (E031 and E039 off). Cost (measured after promotion): FTS5 bm25() runs per phrase and per matching row, and weighting raises the phrase count 1.6-1.8x, so Django lexical ranking takes about 1.9x as long (median 51 -> 107 ms at depth 1000; matching alone 8 -> 18 ms) and median selection time rises about 55% (heldout-d at 4K: 70 -> 109 ms with four workers; p95 246 -> 469 ms). An earlier 'about 15%' figure came from E034 x3 on dev-fast and understated it for large repositories. |
| E040 | 2026-09-27 | Code names in the issue title vote more in the definition channel | **rejected** | No effect on dev-fast: against title x3 alone, x2 and x4 title votes change 1-2 issues per budget (fix +1.0 at 1K, tests -1.0 at 2K and 8K; utility +1.0/-1.0/0/-1.0/0 for x2 and +1.0/-0.6/+1.0/-1.0/0 for x4). Title names are usually few and already decisive in the definition channel's ranking. |
| E041 | 2026-09-27 | Title weighting in top-block trimming's member ranking | **rejected** | No effect on dev-fast at 512-16K: hunk recall identical to title x4 alone on every issue and budget (member order changes in a few selections without changing which gold lines are covered). Trimming mostly acts at small budgets, where the top block's best member is already decided by the rarest query terms. |
| E042 | 2026-09-27 | Top-file module header on the E039 default: only from 4K, or capped at budget//16 | **rejected** | Fails the dev rule declared for HE01 (no significant loss), so nothing went to heldout-e. Full dev vs the E039 default: from-4K fix +2.2/+2.1/+2.0 points at 4K/8K/16K (significant) but tests -1.2 at 8K (significant); cap budget//16 fix +0.7 to +2.0 (significant at 1K, 2K, 8K, 16K) and the same tests -1.2 at 8K; the original E036 header likewise. The header's tokens displace tail test blocks; the loss is identical across variants at 8K/16K because the same header is placed there. The trade (about +2 fix for -1 tests points) has positive utility but the declared criteria forbid significant losses; changing that criterion is a policy decision, not something to tune per experiment. |
| E043 | 2026-09-27 | Cap queries at 512 distinct lexical terms; append backticked literals in query order | **kept** | Kept as a robustness guard. Queries under the cap are unchanged by construction (dev-fast: 511/515 selections identical to the E039 run; the 4 differences are pylint-7080, which has 522 terms). Latency on Django (4K): 1,000 / 5,000 / 20,000 synthetic identifiers 8.4 / 39 / 114 s -> 2.2 / 3.0 / 4.1 s. On the ten benchmark issues above the cap (long-queries split, heldout-e excluded): median latency 1.2 s -> 0.74 s (max 3.5 -> 1.5 s); fix 0/0/-8.3/-10.0/+1.4 and tests +10/+10/+10/+10/0 points vs uncapped, none significant (n=10; 43 of 50 issue-budgets identical). The literal-order fix removes hash-seed dependence (six seeds give one order); on the exposed dev-fast issue, selections were already identical across seeds. Mutants query_term_cap_ignored and explicit_literals_in_hash_order are killed. |
| E044 | 2026-09-27 | A second test mate (for the second-ranked implementation file) at large budgets | **rejected** | Does not replicate. Full dev (300) vs the default: from-8K tests +0.8 (8K, not significant) and +0.95 (16K, lower bound barely above 0), fix -0.17/-0.17, utility +0.30/+0.11 (mean 0.08); from-4K fails (fix -2.6 at 4K, significant). On the 197 dev issues outside dev-fast, where it was not screened, the from-8K variant has utility -0.9 / -0.7 at 8K/16K (fix -0.7/-0.5, tests -0.2/+1.2): the full-dev pass rests on the dev-fast issues. The HE01 plan declared for E044 would have sent the from-8K variant to heldout-e; that confirmation was deliberately not run, which can only prevent a promotion, so heldout-e stays unused for a stronger candidate. Dev-fast screen: tests +2.75 at 8K (significant), utility +2.9/+1.0 at 8K/16K. |
| E045 | 2026-09-27 | A cross-encoder reorders the top 10 fused candidates (ms-marco MiniLM, bge-reranker-base) | **rejected** | Fails decisively on the full dev split (screened there directly). MiniLM: fix -15.8/-12.8/-8.8/-1.1/-0.3 points at 1K-16K (significant at 1K-4K), tests +4.3 (1K, significant)/+3.7/+1.7/-0.6/-0.7, utility -11.0/-9.0/-6.7/-1.6/-1.4. bge-reranker-base: fix -14.8/-11.7/-8.0/-0.4/+0.1 (significant at 1K-4K), utility -11.0/-12.1/-5.0/-1.7/-0.4. Both web-passage rerankers prefer prose-like blocks (tests, docs) that read like the issue over the implementation code; they also cost 1.9 s (MiniLM) and 10.5 s (bge) median per query on one CPU thread. A code-aware reranker would be needed; general-purpose ones are not an opt-in candidate. |
| E046 | 2026-09-27 | Modifier-prefixed declarations and bare member names as JS/TS/Java definitions (compile time) | **rejected** | Fails the dev rule on poly-dev (199 issues; vs P001's default, same issues, the compiler change is the only difference). Fix +2.53 (1K, significant) / +1.01 / +1.38 (significant) / +0.57 (significant) / +0.22 points; tests -0.82 / -0.76 / -0.30 (significant) / -0.89 (significant) / -0.27; utility +1.7 / +0.3 / +1.1 / -0.3 / -0.04. The gain is mostly Java (fix +4.2 at 1K, +2.4 at 4K) with Java's regression-test recall down 0.7-1.9 points; TypeScript is unchanged. Java's test mate cannot mirror FooTest.java to Foo.java (E047), so when definitions change the top implementation file the mate lands on an arbitrary test of the package; E046 is to be re-screened on top of E047 if E047 is kept. Patch saved in the run directory (e046.patch). Compile +5% (13.4 s vs 12.8 s mean), packs +2%. |
| H001 | 2026-09-26 | Held-out confirmation: test mate (E016b), top-block trimming (E005c), context map (E017) | **kept** | E005c confirmed: trimming vs no trimming, fix +3.8 points at 1K (significant), identical at >=2K; utility +2.9/0/0/0/0. E017 confirmed: located fix recall with a 25% map +9.6/+12.3/+13.0/+11.4/+7.2 points over the default's full text, tests +5.3/+5.2/+7.7/+8.0/+8.2 (all CIs exclude zero). E016b confirmed only as a tradeoff: tests up at every budget, fix down 0.3-1.4 points; the 1K utility is -0.012 points with a significant fix loss, so it ships opt-in. Full current default on held-out (definition channel + trimming): fix 0.230/0.309/0.399/0.475/0.575 at 1K-16K (before this loop 0.136/0.206/0.302/0.393/0.490). |
| HB01 | 2026-09-26 | Confirmation on heldout-b: budget-gated test mate (E016c) and replication of E002+E005c | **kept** | E016c passes (see its record). The definition channel and trimming replicate on fresh data: fix +6.5/+5.8/+9.0/+8.0/+8.3 points at 1K-16K over no-definitions/no-trim (all CIs exclude zero); tests -1.9 to -3.3 (the known tradeoff). Product on heldout-b (mate off): fix 0.178/0.244/0.348/0.428/0.526. |
| HC01 | 2026-09-27 | Confirmation on heldout-c: issue-form cleaning of queries (E031) | **kept** | E031 passes all three criteria on 400 unused issues (0 errors). e031_clean vs product: fix -0.2 [-0.7,+0.2] / +0.4 [-0.3,+1.2] / +0.7 [+0.2,+1.3] / +0.9 [+0.3,+1.7] / +1.2 [+0.4,+2.3] points at 1K-16K (16 wins/2 losses at 16K); tests +0.4 [+0.0,+0.9] / +0.1 / +0.6 / +0.9 / +1.4 [+0.2,+2.7]; utility +0.25/+0.54/+1.26/+1.86/+2.57. Product on heldout-c (raw query): fix 0.194/0.259/0.350/0.411/0.496, tests 0.039/0.099/0.126/0.181/0.256. |
| HD01 | 2026-09-27 | Confirmation on heldout-d: E034 title x4, E039 (tf + title x3), E035 mirror_any, E036 header, and combinations | **kept** | 401 unused issues, 0 errors; unrounded paired-bootstrap bounds. E034 x4 passes (utility +4.2/+6.3/+9.8/+11.4/+15.9 points, mean 9.54). E039 passes (+2.9/+7.2/+11.3/+11.9/+16.7, mean 9.99). E035 mirror_any fails (fix -0.9 at 4K significant, utility -0.14 at 16K). E036 header fails: fix +2.8/+2.2/+2.4/+2.9 points at 2K-16K (significant) but tests -0.7 at 2K is a significant loss (upper bound -0.00004; the rounded report first showed it as non-significant, so report.paired now flags significance from unrounded bounds). The passing E034 and E039 are alternative lexical weightings with no arm combining them, so by the declared rule only the candidate with the higher mean utility, E039, is promoted. Combination arms that include E035 or E036 pass (e.g. title x4 + header: mean 11.6) but combine failing components and are not eligible; a header variant would need a fresh confirmation. |
| M000 | 2026-09-26 | Baseline: conversation memory (LongMemEval-S dev, 100 questions) | **kept** | Reference point for the second workload family. Weak spots: multi-session aggregation and implicit preferences. |
| M001 | 2026-09-26 | Source-diverse packing (per-file score decay) for multi-session memory questions | **rejected** | Turn recall falls 10-16 points: fused RRF scores are nearly flat (1/60..1/120), so any per-file decay reorders almost the whole ranking toward weakly matching fresh sessions. Session coverage rises but evidence turns are lost. |
| M002 | 2026-09-26 | Relevance-density ordering (fused score / tokens^alpha) before greedy fill | **rejected** | Aggregate gain is a disguised role prior: it comes from LongMemEval's composition (842/896 evidence turns are user turns) and collapses the question type whose evidence is in long assistant turns (1K: 0.833 -> 0.333). Not a default. Pursue finer units for long turns instead. |
| M003 | 2026-09-26 | Paragraph-level units for long conversation turns (data-level layout test) | **rejected** | Mixed: +1.1/+3.6 at 2K/4K and better session coverage, but -8.9/-1.1/-2.1 at 256/512/1K. Turn-level units stay; no compiler change. |
| M004 | 2026-09-26 | Dense similarity on conversation memory (pool fusion, bge-small / MiniLM) | **kept** | Significant gains on memory-dev (100 questions): bge-small +4.1/+3.4/+4.3/+7.0/+7.7/+5.8 points at 256-8K (CI excludes zero at 2K, 4K, 8K); MiniLM +4.4/+1.4/+1.7/+4.7/+4.4/+4.1 (significant at 4K, 8K). By type (bge): multi-session +8 to +13, single-session-preference +17 to +22, temporal +5 to +13; knowledge-update -3 to -13 at 256-1K. The same fusion hurts code at small budgets (E012), so it cannot be a global default. Productized as the documented semantic/hybrid configuration for chat histories (M006: most of the gain with the shipped MiniLM path). |
| M005 | 2026-09-26 | Time-window channel for dated conversation memory | **rejected** | No effect: identical to the product except one win at 4K (+0.5 points; temporal-reasoning 0.732 -> 0.751 at 4K). Pre-run analysis predicted a small ceiling: LongMemEval-S histories span 10-90 days, so period expressions cover every session (reporting lag makes the window run to the question date), and only 3 of 17 parsable memory-dev questions get a selective point window. |
| M006 | 2026-09-26 | The shipped semantic/hybrid mode on conversation memory | **kept** | Kept as the documented configuration for conversation memory (no code change). vs lexical default on memory-dev: +4.5 [+0.4,+9.0] / +1.4 / +0.3 / +3.5 / +4.4 [+0.2,+9.2] / +7.1 [+2.8,+12.2] points at 256-8K; largest on preferences (0.67 -> 1.00 at 8K) and multi-session (0.74 -> 0.83 at 8K). Within about 3 points of M004's bge-small pool fusion (-3.3 at 4K, +1.3 at 8K) and indistinguishable from MiniLM pool fusion. Cost: 48.9 s compile per history (one CPU thread) vs 0.25 s; query p50 5.9 ms vs 1.9 ms. Held-out (MH01, 370 questions): confirmed at 4K (+4.2) and 8K (+6.0), neutral at 2K and below; the recommendation is scoped to 4K+ budgets. |
| M007 | 2026-09-27 | Chat-memory queries are unchanged by E031 and E039 (sanity check) | **kept** | memory-dev: all 600 selections (100 questions x 256-8K) of the new default equal npk_query_baseline (neither E031 nor E039). |
| MH01 | 2026-09-27 | Held-out confirmation of the semantic/hybrid chat-memory configuration (M006) | **kept** | Confirmed at 4K and above only. Hybrid vs lexical: +0.7/-0.7/+1.1/+2.2 (none significant) at 256-2K; +4.2 [+2.2,+6.4] at 4K (38 wins/6 losses) and +6.0 [+4.2,+8.1] at 8K (42/0). The 256-token gain seen on dev did not replicate. By type at 8K: preferences 0.71 -> 0.92, multi-session 0.78 -> 0.85, temporal 0.87 -> 0.92; knowledge-update is lower at 512-1K. README now recommends the mode for chat histories read with 4K tokens or more. Compile cost 44.6 s vs 0.22 s per history. |
| O001 | 2026-09-26 | Out-of-distribution check on six never-used repositories (SWE-bench Lite dev) | **kept** | Generalizes on the fix target (23 issues: sqlfluff, pvlib, astroid, pydicom, marshmallow, pyvista). Definition channel + trimming vs neither: fix +19.6 [+4.3,+37.0] / +13.8 / +8.7 / +2.2 / +0.7 points at 1K-16K; tests -5/-10/-7.5/-7.5/-2.5 (not significant, same direction as held-out). Trimming alone: fix +15.2 [+2.2,+30.4] at 1K, identical beyond. Test mate (opt-in): tests +5/+15/+10/+5/+5 with no fix loss (20 tasks, lower CI bounds at zero). |
| OM01 | 2026-09-27 | Non-Python generalization: SWE-bench Multilingual sample (114 issues, 41 repositories) | **kept** | Holds, at lower absolute recall. Product fix recall 0.110/0.164/0.197/0.269/0.320 at 1K-16K (Python held-out: 0.230/0.303/...). vs BM25 over 60-line chunks: fix +7.4 to +14.8 points and tests +2.4 to +9.8 (all significant); vs ~1,000-character chunks: fix +4.2 (n.s.) / +8.2 / +6.2 / +12.3 / +8.2 (significant from 2K). The definition channel helps outside Python: +5.1/+4.1/+3.6 points at 2K-8K (significant), decisive for Go (2K: 0.002 -> 0.202) and Ruby (0.000 -> 0.125). By language at 2K: PHP 0.33, Go 0.20, Java 0.20 (chunk baseline 0.27), Rust 0.18, Ruby 0.13, JS/TS 0.12 (flat to 8K), C/C++ 0.09. Weak spots (JS/TS, C/C++, Java) must be analyzed on ood-multi-dev, never on this sample. |
| OMD01 | 2026-09-27 | Multilingual dev split: product vs chunk baseline, and where non-Python fix sites are lost | **kept** | Kept as the development baseline for non-Python work. Product fix 0.146/0.212/0.259/0.328/0.383 at 1K-16K vs ~1,000-character-chunk BM25 0.093/0.120/0.165/0.223/0.270; no-definitions 0.122/0.162/0.209/0.286/0.357. Loss at 2K by language (share of gold hunks): selected 3-4% for C/C++, JS/TS and Rust vs 16-19% for Java, Go, PHP and Ruby. Most misses are ranking losses: missed hunks' covering blocks rank at median 112-401 (C/C++ 401); 13-29% are never retrieved. Covering blocks are large for C/C++ (median 1,086 tokens) and JS/TS (735). |
| P001 | 2026-09-27 | First measurement on SWE-PolyBench poly-dev (Java/JS/TS): default vs query baseline vs B002 | **kept** | 199 issues (173 with test edits), 0 errors, 199 packs (mean compile 12.8 s, 34.9 MB). Fix hunk recall at 1K-16K: default 0.195/0.244/0.319/0.404/0.476, npk_query_baseline 0.134/0.182/0.259/0.318/0.387, B002 0.087/0.121/0.176/0.240/0.297. Regression tests: 0.113/0.185/0.276/0.378/0.418 vs 0.082/0.117/0.191/0.269/0.343 vs 0.051/0.077/0.118/0.184/0.263. The query handling passes the declared rule on this new language set (fix +6.0 to +8.9 points, tests +3.1 to +11.0, all significant; mean utility +14.5); against B002 fix +10.8 to +17.9 points (1.6-2.2x) and tests +6.2 to +19.4 (all significant). By language (fix at 2K/16K): Java (74) 0.262/0.486, JavaScript (75) 0.218/0.440, TypeScript (50) 0.258/0.514; TypeScript gains most from query handling (+10 to +19 points). Median selection latency 68-100 ms. Poly-dev is now the development set for JS/TS/Java work; these numbers are the reference before tuning. |
| R002 | 2026-09-27 | README re-measurement on heldout: the default after E031 and E039 | **kept** | 407 issues, 0 errors. New default vs npk_query_baseline (which reproduces the previous README row exactly, 0.230/0.303/0.385/0.472/0.569): fix 0.254/0.346/0.452/0.571/0.638 (+2.3/+4.3/+6.8/+9.9/+7.0 points, all significant), tests 0.089/0.180/0.252/0.338/0.423 (+3.0/+3.7/+5.8/+8.2/+12.0, all significant), docs +1.5/+8.5/+0.8/-3.4/+3.1 (none significant). Against the B001 chunk-BM25 baseline: fix 2.0-2.5x (significant at every budget), tests 1.5-2.1x (significant from 2K), docs no longer significantly different at any budget (at 2K 0.25 vs 0.31; was 0.17 vs 0.31). |
| R003 | 2026-09-27 | README re-measurement on the multilingual sample: the default after E031 and E039 | **kept** | 114 issues, 0 errors. New default vs npk_query_baseline: fix 0.198/0.260/0.301/0.364/0.455 vs 0.110/0.164/0.197/0.269/0.320 (+8.9/+9.7/+10.4/+9.5/+13.5 points, all significant), tests +2.4/+3.1/+6.7/+12.4/+10.8 (significant except 2K). Against B002 (BM25 over 1,000-character chunks): fix +13.0 to +21.9 points (2.2-3.2x), tests +4.6 to +17.4 (1.9-2.6x), all significant. Non-Python recall moved from about half of Python's to about three quarters (0.260 vs 0.346 at 2K). |

## B001 — Standard-RAG baseline: Okapi BM25 over fixed 60-line chunks (whole and split identifiers)

- **Status:** kept
- **Hypothesis:** NeuralPack's structure-aware blocks, fielded BM25 and channels beat the typical retrieval pipeline on the same repositories, budgets and gold.
- **Run:** experiments/npkbench/runs/B001-rag-baseline-heldout, experiments/npkbench/runs/B001-rag-baseline-devfast, experiments/npkbench/runs/B001-rag-baseline-memory-dev
- **Results:**

```json
{
 "heldout_docs_1K_16K": {
  "bm25_chunks_split": [
   0.125,
   0.311,
   0.372,
   0.537,
   0.614
  ],
  "product": [
   0.137,
   0.165,
   0.305,
   0.517,
   0.602
  ]
 },
 "heldout_fix_1K_16K": {
  "bm25_chunks": [
   0.102,
   0.146,
   0.19,
   0.227,
   0.262
  ],
  "bm25_chunks_split": [
   0.101,
   0.149,
   0.217,
   0.267,
   0.321
  ],
  "product": [
   0.23,
   0.309,
   0.399,
   0.475,
   0.575
  ],
  "product_before_loop": [
   0.136,
   0.206,
   0.302,
   0.393,
   0.49
  ]
 },
 "heldout_tests_1K_16K": {
  "bm25_chunks_split": [
   0.06,
   0.088,
   0.129,
   0.163,
   0.221
  ],
  "product": [
   0.058,
   0.105,
   0.149,
   0.22,
   0.287
  ]
 }
}
```

- **Decision:** Kept as a permanent baseline arm. Held-out (407 issues), fix recall: product 0.230/0.309/0.399/0.475/0.575 vs chunk BM25 0.102/0.146/0.190/0.227/0.262 (+12.8 to +31.4 points) and identifier-split chunk BM25 0.101/0.149/0.217/0.267/0.321 (+12.9 to +25.5); every CI excludes zero. Even the pre-loop product (0.136/0.206/0.302/0.393/0.490) beat both. Tests: split baseline equal at 1-2K, product ahead from 8K (+5.7, +6.6 significant). Docs (33 issues): baseline ahead at 2K (+14.6 split, +21.4 whole; significant), equal from 8K. Dev-fast agrees on fix (+19 to +30 points). Memory-dev at 256-1K is not a fair comparison for 60-line chunks of long chat lines; B002 uses the common ~1,000-character chunker instead.

## B002 — Standard-RAG baseline with the common ~1,000-character chunker (identifier-split BM25)

- **Status:** kept
- **Hypothesis:** A fairer baseline for chat text (60-line chunks of long chat lines rarely fit small budgets) and a second code baseline.
- **Run:** experiments/npkbench/runs/B002-rag-chars-devfast, experiments/npkbench/runs/B002-rag-chars-memory-dev
- **Decision:** Kept as a baseline arm. Code (dev-fast): product fix +23.1/+24.6/+21.8/+19.7/+15.9 points at 1K-16K (all significant); tests within noise (baseline slightly ahead at 1-4K, product at 8-16K); docs (13 tasks) baseline far ahead (0.423 vs 0.000 at 2K). Memory (memory-dev): product +20.6 [+10.6,+30.3] at 256 and +13.9 [+5.0,+23.0] at 512, then 1K-4K within +-1 point and -3.8 (n.s.) at 8K; the semantic/hybrid mode leads at every budget (+25.1/+15.3/+6.0/+3.5/+3.4/+3.3). Documentation retrieval is NeuralPack's main open weakness: small prose units match issue text well, and code-first ranking (definition channel) gives docs up.
- **Follow-ups:** Documentation units sized like prose chunks (about 250 tokens) without changing code ranking; must not repeat E018b's code cost

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

- **Status:** kept
- **Hypothesis:** Placing the best query-matching block of the mirroring test file right after the top implementation block, inside the product's fill and trimming, recovers tests-target recall without a significant fix-target cost.
- **Run:** experiments/npkbench/runs/E016b-test-mate-product-devfast, experiments/npkbench/runs/H001-mate-trim-heldout
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
 "heldout_fix_1K_16K": {
  "mate": [
   0.219,
   0.303,
   0.385,
   0.472,
   0.569
  ],
  "nomate": [
   0.23,
   0.309,
   0.399,
   0.475,
   0.575
  ]
 },
 "heldout_tests_1K_16K": {
  "mate": [
   0.07,
   0.143,
   0.194,
   0.256,
   0.303
  ],
  "nomate": [
   0.058,
   0.105,
   0.149,
   0.22,
   0.287
  ]
 },
 "heldout_utility": [
  -0.00012,
  0.03182,
  0.02764,
  0.03262,
  0.01033
 ],
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

- **Decision:** Kept as an opt-in mode (enable_test_mate=True, --test-mate); the held-out confirmation did not support a default change. Dev-fast: tests +3.7/+7.0/+4.9/+2.9/+2.8 points, fix changes not significant. Held-out H001 (407 issues; criteria committed before the run): tests +1.15 [+0.2,+2.3] / +3.8 [+1.6,+6.0] / +4.5 [+2.2,+7.1] / +3.6 [+2.0,+5.4] / +1.7 [+0.7,+2.9] points at 1K-16K (34 wins/6 losses at 2K); fix -1.15 [-2.2,-0.3] / -0.6 / -1.4 [-2.7,-0.2] / -0.3 / -0.6 [-1.3,-0.1]; docs ~0. Utility -0.012/+3.2/+2.8/+3.3/+1.0 points: negative (by 0.012 points) at 1K with a significant fix loss, so the pre-declared rule blocks a default change. A budget-gated variant (mate only at >=2K) is suggested by these numbers but must not be confirmed on the same held-out split.
- **Follow-ups:** H001: held-out confirmation (tests, docs, fix) together with E005c trimming

## E016c — Budget-gated test mate as the default (on from 2048 tokens)

- **Status:** kept
- **Hypothesis:** H001 showed the always-on test mate trades evenly at 1K (utility -0.012 points, significant fix loss) and gains clearly at 2K and above; gating it at 2K keeps the gain without the 1K cost. Designed from held-out results, so confirmed only on the fresh heldout-b.
- **Run:** experiments/npkbench/runs/HB01-heldout-b
- **Files changed:** `npk/pack/select.py`, `npk/cli.py`, `benchmarks/npkbench/arms.py`, `tests/test_test_mate.py`, `benchmarks/contract_mutations.py`, `README.md`, `CURRENT_ARCHITECTURE.md`
- **Results:**

```json
{
 "heldout_b_fix_1K_16K": {
  "mate_always": [
   0.174,
   0.232,
   0.34,
   0.42,
   0.522
  ],
  "product_mate_off": [
   0.178,
   0.244,
   0.348,
   0.428,
   0.526
  ]
 },
 "heldout_b_tests_1K_16K": {
  "mate_always": [
   0.071,
   0.13,
   0.167,
   0.219,
   0.277
  ],
  "product_mate_off": [
   0.048,
   0.073,
   0.108,
   0.182,
   0.255
  ]
 },
 "utility_gated": [
  0.0,
  0.04511,
  0.05023,
  0.02786,
  0.01875
 ]
}
```

- **Decision:** Passes the criteria declared in NEXT_STEPS.md before HB01 (heldout-b, 400 fresh issues). Gated vs product: 1K identical by construction; tests +5.7 [+3.4,+8.1] / +6.0 [+3.7,+8.4] / +3.7 [+2.0,+5.5] / +2.3 [+1.0,+3.7] points at 2K-16K; fix -1.1 [-2.6,+0.3] / -0.9 [-2.0,+0.2] / -0.9 [-1.8,-0.1] / -0.4 [-1.0,-0.0]; utility 0.0/+4.5/+5.0/+2.8/+1.9. Significant fix losses occur only where utility is clearly positive. The new default equals the evaluated composition (mate off at 1K, evaluated mate from 2K) on all 515 dev-fast selections. enable_test_mate: None (default, gated) / True / False; CLI --test-mate auto|always|never; mutant test_mate_gate_ignored is killed.

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

## E024 — Bulk integrity leaves (one ordered scan per table) and batched framing

- **Status:** rejected
- **Hypothesis:** Compile-time sealing computes each file's integrity leaf with 7 small queries (21K on Django) and frames 500K values one call at a time; one ordered scan per table feeding incremental per-file hashes, and inlined framing, give identical digests faster (profile: ~2 s of a 21 s profiled compile).
- **Run:** experiments/npkbench/runs/E024-bulk-integrity
- **Files changed:** `npk/pack/integrity.py`, `tests/test_incremental_integrity.py`, `benchmarks/contract_mutations.py`
- **Decision:** Correct but not worth its complexity. Digests are byte-identical (4 Django packs; new equality test across all local tables; two mutants killed), but paired compile timing gives 1.018x (12.86 -> 12.64 s median) and verify ~3% (9.4-9.8 s -> 8.8-9.3 s). The cold-pack microbenchmark (1.4 s -> 0.5 s) overstated the in-compile gain because sealing reads hot pages; verify is dominated by the deliberate FTS source-parity rebuild. Not merged: +40 lines in integrity-critical code for ~2%.

## E025 — Parameter sweep: BM25 field weights (E025), candidate depth (E026), RRF constant (E027)

- **Status:** rejected
- **Hypothesis:** Constants never tuned on an external benchmark (field weights 1/1/1, candidate_limit 60, RRF k 60) leave recall on the table.
- **Run:** experiments/npkbench/runs/E025-params-devfast
- **Decision:** Defaults sit near a local optimum; no setting passes the rule. Field weights: name x2 / path x2 / both x2 change fix by at most +3.2 points (both x2 at 16K, the only significant cell) while costing tests -1.7 at 4K (utility -1.4); halving name/path weights loses up to -2.4. Candidate depth: 30 hurts (fix -3.4 at 4K, significant); 120 and 240 give +0.5 to +1.9 points, never significant (utility +0.2 to +3.1). RRF k=20 costs 1 point at 1-2K; k=120 is identical. A reimplementation control reproduced the product exactly. Held-out was not consulted.

## E030 — Top-block trimming for every language (ranked line windows of an oversized non-Python top block)

- **Status:** rejected
- **Hypothesis:** Non-Python covering blocks are large, and trimming is Python-only; ranking 20- or 40-line windows of an oversized top block by file-local BM25 should recover small-budget recall as E005c did for Python.
- **Run:** experiments/npkbench/runs/E030-trim-any-multidev
- **Decision:** No effect on ood-multi-dev: fix +0.4/-0.1 points at 512/1K for 20-line windows (2 wins/2 losses), -0.1/-0.1 for 40-line windows, identical from 2K; tests +0.6 at 512-1K (one task). Trimming helps only when the top-ranked block holds the fix; outside Python the fix sites rank at median 112-401, so the non-Python gap is ranking, not packing.

## E031 — Strip issue-template structure (short headings, checklists, HTML comments) from queries

- **Status:** kept
- **Hypothesis:** Issue forms wrap the reporter's words in section headings, checklists and HTML-comment instructions; those words are rare in code but common in CONTRIBUTING.md, READMEs and changelogs, which then outrank code. Removing them before retrieval (title always kept) should move code up without losing anything the reporter wrote.
- **Run:** experiments/npkbench/runs/HC01-query-clean-heldout-c, experiments/npkbench/runs/E031b-query-clean-dev, experiments/npkbench/runs/E031-query-clean-devfast, experiments/npkbench/runs/E031-query-clean-multidev
- **Files changed:** `npk/pack/select.py`, `npk/cli.py`, `tests/test_query_cleaning.py`, `benchmarks/contract_mutations.py`, `benchmarks/npkbench/arms.py`, `README.md`, `CURRENT_ARCHITECTURE.md`, `NEXT_STEPS.md`
- **Results:**

```json
{
 "dev_utility_points": [
  1.0,
  0.7,
  1.6,
  2.5,
  0.4
 ],
 "equivalence_dev_fast": "515/515 identical",
 "heldout_c_utility_points": [
  0.25,
  0.54,
  1.26,
  1.86,
  2.57
 ],
 "mutants": {
  "query_cleaning_disabled": "killed",
  "query_cleaning_drops_title": "killed",
  "query_cleaning_reports_cleaned_query": "killed"
 }
}
```

- **Decision:** Promoted after the fresh heldout-c confirmation (HC01, criteria declared before the run): fix +0.7/+0.9/+1.2 points at 4K/8K/16K and tests +0.4 (1K) / +1.4 (16K), all significant; utility +0.25 to +2.57, no significant loss. Dev (E031b, 300): utility +1.0/+0.7/+1.6/+2.5/+0.4. Mixed on multilingual dev (utility -0.9 at 4K), which is not part of the rule. Product form: PackSelector(enable_query_cleaning=True) by default, CLI --raw-query to disable; cleaning applies once before every channel and Selection.query keeps the caller's text. The product form equals the evaluated prototype on all 515 dev-fast selections; three new mutants (cleaning disabled, title dropped, cleaned query reported) are killed. Benchmark arm npk_rawquery is the previous product.

## E032 — Bare member names and modifier-prefixed declarations as definition symbols

- **Status:** rejected
- **Hypothesis:** Brace-language methods are stored only under qualified names (JsonReader.nextString), so the definition channel never matches a method an issue names; DEF_RE also misses pub fn / export function / public static / def self.x. Recording bare member names and allowing modifiers should help non-Python ranking.
- **Baseline run:** experiments/npkbench/runs/OMD01-multilingual-dev, experiments/npkbench/runs/E031-query-clean-devfast
- **Run:** experiments/npkbench/runs/E032-def-symbols-multidev, experiments/npkbench/runs/E032-def-symbols-devfast
- **Files changed:** `npk/pack/compile.py`
- **Decision:** Mixed outside Python and no effect on Python. ood-multi-dev vs the product (OMD01): fix -0.4/+0.3/-1.2/-0.4/+0.3 points (none significant; wins and losses balanced), tests +0.3 to +0.6; utility -0.1/+0.7/-1.2/+0.2/+0.6 (negative at 1K and 4K). By language at 2K: JS/TS +4.3, Java +1.5, PHP +0.3, Rust -4.8, others 0. dev-fast (Python): all 515 selections identical. More definition candidates displace lexical ones in some languages; a language-specific form would need more data per language than ood-multi-dev has.

## E033 — Ruby splitter: def/class/module ... end blocks (matched by indentation) instead of 60-line windows

- **Status:** rejected
- **Hypothesis:** Ruby files are cut into anonymous 60-line windows; method-level named blocks should rank Ruby fix and test sites better.
- **Baseline run:** experiments/npkbench/runs/OMD01-multilingual-dev
- **Run:** experiments/npkbench/runs/E033-ruby-split-multidev
- **Files changed:** `npk/pack/compile.py`, `tests/test_ruby_split.py`
- **Decision:** Fails the rule on the 28 Ruby issues of ood-multi-dev: fix +8.3 (1K, 5 wins/1 loss) / -0.4 / -1.4 / -3.6 / -10.9 [-22.8,-0.8] points (the 16K loss is significant: small method blocks lose the incidental coverage of neighboring hunks that windows gave); tests +0.9 / +8.3 / +8.3 / +20.4 [+7.4,+37.0] / +5.6 (minitest methods become findable units); utility +9.2/+7.9/+6.8/+16.6/-5.4. Promising for tests, but 28 issues are too few to tune a variant without fitting noise; a class-level-block design with member trimming (as for Python) would need a larger Ruby dev set.

## E034 — Weight the issue title's terms in the lexical channel

- **Status:** kept
- **Hypothesis:** The lexical channel deduplicates query terms, so the title (the reporter's one-line summary) counts no more than traceback, reproduction or template words. Repeating title terms in the FTS5 OR (bm25 sums repeated phrases) weights them.
- **Run:** experiments/npkbench/runs/E034-title-weight-devfast, experiments/npkbench/runs/E034b-title-weight-sweep-devfast, experiments/npkbench/runs/E034-title-weight-multidev, experiments/npkbench/runs/E034-E035-E036-dev, experiments/npkbench/runs/HD01-heldout-d
- **Decision:** Large dev-fast gains, widening with weight. x1 control identical to the product (515/515). x2: utility +3.6/+6.0/+6.5/+11.8/+9.9 points (tests +5.4* to +8.4* from 2K). x3: fix +1.0/+1.0/+1.8/+6.8*/+4.7, tests +2.9*/+8.7*/+9.8*/+9.3*/+9.5*, docs +15.4 at 1K-8K (2-3 issues); utility +5.2/+10.9/+12.8/+17.3/+14.1, no significant loss. Sweep of x4/x6 and a separate title channel (E034b) queued on dev-fast, then the full dev split; confirmation would use heldout-d. E034b sweep on dev-fast against the new default (with E031 cleaning): x3 utility +4.4/+8.3/+8.6/+12.0/+13.8 (tests significant at every budget, fix never negative); x4 +5.7/+9.6/+8.6/+15.2/+13.6; x6 +5.4/+5.2/+7.5/+15.3/+13.1 (fix -1.5 at 2K); title as its own RRF channel +2.2/+5.8/+15.8/+11.3/+13.6 (fix slightly negative at 1-2K); both +3.3/+4.4/+10.0/+14.0/+14.0 (fix -4.5 at 2K); title-only lexical query -0.7 at 2K (the body matters: weight the title, do not replace the body). x3 and x4 go to the full dev split (E034-E035-E036-dev). Non-Python (ood-multi-dev, 186 issues, 41 repositories' dev half): x3 fix +3.0/+1.9/+6.5*/+6.8*/+8.2* points, tests +3.6*/+0.8/+3.9*/+3.8*/+3.7, utility +6.6/+2.7/+10.4/+10.5/+11.8, no significant loss: the gain generalizes beyond Python. Product form prepared on local branch exp/e034p (title_weight, default 3; equals the prototype on 515/515 dev-fast selections and title_weight=1 equals the previous default on 515/515; two mutants killed). Full dev (300): x3 utility +5.8/+8.8/+10.1/+10.8/+15.4 points, x4 +6.6/+8.7/+10.5/+14.0/+16.4 (fix significant from 2K, tests at every budget, no significant loss); on the 197 issues outside dev-fast x4 is +7.0/+8.1/+10.9/+13.1/+18.2. By the declared rule x4 (higher mean utility) goes to heldout-d (HD01). HD01: x4 passes on heldout-d (fix +2.2 to +5.4 points significant at 2K-16K, tests +2.9 to +10.6 at every budget, mean utility 9.54), but E039 (title x3 with query term frequency) passed with a higher mean utility (9.99) and the declared rule promotes one of two uncombined alternatives; title weighting ships as part of E039 (x3).

## E035 — Choose the test mate's file with lexical evidence

- **Status:** rejected
- **Hypothesis:** The mate mirrors the top implementation file's path and keeps only the best-mirroring files; on dev-fast at 4K it lands in a gold test file in 36/103 issues, the lexically top test file in 37, and the two agree in 15. Considering every mirroring test file (mirror_any) or fusing mirror strength with lexical file rank (fused) should pick the regression-test file more often.
- **Run:** experiments/npkbench/runs/E034-E035-E036-dev, experiments/npkbench/runs/HD01-heldout-d
- **Decision:** Full dev (300): mirror_any utility 0/+2.9/+2.9/+1.1/+0.4 points (tests +2.6* at 4K), fused 0/+2.6/+3.7/+0.9/+0.5 (fix +1.2* and tests +2.1* at 4K); 1K is unchanged by construction (mate off). On the 197 issues outside dev-fast (where the rules were not designed) mirror_any stays >= 0 at every budget (0/+2.4/+1.2/+0.8/0) but fused falls to -0.14 at 8K, so by the declared rule mirror_any goes to heldout-d (HD01). HD01 (heldout-d): fails; fix -0.9 points at 4K is a significant loss and utility is -0.14 at 16K (tests +1.8 at 4K). The dev gain did not replicate.

## E036 — Module header (imports) of the top implementation file

- **Status:** rejected
- **Hypothesis:** About a quarter of the fix hunks missed at 4K inside an already-selected file are import edits in the file's first module-level block; placing that header (<= budget/8) right after the file's top block should find them and show a reader which names are in scope.
- **Run:** experiments/npkbench/runs/E034-E035-E036-dev, experiments/npkbench/runs/HD01-heldout-d
- **Decision:** Full dev (300): one file utility +1.1/+0.7/+0.7/+0.8/+3.3 points (fix +1.3* at 1K, +2.2* at 8K, +3.2* at 16K; tests -0.2 to -1.1, not significant); two files +1.1/+1.7/+1.5/+1.9/+3.5. Outside dev-fast the two-file variant falls to -0.3 at 4K with tests -1.6* at 8K, while one file stays +0.9/+0.9/+0.3/+0.4/+3.6, so by the declared rule the one-file header goes to heldout-d (HD01). HD01 (heldout-d): fix +2.8/+2.2/+2.4/+2.9 points at 2K-16K (significant) and utility +1.0 to +2.9, but tests -0.7 at 2K is a significant loss (upper bound -0.00004), which the declared criteria forbid. A header variant that keeps the fix gain without displacing test blocks at 2K (for example placed only from 4K) would need a fresh held-out split.

## E037 — Morphological query expansion (Snowball stems or plural forms from the pack vocabulary)

- **Status:** rejected
- **Hypothesis:** The analyzer never stems, so issue prose ('choices', 'serialization') misses code spellings ('choice', 'serializer'); adding index terms that share a stem (or a singular/plural form) to the lexical OR should recover them.
- **Run:** experiments/npkbench/runs/E037-stem-expand-devfast
- **Decision:** Fails the rule on dev-fast. Snowball (up to 3 variants per term; a Django query grows from 73 to 166 terms): fix -2.6/-4.5*/-2.1/+1.8/+0.3 points, tests -1.5/-0.5/-2.4/-5.1*/-6.2*, utility -4.1/-4.4/-3.1/-2.7/-7.2. Plural forms only: fix -1.5/-1.9/-0.5/+1.1/+1.1, tests +0.9/+1.8/-2.6/-1.7/-2.2, utility -0.6/-0.2/-2.4/-1.2/-1.7. Variants add common words (even ~ evening, supports, issues) whose BM25 terms outweigh the rare misspelled identifiers they were meant to reach. The product has no dependencies, so nothing would have shipped without an in-repository rule set anyway.

## E038 — Static Model2Vec embeddings (potion-base-8M / potion-retrieval-32M) as a semantic channel for code

- **Status:** rejected
- **Hypothesis:** E012b's bge-small channel passed the rule from 2K but its CPU cost kept it out; static embeddings (a token table, mean-pooled; about 15 s to index a 15K-block Django pack) might keep part of the gain at almost no cost.
- **Run:** experiments/npkbench/runs/E038-static-channel-devfast
- **Decision:** Fails the rule on dev-fast in every form. Pool-of-100 with potion-base-8M: fix -6.6*/-7.4*/-4.0/-0.5/-2.9 points, utility -3.9/-3.2/-1.4/+5.1/-4.0. Pool with potion-retrieval-32M: fix -4.0/-8.4*/-5.5/-2.4/-4.5, utility -0.6/-3.4/+0.2/0.0/-6.9. Full-pack index (32M): fix -3.2*/-7.4*/-5.8/-4.4/-2.3, tests +4.3* at 1K, utility +1.7/-1.3/-1.4/-2.4/-3.8. Mean-pooled static vectors are too coarse for code: as a fusion channel they displace lexical and definition candidates. The semantic gap for code still needs a contextual encoder (E012b) or a different use of static vectors (not as an RRF channel).

## E039 — Query term frequency in the lexical channel

- **Status:** kept
- **Hypothesis:** The lexical channel deduplicates query terms, so a word the reporter repeats throughout the issue counts no more than one mentioned once; repeating each term min(cap, 1 + floor(log2 tf)) times in the FTS5 OR restores BM25's query-side tf.
- **Run:** experiments/npkbench/runs/HD01-heldout-d, experiments/npkbench/runs/E039-query-tf-devfast, experiments/npkbench/runs/E034-E035-E036-dev
- **Files changed:** `npk/pack/select.py`, `npk/cli.py`, `tests/test_title_weight.py`, `tests/test_query_cleaning.py`, `benchmarks/contract_mutations.py`, `benchmarks/npkbench/arms.py`, `benchmarks/npkbench/report.py`, `README.md`, `CURRENT_ARCHITECTURE.md`, `NEXT_STEPS.md`
- **Decision:** Promoted after HD01 (heldout-d, 401 unused issues, criteria declared before the run): fix +0.1/+1.4/+2.9/+3.2/+4.6 points (significant from 2K), tests +2.8/+5.8/+8.5/+8.8/+12.2 (significant at every budget), utility +2.9/+7.2/+11.3/+11.9/+16.7, no significant loss; its mean utility (9.99) beat the other passing candidate, E034 title x4 (9.54). Full dev: +6.9/+6.8/+10.5/+11.6/+17.1. Product form: title_weight=3 and tf_cap=3 by default (CLI --title-weight/--tf-cap); each term of a multi-line query repeats min(tf_cap, 1 + floor(log2 tf)) times in the lexical OR plus title_weight - 1 if it is in the first line; single-line queries (chat memory) are unweighted. Equals the evaluated prototype on 515/515 dev-fast selections, and title_weight=1, tf_cap=1 equals the previous default on 515/515. Mutants killed: title_weight_ignored, query_tf_ignored, single_line_queries_weighted, title_weight_whole_query. Benchmark arms npk_unweighted (E039 off) and npk_query_baseline (E031 and E039 off). Cost (measured after promotion): FTS5 bm25() runs per phrase and per matching row, and weighting raises the phrase count 1.6-1.8x, so Django lexical ranking takes about 1.9x as long (median 51 -> 107 ms at depth 1000; matching alone 8 -> 18 ms) and median selection time rises about 55% (heldout-d at 4K: 70 -> 109 ms with four workers; p95 246 -> 469 ms). An earlier 'about 15%' figure came from E034 x3 on dev-fast and understated it for large repositories.

## E040 — Code names in the issue title vote more in the definition channel

- **Status:** rejected
- **Hypothesis:** The definition channel gives every code name the query mentions the same vote; a name that also appears in the title is the issue's subject and should vote more (x2 or x4), on top of E034's title weighting.
- **Run:** experiments/npkbench/runs/E040-title-defs-devfast
- **Decision:** No effect on dev-fast: against title x3 alone, x2 and x4 title votes change 1-2 issues per budget (fix +1.0 at 1K, tests -1.0 at 2K and 8K; utility +1.0/-1.0/0/-1.0/0 for x2 and +1.0/-0.6/+1.0/-1.0/0 for x4). Title names are usually few and already decisive in the definition channel's ranking.

## E041 — Title weighting in top-block trimming's member ranking

- **Status:** rejected
- **Hypothesis:** When the best block alone exceeds the budget, trimming ranks its members by file-local BM25 over unique query terms; weighting title terms (x4) there should pick the member the issue is about.
- **Run:** experiments/npkbench/runs/E041-title-members-devfast
- **Decision:** No effect on dev-fast at 512-16K: hunk recall identical to title x4 alone on every issue and budget (member order changes in a few selections without changing which gold lines are covered). Trimming mostly acts at small budgets, where the top block's best member is already decided by the rarest query terms.

## E042 — Top-file module header on the E039 default: only from 4K, or capped at budget//16

- **Status:** rejected
- **Hypothesis:** E036 failed held-out only on a tests loss at 2K while its fix gains held at 4K-16K; placing the header only from 4K, or with a tighter cap, should keep the fix gain without displacing test blocks.
- **Run:** experiments/npkbench/runs/E042-header-dev
- **Decision:** Fails the dev rule declared for HE01 (no significant loss), so nothing went to heldout-e. Full dev vs the E039 default: from-4K fix +2.2/+2.1/+2.0 points at 4K/8K/16K (significant) but tests -1.2 at 8K (significant); cap budget//16 fix +0.7 to +2.0 (significant at 1K, 2K, 8K, 16K) and the same tests -1.2 at 8K; the original E036 header likewise. The header's tokens displace tail test blocks; the loss is identical across variants at 8K/16K because the same header is placed there. The trade (about +2 fix for -1 tests points) has positive utility but the declared criteria forbid significant losses; changing that criterion is a policy decision, not something to tune per experiment.

## E043 — Cap queries at 512 distinct lexical terms; append backticked literals in query order

- **Status:** kept
- **Hypothesis:** bm25() cost grows with query terms and matching rows, and E039 repeats terms, so pasted logs with thousands of distinct words take tens of seconds; keeping the first 512 distinct terms (above the p99 of every split) bounds the cost without touching ordinary issues. Separately, explicit literals were appended by iterating a set, whose order depends on PYTHONHASHSEED.
- **Run:** experiments/npkbench/runs/E043-term-cap-long-queries
- **Files changed:** `npk/pack/select.py`, `tests/test_query_term_determinism.py`, `benchmarks/contract_mutations.py`, `benchmarks/npkbench/data.py`, `benchmarks/npkbench/prototypes/term_cap.py`, `README.md`, `CURRENT_ARCHITECTURE.md`, `NEXT_STEPS.md`
- **Decision:** Kept as a robustness guard. Queries under the cap are unchanged by construction (dev-fast: 511/515 selections identical to the E039 run; the 4 differences are pylint-7080, which has 522 terms). Latency on Django (4K): 1,000 / 5,000 / 20,000 synthetic identifiers 8.4 / 39 / 114 s -> 2.2 / 3.0 / 4.1 s. On the ten benchmark issues above the cap (long-queries split, heldout-e excluded): median latency 1.2 s -> 0.74 s (max 3.5 -> 1.5 s); fix 0/0/-8.3/-10.0/+1.4 and tests +10/+10/+10/+10/0 points vs uncapped, none significant (n=10; 43 of 50 issue-budgets identical). The literal-order fix removes hash-seed dependence (six seeds give one order); on the exposed dev-fast issue, selections were already identical across seeds. Mutants query_term_cap_ignored and explicit_literals_in_hash_order are killed.

## E044 — A second test mate (for the second-ranked implementation file) at large budgets

- **Status:** rejected
- **Hypothesis:** Regression-test recall is the lowest target (held-out 0.42 at 16K vs 0.64 for fix) and the test mate places one test block; at large budgets a second mate, for the second-ranked implementation file, should find more regression-test sites at little cost.
- **Run:** experiments/npkbench/runs/E044-second-mate-dev, experiments/npkbench/runs/E044-second-mate-devfast
- **Decision:** Does not replicate. Full dev (300) vs the default: from-8K tests +0.8 (8K, not significant) and +0.95 (16K, lower bound barely above 0), fix -0.17/-0.17, utility +0.30/+0.11 (mean 0.08); from-4K fails (fix -2.6 at 4K, significant). On the 197 dev issues outside dev-fast, where it was not screened, the from-8K variant has utility -0.9 / -0.7 at 8K/16K (fix -0.7/-0.5, tests -0.2/+1.2): the full-dev pass rests on the dev-fast issues. The HE01 plan declared for E044 would have sent the from-8K variant to heldout-e; that confirmation was deliberately not run, which can only prevent a promotion, so heldout-e stays unused for a stronger candidate. Dev-fast screen: tests +2.75 at 8K (significant), utility +2.9/+1.0 at 8K/16K.

## E045 — A cross-encoder reorders the top 10 fused candidates (ms-marco MiniLM, bge-reranker-base)

- **Status:** rejected
- **Hypothesis:** Top-1 precision limits 1K-2K recall (the first gold block is ranked first for 38 of 103 dev-fast issues) and re-weighting existing features cannot fix it (E011); a cross-encoder that reads the issue and each candidate together is new evidence and might reorder the head correctly.
- **Run:** experiments/npkbench/runs/E045-rerank-dev
- **Decision:** Fails decisively on the full dev split (screened there directly). MiniLM: fix -15.8/-12.8/-8.8/-1.1/-0.3 points at 1K-16K (significant at 1K-4K), tests +4.3 (1K, significant)/+3.7/+1.7/-0.6/-0.7, utility -11.0/-9.0/-6.7/-1.6/-1.4. bge-reranker-base: fix -14.8/-11.7/-8.0/-0.4/+0.1 (significant at 1K-4K), utility -11.0/-12.1/-5.0/-1.7/-0.4. Both web-passage rerankers prefer prose-like blocks (tests, docs) that read like the issue over the implementation code; they also cost 1.9 s (MiniLM) and 10.5 s (bge) median per query on one CPU thread. A code-aware reranker would be needed; general-purpose ones are not an opt-in candidate.

## E046 — Modifier-prefixed declarations and bare member names as JS/TS/Java definitions (compile time)

- **Status:** rejected
- **Hypothesis:** E032's structural definitions (declarations after export/public/static/... modifiers, and a method's bare name) helped JS/TS and Java on ood-multi-dev but hurt Rust; scoped at compile time to JavaScript, TypeScript and Java, they should let the definition channel find more fix sites on poly-dev without the Rust cost.
- **Baseline run:** experiments/npkbench/runs/P001-polybench-dev
- **Run:** experiments/npkbench/runs/E046-modified-defs-polydev
- **Bench version:** npkbench-1.1
- **Files changed:** `npk/pack/compile.py`
- **Decision:** Fails the dev rule on poly-dev (199 issues; vs P001's default, same issues, the compiler change is the only difference). Fix +2.53 (1K, significant) / +1.01 / +1.38 (significant) / +0.57 (significant) / +0.22 points; tests -0.82 / -0.76 / -0.30 (significant) / -0.89 (significant) / -0.27; utility +1.7 / +0.3 / +1.1 / -0.3 / -0.04. The gain is mostly Java (fix +4.2 at 1K, +2.4 at 4K) with Java's regression-test recall down 0.7-1.9 points; TypeScript is unchanged. Java's test mate cannot mirror FooTest.java to Foo.java (E047), so when definitions change the top implementation file the mate lands on an arbitrary test of the package; E046 is to be re-screened on top of E047 if E047 is kept. Patch saved in the run directory (e046.patch). Compile +5% (13.4 s vs 12.8 s mean), packs +2%.

## H001 — Held-out confirmation: test mate (E016b), top-block trimming (E005c), context map (E017)

- **Status:** kept
- **Hypothesis:** Dev-fast decisions hold on 407 held-out issues under criteria committed before the run (NEXT_STEPS.md, commit e822844).
- **Run:** experiments/npkbench/runs/H001-mate-trim-heldout
- **Bench version:** npkbench-1.1 + docs-3
- **Decision:** E005c confirmed: trimming vs no trimming, fix +3.8 points at 1K (significant), identical at >=2K; utility +2.9/0/0/0/0. E017 confirmed: located fix recall with a 25% map +9.6/+12.3/+13.0/+11.4/+7.2 points over the default's full text, tests +5.3/+5.2/+7.7/+8.0/+8.2 (all CIs exclude zero). E016b confirmed only as a tradeoff: tests up at every budget, fix down 0.3-1.4 points; the 1K utility is -0.012 points with a significant fix loss, so it ships opt-in. Full current default on held-out (definition channel + trimming): fix 0.230/0.309/0.399/0.475/0.575 at 1K-16K (before this loop 0.136/0.206/0.302/0.393/0.490).

## HB01 — Confirmation on heldout-b: budget-gated test mate (E016c) and replication of E002+E005c

- **Status:** kept
- **Hypothesis:** Criteria declared in NEXT_STEPS.md (commit c5ebfe0) before the run.
- **Run:** experiments/npkbench/runs/HB01-heldout-b
- **Decision:** E016c passes (see its record). The definition channel and trimming replicate on fresh data: fix +6.5/+5.8/+9.0/+8.0/+8.3 points at 1K-16K over no-definitions/no-trim (all CIs exclude zero); tests -1.9 to -3.3 (the known tradeoff). Product on heldout-b (mate off): fix 0.178/0.244/0.348/0.428/0.526.

## HC01 — Confirmation on heldout-c: issue-form cleaning of queries (E031)

- **Status:** kept
- **Hypothesis:** Criteria declared in NEXT_STEPS.md (commit a97b080) before the run: utility d_fix + 0.99 d_tests >= 0 at every budget, a significant fix or tests gain at one or more budgets, and no significant loss for any target at any budget.
- **Run:** experiments/npkbench/runs/HC01-query-clean-heldout-c
- **Results:**

```json
{
 "heldout_c_fix_1K_16K": {
  "clean": [
   0.1922,
   0.2631,
   0.3572,
   0.4203,
   0.508
  ],
  "raw": [
   0.1938,
   0.2588,
   0.3504,
   0.4111,
   0.4957
  ]
 },
 "heldout_c_tests_1K_16K": {
  "clean": [
   0.043,
   0.1004,
   0.1317,
   0.1905,
   0.2697
  ],
  "raw": [
   0.0389,
   0.0993,
   0.1257,
   0.1809,
   0.2562
  ]
 },
 "utility_points": [
  0.25,
  0.54,
  1.26,
  1.86,
  2.57
 ]
}
```

- **Decision:** E031 passes all three criteria on 400 unused issues (0 errors). e031_clean vs product: fix -0.2 [-0.7,+0.2] / +0.4 [-0.3,+1.2] / +0.7 [+0.2,+1.3] / +0.9 [+0.3,+1.7] / +1.2 [+0.4,+2.3] points at 1K-16K (16 wins/2 losses at 16K); tests +0.4 [+0.0,+0.9] / +0.1 / +0.6 / +0.9 / +1.4 [+0.2,+2.7]; utility +0.25/+0.54/+1.26/+1.86/+2.57. Product on heldout-c (raw query): fix 0.194/0.259/0.350/0.411/0.496, tests 0.039/0.099/0.126/0.181/0.256.

## HD01 — Confirmation on heldout-d: E034 title x4, E039 (tf + title x3), E035 mirror_any, E036 header, and combinations

- **Status:** kept
- **Hypothesis:** Selection rule and criteria declared in NEXT_STEPS.md (commit 508218c) before the run; candidates chosen on the full dev split by that rule (commit 8fee79a).
- **Run:** experiments/npkbench/runs/HD01-heldout-d
- **Results:**

```json
{
 "mean_utility_points": {
  "combo_qtf3_title3_mate_any_header1": 10.926,
  "combo_qtf3_title4_mate_any_header1": 12.219,
  "combo_title4_header1": 11.633,
  "combo_title4_mate_any": 9.74,
  "combo_title4_mate_any_header1": 11.887,
  "e034_title_x4": 9.537,
  "e035_mirror_any": 0.219,
  "e036_header": 2.04,
  "e039_qtf_cap3_title3": 9.99
 }
}
```

- **Decision:** 401 unused issues, 0 errors; unrounded paired-bootstrap bounds. E034 x4 passes (utility +4.2/+6.3/+9.8/+11.4/+15.9 points, mean 9.54). E039 passes (+2.9/+7.2/+11.3/+11.9/+16.7, mean 9.99). E035 mirror_any fails (fix -0.9 at 4K significant, utility -0.14 at 16K). E036 header fails: fix +2.8/+2.2/+2.4/+2.9 points at 2K-16K (significant) but tests -0.7 at 2K is a significant loss (upper bound -0.00004; the rounded report first showed it as non-significant, so report.paired now flags significance from unrounded bounds). The passing E034 and E039 are alternative lexical weightings with no arm combining them, so by the declared rule only the candidate with the higher mean utility, E039, is promoted. Combination arms that include E035 or E036 pass (e.g. title x4 + header: mean 11.6) but combine failing components and are not eligible; a header variant would need a fresh confirmation.

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

- **Status:** kept
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

- **Decision:** Significant gains on memory-dev (100 questions): bge-small +4.1/+3.4/+4.3/+7.0/+7.7/+5.8 points at 256-8K (CI excludes zero at 2K, 4K, 8K); MiniLM +4.4/+1.4/+1.7/+4.7/+4.4/+4.1 (significant at 4K, 8K). By type (bge): multi-session +8 to +13, single-session-preference +17 to +22, temporal +5 to +13; knowledge-update -3 to -13 at 256-1K. The same fusion hurts code at small budgets (E012), so it cannot be a global default. Productized as the documented semantic/hybrid configuration for chat histories (M006: most of the gain with the shipped MiniLM path).
- **Follow-ups:** M006: shipped hybrid mode on memory-dev; If a dense form wins memory without hurting code, make it the recommended mode for conversation/prose packs

## M005 — Time-window channel for dated conversation memory

- **Status:** rejected
- **Hypothesis:** Relative time expressions (two weeks ago, last Tuesday, in February) resolved against the question date select the sessions that hold the evidence; lexical candidates inside the window form an extra RRF channel.
- **Run:** experiments/npkbench/runs/M005-time-window-memory-dev
- **Decision:** No effect: identical to the product except one win at 4K (+0.5 points; temporal-reasoning 0.732 -> 0.751 at 4K). Pre-run analysis predicted a small ceiling: LongMemEval-S histories span 10-90 days, so period expressions cover every session (reporting lag makes the window run to the question date), and only 3 of 17 parsable memory-dev questions get a selective point window.

## M006 — The shipped semantic/hybrid mode on conversation memory

- **Status:** kept
- **Hypothesis:** The product's existing opt-in semantic compile (local MiniLM embeddings for every block) plus hybrid retrieval (whole-index cosine channel and symbol channel in the RRF) delivers most of M004's prototype dense gain on chat histories.
- **Run:** experiments/npkbench/runs/M006-shipped-hybrid-memory-dev
- **Files changed:** `README.md`
- **Results:**

```json
{
 "hunk_recall_256_8K": {
  "npk_default": [
   0.529,
   0.612,
   0.688,
   0.749,
   0.795,
   0.838
  ],
  "npk_hybrid": [
   0.575,
   0.626,
   0.69,
   0.784,
   0.839,
   0.909
  ]
 }
}
```

- **Decision:** Kept as the documented configuration for conversation memory (no code change). vs lexical default on memory-dev: +4.5 [+0.4,+9.0] / +1.4 / +0.3 / +3.5 / +4.4 [+0.2,+9.2] / +7.1 [+2.8,+12.2] points at 256-8K; largest on preferences (0.67 -> 1.00 at 8K) and multi-session (0.74 -> 0.83 at 8K). Within about 3 points of M004's bge-small pool fusion (-3.3 at 4K, +1.3 at 8K) and indistinguishable from MiniLM pool fusion. Cost: 48.9 s compile per history (one CPU thread) vs 0.25 s; query p50 5.9 ms vs 1.9 ms. Held-out (MH01, 370 questions): confirmed at 4K (+4.2) and 8K (+6.0), neutral at 2K and below; the recommendation is scoped to 4K+ budgets.
- **Follow-ups:** Swap the semantic encoder to bge-small if its pool-fusion edge (+3.3 at 4K) survives memory-heldout

## M007 — Chat-memory queries are unchanged by E031 and E039 (sanity check)

- **Status:** kept
- **Hypothesis:** Issue-form cleaning keeps a query's first line and title/repetition weighting applies only to multi-line queries; LongMemEval questions are single-line (0 of 470 multi-line), so memory selections must be identical.
- **Run:** experiments/npkbench/runs/M007-query-handling-memory-dev
- **Decision:** memory-dev: all 600 selections (100 questions x 256-8K) of the new default equal npk_query_baseline (neither E031 nor E039).

## MH01 — Held-out confirmation of the semantic/hybrid chat-memory configuration (M006)

- **Status:** kept
- **Hypothesis:** M006's gains on memory-dev (+4.5*/+1.4/+0.3/+3.5/+4.4*/+7.1* points at 256-8K) hold on the 370 memory-heldout questions.
- **Run:** experiments/npkbench/runs/MH01-hybrid-memory-heldout
- **Results:**

```json
{
 "hunk_recall_256_8K": {
  "npk_default": [
   0.562,
   0.685,
   0.748,
   0.805,
   0.84,
   0.871
  ],
  "npk_hybrid": [
   0.569,
   0.678,
   0.76,
   0.827,
   0.881,
   0.931
  ]
 }
}
```

- **Decision:** Confirmed at 4K and above only. Hybrid vs lexical: +0.7/-0.7/+1.1/+2.2 (none significant) at 256-2K; +4.2 [+2.2,+6.4] at 4K (38 wins/6 losses) and +6.0 [+4.2,+8.1] at 8K (42/0). The 256-token gain seen on dev did not replicate. By type at 8K: preferences 0.71 -> 0.92, multi-session 0.78 -> 0.85, temporal 0.87 -> 0.92; knowledge-update is lower at 512-1K. README now recommends the mode for chat histories read with 4K tokens or more. Compile cost 44.6 s vs 0.22 s per history.

## O001 — Out-of-distribution check on six never-used repositories (SWE-bench Lite dev)

- **Status:** kept
- **Hypothesis:** The kept changes are not specific to the 12 development repositories.
- **Run:** experiments/npkbench/runs/O001-ood-generalization
- **Results:**

```json
{
 "fix_1K_16K": {
  "no_defs_no_trim": [
   0.304,
   0.37,
   0.565,
   0.652,
   0.667
  ],
  "no_trim_mate_on": [
   0.348,
   0.522,
   0.652,
   0.674,
   0.674
  ],
  "product": [
   0.5,
   0.507,
   0.652,
   0.674,
   0.674
  ],
  "product_mate_on": [
   0.5,
   0.522,
   0.652,
   0.674,
   0.674
  ]
 }
}
```

- **Decision:** Generalizes on the fix target (23 issues: sqlfluff, pvlib, astroid, pydicom, marshmallow, pyvista). Definition channel + trimming vs neither: fix +19.6 [+4.3,+37.0] / +13.8 / +8.7 / +2.2 / +0.7 points at 1K-16K; tests -5/-10/-7.5/-7.5/-2.5 (not significant, same direction as held-out). Trimming alone: fix +15.2 [+2.2,+30.4] at 1K, identical beyond. Test mate (opt-in): tests +5/+15/+10/+5/+5 with no fix loss (20 tasks, lower CI bounds at zero).

## OM01 — Non-Python generalization: SWE-bench Multilingual sample (114 issues, 41 repositories)

- **Status:** kept
- **Hypothesis:** NeuralPack's advantage over standard RAG, and the definition channel's gain, hold outside Python (measurement only; declared in NEXT_STEPS.md before the run).
- **Run:** experiments/npkbench/runs/OM01-multilingual
- **Results:**

```json
{
 "fix_1K_16K": {
  "bm25_60line_split": [
   0.036,
   0.06,
   0.087,
   0.141,
   0.173
  ],
  "bm25_chars1000_split": [
   0.068,
   0.082,
   0.134,
   0.145,
   0.238
  ],
  "no_defs_no_trim": [
   0.093,
   0.113,
   0.156,
   0.233,
   0.302
  ],
  "product": [
   0.11,
   0.164,
   0.197,
   0.269,
   0.32
  ]
 }
}
```

- **Decision:** Holds, at lower absolute recall. Product fix recall 0.110/0.164/0.197/0.269/0.320 at 1K-16K (Python held-out: 0.230/0.303/...). vs BM25 over 60-line chunks: fix +7.4 to +14.8 points and tests +2.4 to +9.8 (all significant); vs ~1,000-character chunks: fix +4.2 (n.s.) / +8.2 / +6.2 / +12.3 / +8.2 (significant from 2K). The definition channel helps outside Python: +5.1/+4.1/+3.6 points at 2K-8K (significant), decisive for Go (2K: 0.002 -> 0.202) and Ruby (0.000 -> 0.125). By language at 2K: PHP 0.33, Go 0.20, Java 0.20 (chunk baseline 0.27), Rust 0.18, Ruby 0.13, JS/TS 0.12 (flat to 8K), C/C++ 0.09. Weak spots (JS/TS, C/C++, Java) must be analyzed on ood-multi-dev, never on this sample.

## OMD01 — Multilingual dev split: product vs chunk baseline, and where non-Python fix sites are lost

- **Status:** kept
- **Hypothesis:** Diagnose the non-Python weakness on ood-multi-dev (186 issues) rather than on the measurement sample.
- **Run:** experiments/npkbench/runs/OMD01-multilingual-dev
- **Decision:** Kept as the development baseline for non-Python work. Product fix 0.146/0.212/0.259/0.328/0.383 at 1K-16K vs ~1,000-character-chunk BM25 0.093/0.120/0.165/0.223/0.270; no-definitions 0.122/0.162/0.209/0.286/0.357. Loss at 2K by language (share of gold hunks): selected 3-4% for C/C++, JS/TS and Rust vs 16-19% for Java, Go, PHP and Ruby. Most misses are ranking losses: missed hunks' covering blocks rank at median 112-401 (C/C++ 401); 13-29% are never retrieved. Covering blocks are large for C/C++ (median 1,086 tokens) and JS/TS (735).

## P001 — First measurement on SWE-PolyBench poly-dev (Java/JS/TS): default vs query baseline vs B002

- **Status:** kept
- **Hypothesis:** Measurement only, before any tuning on poly-dev: how the current default (E031/E039/E043 query handling) does on 199 Java, JavaScript and TypeScript issues from 12 repositories, against the product without query handling (npk_query_baseline) and a BM25 baseline over 1,000-character chunks (B002).
- **Run:** experiments/npkbench/runs/P001-polybench-dev
- **Commit:** da4f293
- **Bench version:** npkbench-1.1
- **Decision:** 199 issues (173 with test edits), 0 errors, 199 packs (mean compile 12.8 s, 34.9 MB). Fix hunk recall at 1K-16K: default 0.195/0.244/0.319/0.404/0.476, npk_query_baseline 0.134/0.182/0.259/0.318/0.387, B002 0.087/0.121/0.176/0.240/0.297. Regression tests: 0.113/0.185/0.276/0.378/0.418 vs 0.082/0.117/0.191/0.269/0.343 vs 0.051/0.077/0.118/0.184/0.263. The query handling passes the declared rule on this new language set (fix +6.0 to +8.9 points, tests +3.1 to +11.0, all significant; mean utility +14.5); against B002 fix +10.8 to +17.9 points (1.6-2.2x) and tests +6.2 to +19.4 (all significant). By language (fix at 2K/16K): Java (74) 0.262/0.486, JavaScript (75) 0.218/0.440, TypeScript (50) 0.258/0.514; TypeScript gains most from query handling (+10 to +19 points). Median selection latency 68-100 ms. Poly-dev is now the development set for JS/TS/Java work; these numbers are the reference before tuning.

## R002 — README re-measurement on heldout: the default after E031 and E039

- **Status:** kept
- **Hypothesis:** Measurement only (heldout was spent on earlier confirmations; E031 and E039 were decided on heldout-c and heldout-d).
- **Run:** experiments/npkbench/runs/R002-readme-heldout-e039
- **Decision:** 407 issues, 0 errors. New default vs npk_query_baseline (which reproduces the previous README row exactly, 0.230/0.303/0.385/0.472/0.569): fix 0.254/0.346/0.452/0.571/0.638 (+2.3/+4.3/+6.8/+9.9/+7.0 points, all significant), tests 0.089/0.180/0.252/0.338/0.423 (+3.0/+3.7/+5.8/+8.2/+12.0, all significant), docs +1.5/+8.5/+0.8/-3.4/+3.1 (none significant). Against the B001 chunk-BM25 baseline: fix 2.0-2.5x (significant at every budget), tests 1.5-2.1x (significant from 2K), docs no longer significantly different at any budget (at 2K 0.25 vs 0.31; was 0.17 vs 0.31).

## R003 — README re-measurement on the multilingual sample: the default after E031 and E039

- **Status:** kept
- **Hypothesis:** Measurement only (ood-multi-sample, never used for decisions).
- **Run:** experiments/npkbench/runs/R003-readme-multilingual-e039
- **Decision:** 114 issues, 0 errors. New default vs npk_query_baseline: fix 0.198/0.260/0.301/0.364/0.455 vs 0.110/0.164/0.197/0.269/0.320 (+8.9/+9.7/+10.4/+9.5/+13.5 points, all significant), tests +2.4/+3.1/+6.7/+12.4/+10.8 (significant except 2K). Against B002 (BM25 over 1,000-character chunks): fix +13.0 to +21.9 points (2.2-3.2x), tests +4.6 to +17.4 (1.9-2.6x), all significant. Non-Python recall moved from about half of Python's to about three quarters (0.260 vs 0.346 at 2K).

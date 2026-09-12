# Cycle 26: spelling indexes do not solve behavior retrieval

**Decision: PIVOT REQUIRED.** Keep the compiled product's current lexical
retrieval. New spelling indexes improve literal-name lookup, but none establishes
a general advantage on the existing behavior questions. Everything added in this
cycle remains research code under `benchmarks/`; no product schema, default flag,
provider dependency or model call was added.

NeuralPack still compiles source once into a local `.npk`, searches it locally for
each question, and gives literal source passages to the application's chosen AI.
The research question here is whether a reusable spelling index makes that search
better enough to justify its compilation, disk and update costs.

## Frozen comparison

The source is the same 153 public SQLAlchemy 2.0.43 documentation files from
commit `a303102a7bfbbb6da992a89b6610d71f080fb5eb`, licensed under MIT. Every request
has 527,598 corpus tokens and 527,807 compiled available tokens, using the explicit
characters/4 estimate. These are per-request quantities. The corpus and complete
source hashes were inherited from cycle 24 and checked again.

All six methods use the same 1,141 blocks, the same maximum 2,048-character
splitting policy and the same provenance-budgeted passage assembly. We sweep
1,024 and 4,096 token caps with three shuffled repetitions. The 202 tasks comprise
96 previously inspected spelling probes, 96 probes from previously unsampled
names, and the ten existing executable behavior scenarios. The new probes are
generated from this known corpus; they are not sealed independent validation.

The controls are current compiled lexical search; normalized-source FTS5; a
normalized spelling dictionary fused with lexical search; the same dictionary
limited to explicitly marked names; joined/split query variants requiring no
additional index; and real local MiniLM hybrid retrieval. Splitting and
concatenating words are established IR operations, documented for example in
[Lucene's WordDelimiterGraphFilter](https://lucene.apache.org/core/10_3_1/analysis/common/org/apache/lucene/analysis/miscellaneous/WordDelimiterGraphFilter.html)
(checked September 7, 2026). This SQLite experiment is not a Lucene implementation
or its token-position graph.

The optional encoder is `sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with cached weights, 256-token maximum,
2,000-character document prefixes, masked-mean pooling and L2 normalization.
It uses transformers 4.57.6 and torch 2.8.0+cu126 on CPU with two threads. The
hybrid's existing similarity gate actually used embeddings for 53/96 known and
64/96 new spelling probes at each cap, and all ten behavior scenarios. Its costs
therefore include real encoder inference, with no generative or API calls.

## Source diagnostics, not answer accuracy

**EMPIRICAL.** Literal identifier presence is checked in selected source bodies,
never only in path labels. Behavior checks require all annotated source passages.
These are separate metrics and neither establishes whether an LLM answers
correctly. Each fraction below counts unique tasks once, not repeated trials.

| Method | Known spelling 1K / 4K (of 96) | New spelling 1K / 4K (of 96) | Behavior 1K / 4K (of 10) |
| --- | --- | --- | --- |
| Current lexical | 72 / 83 | 69 / 89 | 1 / 3 |
| Normalized FTS | 82 / 93 | 86 / 96 | 0 / 3 |
| Spelling dictionary + lexical | 87 / 93 | 88 / 96 | 0 / 0 |
| Marked dictionary + lexical | 87 / 93 | 88 / 96 | 0 / 0 |
| Query variants + lexical, no extra index | 81 / 95 | 86 / 96 | 0 / 1 |
| Local MiniLM hybrid | 68 / 85 | 64 / 78 | 0 / 4 |

The normalized FTS wins 19 new spelling probes and loses two against current
lexical at 1K. At 4K it wins seven and loses none. The no-index variant also
reaches 96/96 at 4K, and at 1K has 17 wins with no losses. That cheap control is
enough to reject any claim that the larger dictionary is necessary for these
gains. Both dictionary policies pass none of the complete behavior-passage checks
at either cap. Their extra specificity did not make the retrieval more sufficient.
Their selected contexts are identical in all 404 task/cap pairs, so limiting the
dictionary to marked names earned no additional behavior on this corpus.

![Source-retention curves](../experiments/results/cycle26-source-curves.png)

The curves use actual mean selected tokens, with both methods and caps shown.
The machine-readable summary also contains the descriptive token/metric Pareto
frontier. It is a frontier over these measured points, not an exact global knee,
minimum sufficient context or answer-quality guarantee.

**EMPIRICAL.** Corrected query-time medians below include index checks, ranking
and passage assembly. Each task first takes the median of three trials; each
cohort then takes the median across tasks. Units are milliseconds, not sub-ms
claims at this scale. Host load was uncontrolled; agent CPU benchmarks, tests,
archive compression and LIVE I/O did not overlap these measurement runs.

| Method | New spelling 1K / 4K ms | Behavior 1K / 4K ms |
| --- | --- | --- |
| Current lexical | 18.23 / 38.27 | 54.86 / 82.99 |
| Normalized FTS | 7.20 / 7.73 | 36.19 / 62.30 |
| Spelling dictionary + lexical | 19.54 / 43.61 | 67.34 / 87.91 |
| Marked dictionary + lexical | 21.45 / 42.72 | 65.69 / 90.80 |
| Query variants + lexical | 19.66 / 40.42 | 96.83 / 121.90 |
| Local MiniLM hybrid | 68.13 / 107.79 | 362.84 / 415.94 |

The first adapter unnecessarily ran current lexical search and discarded it
before querying normalized FTS. Its latency is retained as a failed measurement
implementation. A regression now prohibits that extra work. The corrected
adapter reran all 7,272 observations with the same tasks, compiled indexes and
budgets. The audit compares all 2,424 unique cells across the two runs, including
literal source, status and metric, rather than assuming timings imply equivalent
outputs. Only the corrected query run supplies the table above.

## Compilation, updates and a concurrent-writer counterexample

**EMPIRICAL.** One initial combined research index build took 2,920.11 ms wall
and 1,828.13 ms CPU, occupied 16,121,856 bytes, and wrote 135,879 spelling forms.
That container includes both normalized FTS and the spelling dictionary; its
entire size or construction time cannot be attributed to either component alone.
Process RSS before/after was 56,983,552 / 56,483,840 bytes. These are endpoints,
not peak memory measurements. The corrected query run reused that exact build
and records its original provenance; it does not claim another compilation.

The index caches per-file content identities, invalidates changed owners, and
updates only their blocks. Changes are explicit synthetic marker additions to
copies of complete public source files; the original corpus is unchanged.
The 1% and 10% cases round up to 2 and 16 files out of 153. Each case has three
shuffled trials. Copying, source compilation and full validation are outside
the measured side-index steps; the core update is separately recorded.

| Changed files | Before repair: incremental / fresh ms | After repair: incremental / fresh ms | After repair: core update ms |
| --- | --- | --- | --- |
| 0 | 23.18 / 1,846.50 | 26.43 / 3,446.38 | 320.96 |
| 1 | 24.51 / 1,787.66 | 26.99 / 3,578.55 | 317.61 |
| 2 | 90.02 / 2,847.19 | 100.78 / 3,173.41 | 390.19 |
| 16 | 253.33 / 2,037.69 | 401.50 / 3,219.05 | 736.13 |

Large variation also affects fresh builds, so these separate runs do not isolate
the performance cost of the lock repair. Small CPU timings are quantized on this
host and may round to zero; that does not mean the operation consumes no CPU.
The fast incremental step is ordinary avoided rebuilding of an optional index,
not a new end-to-end product speedup. The default product has no such side index.

The initial updater read cached ownership before acquiring its write lock.
A controlled interleaving lets another writer update a different file between
that read and the first writer's transaction. The first writer can then leave a
mixed index while recording its own parent's identifier. The new regression
reproduced this failure before repair. The fix acquires `BEGIN IMMEDIATE` before
reading either ownership or policy metadata. The actual product compiler already
used that transaction ordering; no production concurrency repair is claimed.

Both old sequential and corrected update runs match fresh indexes on five logical
tables and ten query/ranker combinations per case/trial. The audit independently
rechecks 120 table comparisons and 240 rank comparisons across both runs, plus
parent artifact hashes, full integrity and exact compiled source manifests.
Sequential equivalence does not supersede the old writer's concurrency failure.

The research reader holds a SQLite snapshot and refuses mismatched parent roots
or unsupported versions. That check is separate from external integrity checks
or publisher authentication. Normalized spelling collisions remain explicit;
they do not prove that two names refer to the same program object. See the
[labeled counterexample and limited proof](math/SPELLING_COLLISIONS.md).

## Keep, discard and next hypothesis

Keep the source-normalization and no-index controls for focused lookup work,
the controlled concurrency regression, transaction repair and benchmark-adapter
assertion. Keep source spans, selection budgets, current query preservation and
uncalibrated risk reporting. Reject default promotion of these spelling indexes,
mandatory embeddings, and claims of answer accuracy from retained names.

There are no new target-model answers, target API tokens, billing observations
or monetary savings in cycle 26. Dollar cost and billing break-even are N/A.
Per-task output records include corpus, available and selected tokens, plus an
explicit hypothetical full SOURCE/QUESTION frame estimate of 530,357–530,704
tokens; they exclude provider and system wrappers. A cheaper search on a spelling
probe does not establish total savings on a real application workload.

The next highest-value hypothesis is **CONJECTURE**: operation-aware static query
views may better isolate the relevant action and state transition in long
executable scenarios than generic lexical OR, name normalization or dictionary
fusion. Test those views against the already available clause and lexical
baselines, freeze variants before calling an answer model, and retain negative
constraints. Prior clause experiments already failed to establish superiority;
renaming their approach is not new evidence.

Reproduction entry points are `benchmarks.spelling_index_eval`,
`benchmarks.spelling_index_updates`, `benchmarks.cycle26_record` and
`benchmarks.spelling_index_plot`. Completed runs and failed implementations are
retained with executed-source snapshots. Final test and mutation counts are in
`experiments/results/cycle26-record.json`; the first mutation attempt's failure
classification is preserved separately rather than silently overwritten.

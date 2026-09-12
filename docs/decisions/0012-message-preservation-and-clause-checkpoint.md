# Preserve arbitrary messages; keep clause retrieval experimental

Status: accepted message repairs; second answer-model evaluation still running.
Verdict at this checkpoint: **PIVOT REQUIRED**. The compiled BM25 runtime is
unchanged. Retrieval superiority has not been established.

## Newly reproduced failures

The older chat planner labeled generic deduplication and message rearrangement
as lossless. Five permanent counterexamples disproved that assumption. It removed
a distinct JSON string because whitespace normalization made it resemble another
string; discarded repeated transaction records whose occurrence count mattered;
deleted a requested license notice; changed literal blank lines; and rearranged
conversation messages while dropping tool metadata. Every changed result passed
the previous presence/query/system checks.

Automatic deduplication, boilerplate deletion, and prefix rearrangement are now
removed, together with `ContextDeduplicator`, `PrefixOptimizer`, `enable_dedup`,
and `enable_prefix_opt`. This intentionally removes those legacy APIs. Passing
the removed flags raises an error instead of silently doing nothing. Provider
cache behavior is not inferred from rearranging arbitrary messages.

The planner only considers user source content for selection. It skips the full
current question and preserves assistant, tool, system and other instruction
messages. The invariant gate checks message counts and envelopes, including tool
linkage, and exact non-user messages. Missing retrieval measurements now mean
`uncalibrated:unknown`; they no longer imply a lossless transformation. Trace or
conversation compaction and further extraction cannot borrow an earlier retrieval
score as evidence for their unmeasured changes.

These checks do not prove that every selected user-source passage is sufficient,
nor that query-term coverage is calibrated omission risk. The risk maximum for
an unmeasured transform is an ordinal admission policy, not a failure probability.

The obsolete `benchmarks/profiler.py` was also deleted. It still used a hardcoded
historical savings number and an assumed network round trip. The surviving scale
profiler no longer invokes the removed stages. None of those old economic numbers
are evidence for this product.

## LOCAL repair measurements

All five targeted cases changed before repair; all five are byte-preserved after
repair. This is deterministic preservation evidence, not answer accuracy.

Three shuffled fresh-process trials compare commit `2f4543d` with the repaired
client. Each process uses four real public-source contexts, one initial call and
two warm repeats. Network access is denied and the target is MOCK. The table
reports median warm latency; timing includes tracing and MOCK dispatch, excludes
imports, and measures this older client rather than compiled FTS5 retrieval.

| Available context, chars/4 estimate | Before ms | After ms |
| ---: | ---: | ---: |
| 2,202 | 5.72 | 4.70 |
| 26,004 | 66.05 | 50.56 |
| 51,938 | 112.51 | 93.82 |
| 102,491 | 206.69 | 190.48 |

All 36 repaired dispatches preserve the complete input messages. The previous
client changed all nine smallest-context dispatches; the 27 larger dispatches
were already unchanged. The smallest first call was slightly slower, 7.90 to
8.82 ms. These are modest overhead changes, not a 10× performance claim. No CPU
tests or mutation runs overlapped profiles; LIVE answer IO and uncontrolled host
activity did. Raw messages, inputs, code snapshots, timings and hashes are saved.

**681 tests pass, two skip; all 51 mutation checks are killed.** This includes
the original dependency/query/fallback mutants and four new whitespace, history,
envelope and risk mutations. An earlier full run reported the three deleted files
as unreadable tracked files. Staging their actual deletion resolved that repository
state; the scanner was not weakened. The final full run passes.

## Seed research checkpoint

The frozen LOCAL comparison covers 36 developer-authored questions: eight new
stdlib behavior cases and 28 previously inspected controls. Each question has
559,738 available estimated tokens, with the same 2,183 blocks for every method.
Budgets are 512, 2,048 and 8,192 chars/4 estimates, not actual model token counts.
All 540 selected contexts reconstruct from pinned source paths and line spans.

At 2,048 tokens on the eight new cases, BM25 retained every labeled required
span on three tasks; balanced clause retrieval did so on two; both clause-fusion
variants did so on none. At 8,192 the counts were five, three, three and five for
BM25, balanced clauses, ordinary clause fusion and focused fusion respectively.
These are source diagnostics, not task success. Weighted field search matched
BM25's complete-span counts on the new cases.

Repeated warm ranking medians on the full corpus were 8.54 ms for BM25, 6.82 ms
for weighted fields, and 18.51–19.85 ms for clause variants. The research sidecar
took 70.78 ms to build and occupied 3,911,680 bytes. It has no promoted runtime or
incremental-update API. Additional clause search did not earn product complexity.

The frozen answer evaluation compares BM25, weighted fields and balanced clauses
at 2,048/8,192 tokens, plus no-context controls. Methods were chosen after LOCAL
inspection and before LIVE answers. Questions, sources and payloads are frozen;
there are no generative optimization calls. The completed Nemotron run made 245
unique attempts and obtained 173 answers; 66 HTTP 503 and six HTTP 429 failures
remain missing. No completed request is retried. On the new cases, balanced
clauses had zero wins and two losses against BM25 at 2K, and one win and one loss
at 8K, with four and two missing paired comparisons respectively. This sparse
evidence does not justify promotion. The DeepSeek run is still in progress and
is not included as a completed result at this checkpoint.

Dollar cost remains N/A. No full-context or remote-preprocessor answer arm was
run in this experiment, so it establishes no complete economic comparison.
No-context answers measure prior model knowledge, not empty-context optimization.

## Next step

Finish and audit the already frozen second-model run. Then test a separate
corpus-completeness hypothesis: the present collection contains implementation
files but lacks the corresponding collections/functools/contextlib API manuals.
Adding those exact-version manuals might supply the semantic bridge that extra
query splitting failed to provide. Keep corpus additions explicit and compare
all methods at identical budgets within each corpus; do not tune current answers.

# Cycle 28: executable answers after the rival retrieval comparison

Verdict: **PIVOT REQUIRED**. The rival's retrieval lead was reproduced. Stronger
seed systems improve source retention, but superiority in actual answers remains
unproven. This is an open checkpoint, not completion of the research goal.
All numerical findings below are **EMPIRICAL**. The original archived checkpoint
has 76 attempts; the later 100-attempt continuation is recorded at the end.

## What was tested

The frozen Rich 14.2.0, Jinja2 3.1.6 and Werkzeug 3.1.3 corpus contains 155 Python
files and **558,878 available NIM tokens per request**. This is a per-request raw
source count; it is not a sum across tasks, a sum of chunk counts, or the earlier
519,017-token cl100k representation. Both units and source representation matter.

Fifteen questions have executable answers and source traces reproduced in two
fresh processes on CPython 3.12.14 / Windows. They test falsey/missing values,
Unicode terminal width, platform behavior, ordering, conversion fallbacks and
multiple required facts. The questions were informed by inspected source. They
are development diagnostics, not an unseen sealed evaluation. Trace lines are
provenance and are not minimum sufficient context.

Seven shared-block NPK arms and two native CRISP arms each selected context at
512, 2,048 and 8,192 exact NIM tokens. The arms are body BM25, uniform metadata,
shared CRISP scoring with literal raise lookup, two MiniLM hybrid variants, Qwen
hybrid, a local cross-encoder after Qwen hybrid, and two native CRISP variants.
Graph expansion is not promoted. The CRISP snapshot is read-only and its own
chunking/reduced views are explicitly distinguished from shared NPK blocks.

The independent preflight audited **405 selections and 6,803 source items**,
including native full, signature and focus views. It reconstructed source spans,
recounted assembled contexts, checked preserved questions and fallback flags,
and replayed NPK fusion/packing. No selection was empty or exceeded its cap.
This establishes selection provenance and budget compliance, not sufficiency.

The frozen LIVE plan has **435 observations and 416 distinct model requests**,
including no-context and full-context controls. Identical requests are shared,
not counted as independent samples. Plan SHA-256:
`4b7685af9b9e2c9e35a782b599d5f0ff3d248435e220e920b8be5c052b3ba88c`.
The execution order was shuffled before any answers, starting with the 2K arms
and no-context controls. Full-context calls have not been attempted.

## Actual target answers: incomplete

The target is `nvidia/nemotron-3-super-120b-a12b`, temperature 1.0, top-p 0.95,
thinking disabled, and a 2,048-token output limit. All optimization is LOCAL;
these LIVE calls only answer the final question. An exact JSON oracle grades
the answers without a generative judge. There is one stochastic sample per
distinct request. This cannot establish reliability across seeds or models.

At this checkpoint, **76 calls were attempted, 59 returned answers, 16 returned
HTTP 503 and one returned HTTP 429**. The run is paused after consecutive service
overload failures. Failed or uncertain requests are not automatically retried.
The endpoint supplied no usable Retry-After hint in these failures. An earlier
automatic-review timeout occurred before process creation and made zero calls;
the subsequent authorized execution is recorded separately.

The independent audit checks raw responses, usage, request identity, source
contexts, frozen grading and exact framed prompt counts. Local input counts
match provider usage on **all 59 distinct successful responses**. Shared
observations do not increase this denominator. The stable report stores its
own source and the exact ledger snapshot it used:
`experiments/results/cycle28-library-answer-76-stable.json`.

Every method has missing task outcomes, so every arm's accuracy is **N/A**.
The following are counts, not an available-case leaderboard. Each row plans
15 tasks; failures and pending tasks remain missing outcomes.

| Method at 2K unless control | Answers returned | Exact successes | Failed calls | Pending |
|---|---:|---:|---:|---:|
| NPK body BM25 | 9 | 3 | 1 | 5 |
| Uniform metadata | 4 | 2 | 5 | 6 |
| Shared CRISP scorer + raises | 7 | 2 | 1 | 7 |
| MiniLM body hybrid | 5 | 2 | 0 | 10 |
| MiniLM metadata hybrid | 8 | 2 | 2 | 5 |
| Qwen metadata hybrid | 2 | 1 | 1 | 12 |
| Qwen + local reranker | 7 | 1 | 2 | 6 |
| Native CRISP guarded views | 7 | 4 | 1 | 7 |
| Native CRISP BM25 + raises | 7 | 3 | 3 | 5 |
| No-context control | 5 | 0 | 1 | 9 |

Some observations share the same successful response, so these rows sum to more
than 59. Paired comparisons are also very incomplete: native guarded CRISP has
one win, one loss and two ties against NPK body BM25, with 11 missing pairs.
That is not evidence of a winner. Even the no-context control remains incomplete;
the five observed failures cannot establish that these tasks resist memorization.

Two failures deserve explicit treatment. One redirect answer gives the string
`308 Permanent Redirect` where the oracle expects numeric `308`. The question's
wording may permit a format ambiguity. The frozen primary grade remains failed;
it is not silently relaxed after observing the answer. A terminal-width answer
contains mojibake; the saved question and request correctly contain `界界`.
That is observed output corruption, with no evidence of corruption in the query.
Neither issue is grounds to rewrite this frozen task matrix after the fact.

Published dollar cost and break-even requests are **N/A**: there is no verified
billing rate and local compute price. A free development endpoint does not prove
commercial savings. Full-context performance and broad answer-quality superiority
remain unmeasured in this plan.

## Costs of real local models

These were actual local model executions with network access disabled in model
loading and inference, not n-gram vectors called semantic embeddings.

| Component | Exact model/revision | Measured work |
|---|---|---|
| MiniLM encoder | `sentence-transformers/all-MiniLM-L6-v2` at `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | CPU document encoding 112.99 s; query median 11.19 ms |
| Qwen encoder | `Qwen/Qwen3-Embedding-0.6B` at `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | GPU document encoding 127.51 s; query median 43.05 ms |
| Cross-encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` at `233902d25c440f23af6f7d6e94d2946bac0bee0a` | CPU reranking 160 candidates: 12,902 ms median per query |

There are 3,513 encoded source blocks. The two document matrices occupy
5,396,096 and 14,389,376 bytes. Encoding times exclude model loading, and the
models use different input/truncation policies and hardware. These are not
algorithm-only speed comparisons. Model revisions, token limits, instructions,
precision and actual array hashes are frozen in the encoder/selection plans.
MiniLM uses the trusted cached revision; it did not receive an independent
pre-run weight-file fingerprint. Qwen model bytes were checked against the
earlier download record. The reranker plan records actual local model hashes.

The expensive reranker has not earned product integration. No encoder, metadata
index or graph feature is promoted from this partial answer study. Semantic
sidecar incremental updates are also not established by these full-index runs.

## Attacks and repairs

A reproducible reporting race allowed a long audit to read older outcomes and
then record the hash of a newer ledger. The audit now captures the bytes once,
checks that the ledger remained unchanged, and archives that exact snapshot.
A concurrent-write regression fails before the repair. The completed answer
reports were run while execution was paused; they remain valid.

The LIVE benchmark executor now supports explicit request spacing using a
monotonic clock. Waiting happens before an attempt is marked STARTED, so a
cancelled wait cannot create a phantom uncertain request. The option requires
one worker when enabled. Retry-After integer/date hints are parsed and recorded
without automatically repeating a request. These changes belong to development
evaluation; they add no remote call to the product runtime.

The final full suite passes **901 tests with 22 skips** on bundled Python
3.12.14, and all **88 mutation checks** catch their planted defects, including
the original three critical mutants. Twenty skipped oracle tests require the
canonical Python 3.12.10 interpreter; two require symlink permissions. These
environment-dependent checks remain outstanding. Results are recorded in
`cycle28-final-evidence-full.xml` and `cycle28-final-evidence-mutations.json`.
The mutation baseline now hashes all Python source in `npk`, `benchmarks` and
`tests`; earlier checks bound only product source. Check these result files for
the completed counts rather than attributing older runs to changed code.

The verified behavior archive is `experiments/results/cycle28-library-checkpoint.zip`:
63,595,390 bytes, 1,989 files, SHA-256
`d7fd2de82964cee8547142da1a7e9fff2e84c1537f6863b1ff8e4109fa4a24a6`.
Every member was read back against its hash, ZIP CRCs passed, 90 numeric arrays
were checked, and 504,916 decoded/SQLite pattern checks found no recognized
credential pattern. This is not proof against every possible secret format.
The archive includes the exact code, responses, ledger snapshots, sources and
tokenizer for this checkpoint; it explicitly records that the goal is open.

## A simpler speed challenger

The tokenizer's documented no-offset batch API was tested before implementing
custom tokenization. It matched every token ID in 6,897 differential cases,
including all frozen seed contexts, added special tokens, random Unicode and
boundary probes. In 270 public selection runs it preserved all contexts/counts.

| NIM context cap | Ordinary API median | No-offset API median |
|---|---:|---:|
| 512 | 56.18 ms | 47.69 ms |
| 2,048 | 149.93 ms | 127.18 ms |
| 8,192 | 465.45 ms | 387.00 ms |

These are three paired passes on 15 questions with the outer count cache cleared
per query, loaded tokenizers, and uncontrolled host load. The approximately
15–17% gain is useful but not 10× and not evidence of equivalence for arbitrary
tokenizers. This challenger remains separate from the default runtime. Source:
[the upstream tokenizers API](https://huggingface.co/docs/tokenizers/api/tokenizer#tokenizers.Tokenizer.encode_batch_fast).

## Keep, discard, investigate

Keep exact budget admission, preserved query intent, the stronger audited
baselines and response provenance. Discard an answer-win claim based on partial
responses or source-retention percentages. Do not promote the costly reranker
or generic graph expansion without measured answer gains.

The next local hypothesis is that exact packing repeatedly tokenizes mostly
unchanged candidate assemblies. Reuse may offer a larger gain than omitting
offsets, but BPE joins and added-token rules make simple additive accounting
incorrect. Any faster admission method must reproduce the exact selected
evidence and fallback behavior, not just stay below a cap. The known metadata
ranking loss also remains: short `__exit__` boilerplate can crowd out the longer
traceback constructor, despite the correct block being in the seed pool.

When the endpoint recovers, continue only never-attempted frozen requests under
the recorded pacing/pause rules. SQLAlchemy source expansion and its existing
answer plan remain open. This small inspected behavior diagnostic does not
replace that work or meet the final independent-validation standard.

## Later checkpoint: 100 attempts

After approximately half an hour of cooldown, another 24 never-attempted
requests ran with at least 15 seconds between dispatch starts, one worker and
a three-consecutive-failure stop rule. Seventeen returned answers and seven
returned HTTP 503. The batch finished its bound; no request remains active.

The ledger now contains **100 DONE attempts, 76 answers, 23 HTTP 503 failures
and one HTTP 429 failure**. The independent report
`experiments/results/cycle28-library-answer-100.json` was generated with a
quiescent ledger and archived its exact snapshot. All **76 distinct successful
input counts match** provider usage. The prior 76-attempt archive is immutable
and remains a valid historical checkpoint.

Every arm still has missing outcomes, so accuracy remains N/A. At 2K, native
guarded CRISP has two wins, one loss and four ties against body BM25, with eight
missing pairs. The no-context control now has one correct answer among six
returned answers, with nine missing outcomes. These incomplete observations
neither establish a winner nor justify ignoring model prior knowledge.

The local counting hypotheses have since been measured and attacked: the piece
cache loses and batching trades CPU for latency. See `CYCLE28_COUNTING_COST.md`.
Canonical Python access is restored; **931 tests pass, two symlink tests skip,
and all 91 mutants are killed**. The earlier 20 pending version-pinned oracle
checks now pass without changing their definitions. The separate 3.12.14 LIVE
behavior plan remains unchanged. Verdict: **PIVOT REQUIRED**.

## Source-identity and 108-attempt checkpoint

The original plan now has 108 DONE attempts: 81 answers, 26 HTTP 503 failures
and one HTTP 429 failure. Its last eight-request batch paused after three
consecutive 503s. All 81 successful prompt counts match actual usage; 40
first-stage requests remain never attempted. Every answer arm remains incomplete.

The new source-identity cycle independently audits 270 selections and 3,742
source items, with zero budget violations. Labels displace listed implementation
bodies on some tasks at the same cap and are not promoted. A corrected post-hoc
analysis counts returned null/malformed answers separately from missing transport.
It does not equate whole-function exposure with evidence sufficiency.

The UTF-8 executor repair preserves non-English questions under Windows locale
encodings. A separate 45-request target configuration diagnostic preserves the
original questions, evidence and grading, changing target reasoning flags and
output cap together. Its ledger is empty: automatic approval review timed out
on the six-call batch and the permitted retry. User guidance is pending.

Current bundled checks: 924 tests pass, 22 explicitly skip, all 96 mutants die.
Twenty skips require canonical Python; two require symlink permission. Earlier
canonical full checks preceded the UTF-8 repair; 24 targeted checks passed after
it. The final canonical full rerun is pending after two approval timeouts.

See [the complete cycle record](CYCLE28_SOURCE_IDENTITY.md) for failed ideas,
counterexamples, measured costs and the next hypothesis. Verdict: PIVOT REQUIRED.
The original evaluation and SQLAlchemy work remain open.

## Current 135-attempt checkpoint

The earlier approval timeouts are resolved by the current execution environment.
The original non-thinking plan now has **135 terminal attempts: 94 LIVE answers,
40 HTTP 503s and one HTTP 429**. The independent reporter verifies all 94
successful hosted prompt counts exactly. The most recent bounded batch produced
four answers and seven service errors, then paused after three consecutive 503s.
Thirteen first-stage requests remain never attempted. DONE and uncertain
requests are not retried. The report is `cycle28-library-answer-135.json`.

At 2K, BM25 has four correct outcomes among 11 answered tasks; native guarded
CRISP has six among 12. These incomplete arms retain N/A accuracy. Their nine
jointly answered pairs contain one BM25 win, two CRISP wins and six ties; six
pairs remain missing. This does not establish an answer-quality winner.

The separate target-profile diagnostic has attempted all 45 payloads once:
28 answers and 17 HTTP 503s. All successful prompt counts match. At identical
contexts, its comparison with the 135-attempt original checkpoint has
wins/losses/ties/missing of 2/0/5/8 for BM25, 4/0/5/6 for CRISP and 1/0/4/10
for no context. Both target flags and output allowance change together, on
inspected tasks with one response per payload. This is a post-hoc target
configuration diagnostic, not an isolated reasoning-effect or optimizer claim.
The historical 108- and 124-attempt pair reports remain preserved separately.

Current canonical verification passes 993 tests with two symlink skips and
kills all 105 mutants. Full packing selection audit is complete; every tested
grouping/fusion variant loses net source annotations. The length-penalty sweep
is generated and under independent audit. Current runtime remains local and
zero-generative-LLM. Verdict: PIVOT REQUIRED; wider validation remains open.

The subsequent three-request batch, after a 30-minute cooldown, returns three
HTTP 503s and pauses. The current independent checkpoint has 138 attempts,
94 answers, 43 HTTP 503s and one HTTP 429. All 94 successful prompt counts still
match. Ten first-stage requests are never attempted; these new transport errors
change no known answer outcome. No DONE request is retried. The new local
counting prototype changes no evidence in its measured cases and contributes
no new answer-quality result. Current canonical checks pass 1,001 tests with
two symlink skips and kill all 107 mutants.

The next bounded batch also returns three HTTP 503s and pauses, after a further
cooldown. The latest independent checkpoint is `cycle28-library-answer-141.json`:
141 attempts, 94 answers, 46 HTTP 503s and one HTTP 429. All 94 successful prompt
counts again match the local asset. Seven first-stage requests remain never
attempted. These transport errors add no answer outcome; completed payloads
were not retried. The current counter-barrier work changes no measured selected
evidence and supplies no new answer-quality claim. Its canonical suite passes
1,011 tests with two symlink skips and kills all 112 mutants. Overall verdict
remains PIVOT REQUIRED, with answer accuracy N/A where trials are incomplete.

After a verified 6,022-second cooldown, the last seven never-attempted first-stage
payloads produce five answers and two HTTP 503s. Independent report
`cycle28-library-answer-148.json` binds a quiescent 148-attempt ledger: 99 answers,
48 HTTP 503s and one HTTP 429. All 99 successful prompt counts match. The first
stage has zero never-attempted payloads but 49 transport-missing answers; it is
not a completed quality evaluation. No original DONE entry was retried.

At 2K BM25 remains four correct of eleven answered, native CRISP six of twelve.
The observed BM25-vs-CRISP pairs are one win, two losses and six ties, with six
pairs missing. No complete accuracy or winner is inferred. A future recovery
plan must preserve every original attempt, import successful evidence explicitly
as REPLAY, and label new attempts for known failed transports with their lineage.
Do not overwrite the original ledger or treat HTTP success as task success.
The lazy-count cycle supplies cost/memory evidence, not better answers. Current
canonical checks pass 1,057 tests, skip two symlink tests, and kill all 126 mutants.

The separate `cycle28-library-stage1-recovery-v1` run now preserves those original
148 attempts and reuses the 99 returned answers as explicit REPLAY records.
Eighteen new attempts, selected solely from terminal HTTP 429/503 failures,
recover twelve answers and return six HTTP 503s. It pauses after three consecutive
errors. There are 111 unique returned answers, 37 unanswered payloads (31 not yet
attempted in recovery, six failed again), and 166 cumulative API attempts. The
original ledger is unchanged. All 111 returned prompt counts match the asset.

`cycle28-recovery-answer-18.json` separates attempt and answer completeness and
retains parent lineage. BM25 has five correct of twelve answered, native CRISP
seven of thirteen; their pairs are one BM25 win, two losses, seven ties and five
missing. Every method's complete accuracy remains N/A. A post-hoc source-hashed
counterexample verifies two wrong answers despite complete function and literal
lookup-table exposure. It is not a sufficiency theorem or an independent sample.
Current canonical checks: 1,087 pass, two skips, 132/132 mutants killed. See
CYCLE28_TRANSPORT_RECOVERY.md; overall PIVOT REQUIRED and research goal active.

The final one-retry recovery pass is now attempted completely:49 new attempts,
35 returned answers and14 HTTP503s. It reuses99 original LIVE-origin answers, so
134 unique original payloads now have answers from197 total historical calls.
All134 prompt counts match. No original or recovered answer, nor failed new retry,
was resampled. The original148-attempt ledger remains intact. Fourteen payloads
remain unanswered; the later268 original budget-stage payloads were never attempted.

`cycle28-recovery-answer-49.json`: BM25 now has5/15 successes, native CRISP7/14
answered with one missing, field-weighted lexical7/12. CRISP's known count exceeds
BM25's completed count regardless of its missing outcome. Paired BM25-vs-CRISP:
1win,3losses,10ties,1missing. This establishes a loss on these inspected tasks,
not a universal ranking of the projects. Incomplete arms keep N/A accuracy.

Separate manual reference arms use24 new unique payloads/30 observations with
unchanged target settings:19 returned answers,5 HTTP503s, all19 prompt counts0
delta. Compact primary functions have4/13 successes with2 missing; adding direct
module bindings has5/11 with4 missing. Primary-only cannot reach CRISP's known7
even if both missing answers pass. It is not promoted. Six duplicate-context
pairs share answers. See CYCLE28_REFERENCE_EVIDENCE.md for source audits, strict
format-vs-behavior diagnostics, counterexamples and final reference comparisons.
Canonical checks:1106 pass,2 skips,138/138 mutants killed,349 bound sources.

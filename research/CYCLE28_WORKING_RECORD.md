# Cycle 28 — source completeness and an external challenger

Status: **IN PROGRESS**. This is a checkpoint, not a validation verdict.
The last completed cycle remains cycle 27. No production selector has been
promoted in this cycle, and no new LIVE target calls have been made.

## What we are testing

NeuralPack builds a searchable local artifact once, finds literal evidence for
a question, and passes that evidence to the application's answering model.
The compiler and default selector do not call a generative model.

The first hypothesis was that a documentation-only corpus omits useful API
docstrings and implementation details. All 153 declared manual files were
already present; this is an explicit corpus expansion, not a repair of a file
silently lost by the compiler. The challenger adds all 256 Python files under
the pinned SQLAlchemy library directory. Question text and expected answers
are never added to either corpus.

The user's subsequent CRISP comparison introduced a second priority: reproduce
an independent selector's advantage, and distinguish retrieval quality from
block granularity, token accounting and engineering strength.

## Completed LOCAL evidence

The SQLAlchemy archive is pinned to commit
`a303102a7bfbbb6da992a89b6610d71f080fb5eb`, SHA-256
`31fb3c7ced4274431d4f5c043e3fffc4bf79c36e5e6322756d2ec5531d544a49`.
No source modules were imported during corpus acquisition or compilation.
Static inspection found 12,917 definitions, 3,739 docstrings and 751 autodoc
directives. This is not equivalent to rendering Sphinx or resolving exports.

Ten new executable SQLAlchemy scenarios were run twice against version 2.0.43
with identical answers before retrieval. They are developer-authored scenarios,
not a sealed test set. They join 20 previously inspected scenarios.

Both corpora use the same physical-line windows with a 2,048-character target,
the same BM25/hybrid rankings and the same literal passage assembler. The
three estimated evidence caps are 1,024, 2,048 and 4,096. All 1,080 observations
were reconstructed and checked; the 360 distinct selections were identical
across three shuffled repetitions.

| Quantity | Manuals | Manuals + library Python |
|---|---:|---:|
| Source files | 153 | 409 |
| Blocks | 1,141 | 5,228 |
| Available context, chars/4 estimate per request | 527,807 | 2,534,628 |
| Deterministic artifact bytes | 15,183,872 | 65,347,584 |
| Semantic artifact bytes | 17,530,880 | 76,079,104 |

Adding 256 files took 9,834.6 ms for the deterministic artifact and 264,543.7 ms
for the semantic artifact. These are incremental additions to existing manual
packs, **not** fresh-build or single-file-update timings. The semantic update
encoded the 4,087 added blocks and retained the unchanged manual vectors.

At the 4,096 estimated cap, median query times for the ten new scenarios were:
manual BM25 63.49 ms, expanded BM25 151.50 ms, manual hybrid 240.61 ms, expanded
hybrid 837.19 ms. These are repeated-query measurements, not first-query costs.
API-source selection and docstring coverage are diagnostics; new tasks without
hand-annotated required spans receive N/A for that metric, never automatic wins.

A three-question profile found the expanded symbol channel cost about 259 ms,
versus about 41 ms for the dense channel. An aggregate-before-metadata-join SQL
challenger preserved all 60 corpus/question rankings across three repetitions.
Its isolated symbol median fell from 276.15 to 145.35 ms on the expanded pack
and 64.98 to 30.31 ms on manuals. **This is not a whole-query speedup or an
answer-quality improvement.** It has not been promoted.

The full checkpoint suite passed **826 tests, with 2 skipped** after the external
challenger work. All **76 mutation checks** caught their planted defects,
including the previous dependency, query and fallback mutants. The final suite
must run again after subsequent product repairs.

## Target-answer preparation

`cycle28-api-live-v2` freezes 270 observations and 249 unique payloads:
97 completed REPLAY records and 152 unattempted requests. Of the replays,
39 themselves came through an earlier replay; original LIVE ancestry and
intermediate response bytes were validated. Failed past calls remain failed.
Neither `v1` nor `v2` has made a new LIVE call. Version 2 shuffles the same
request identities with seed 28017 before any new call.

The frozen target is `nvidia/nemotron-3-super-120b-a12b`, temperature 1,
top-p 0.95, thinking disabled, maximum 2,048 output tokens. The caps in this
experiment are character estimates, **not exact NIM tokenizer budgets**.
Dollar savings and billing break-even remain N/A.

## CRISP snapshot and comparison boundary

The rival checkout was read only. It has no Git history and was changing during
inspection. Snapshot `cycle28-crisp-snapshot-v1` contains 249 files / 3,686,554
bytes, with manifest SHA-256
`9042a02247f83bb30602265e2a05f587fed2c7a8077342a7d5f5f4ad33a23daf`.
Copied files passed the limited recognized-credential pattern screen and a
second read verified that their bytes did not change during capture.

The documents describe a historical 300-task benchmark, while the frozen
current task file has **246 tasks and 207 distinct question strings**. This
comparison therefore cannot be called an exact reproduction of the historical
headline. Some exception questions have the same wording but different target
methods; their task rows are not independent question observations.

Both systems are freshly compiled from the same 155 Python source files in
rich, Jinja2 and Werkzeug. Non-Python assets are excluded from both sides.
The concatenated source contains 519,017 `cl100k_base` tokens. This is a
current-source comparison on inspected data, not new held-out validation.

Seven arms are frozen: NeuralPack default, method-level chunks, each of those
with exact-cost whole-block packing, CRISP, CRISP's BM25 packing baseline and
its BM25-plus-structural-channel baseline. Five caps span 512 to 8,192 tokens.
Exact-cost arms count the complete assembled context with pinned
`tiktoken==0.12.0`; query and caller wrappers are excluded identically.
`cl100k_base` is **not** asserted to be the NIM tokenizer.

The original substring needle metric is retained for comparison. An additional
diagnostic requires matching source path and overlapping source span. Neither
metric establishes answer correctness, semantic sufficiency or preservation of
every necessary condition. Body-line retention is reported alongside needles.

Two full comparison attempts terminated with exit code 1 and no Python
traceback. Sampled RSS in the second was about 117 MB; the cause is unknown.
These incomplete runs are retained and supply no headline result. The current
`cycle28-crisp-reproduction-v5` uses short resumable batches, content-addressed
context files and one atomically published record per selection. Records are
revalidated before reuse. Tokenizer caches are cleared per observation, so
latencies are diagnostic and cannot be substituted for warm production timing.

The complete rival run and source audit subsequently passed for all **8,610
selections / 86,871 source items**. At 2,048 exact context tokens, CRISP retained
all task needle lines on 234/246 tasks (95.1%), versus 153/246 (62.2%) for
NeuralPack method chunks with exact costing. CRISP's simpler BM25-plus-structure
baseline reached 231/246 (93.9%). This is source retention, not answer accuracy.
The advantage persists when repeated question strings are grouped. See
[the completed comparison](CYCLE28_CRISP_REPRODUCTION.md).

A data-only download of NVIDIA's pinned tokenizer and chat template reproduced
input-token usage on all 74 successful completed NIM responses. No new model
calls were needed. This provides a checked local tokenizer for the next budget
sweep; it does not turn earlier estimated caps into exact caps retroactively.

## Next decisions

### Exact-budget repair in progress

The working runtime accepts an explicit local `tokenizer.json` through
`LocalTokenizer`, `PackSelector(..., tokenizer=...)`, the convenience API, and
`npk query --tokenizer-json`. It disables stored truncation and padding, rejects
nonzero BPE dropout, counts the complete assembled context, and reconciles the
final bytes after optional evidence edits. Exact selected counts no longer share
an efficiency denominator with estimated corpus counts. Evidence sufficiency is
explicitly unverified. Query-time tokenization makes no network/model calls.

Initial tests caught a test expectation error: CLI fallback correctly exits 1,
while the new test expected 0. That expectation was corrected. Two subsequent
automatic approval reviews timed out before starting the corrected test command.
The ordinary project interpreter could not launch under workspace permissions.
The bundled CPython 3.12.14 interpreter did launch. Its first attempts exposed
test-environment problems (an inaccessible shared pytest temp directory, missing
child-process package paths, and a relocated tiktoken cache). Workspace-local
temporary files and explicit existing package/cache paths resolved those errors.

The resulting intermediate full check passed 820 tests and skipped 22. Twenty
skips are executable oracles pinned to CPython 3.12.10; the other two require
unavailable symlink permissions. This is not a substitute for the canonical
interpreter's final check. Later dropout and counting-challenger tests passed in
a separate targeted run. All failed/intermediate XML outputs are retained.

The `cycle28-local-budget-v1` attempt stopped before observations because the
existing compiled pack was unreadable under ordinary workspace permissions.
Version 2 freshly compiled the same frozen source under those permissions.
It compares estimates, exact counting, a bounded exact-count cache, and an
additive-cost challenger with final exact reconciliation. Both counting
challengers remain research code until the saved outputs and timings are audited.
This experiment uses the pinned NVIDIA tokenizer, so its numerical caps cannot
be interchanged with the earlier `cl100k_base` comparison.

Another identified seed-quality weakness is that the generic stopword filter
deletes `get`, `set`, `return`, and similar meaningful code terms. Explicitly
named identifiers and indexed path/name information are the next retrieval
hypotheses. No claim about their measured benefit has been made yet.

The local budget comparison subsequently completed: 2,484 selections and 864
profile observations, with an independent audit of 44,158 source items. Exact
caching preserved all 621 contexts. It reduced immediate repeated-query cost,
but barely helped cold queries. The additive approximation changed evidence and
remains experimental. The product implementation now has bounded exact-text
caching, serialized cache access, explicit disable/clear operations and source
update/concurrency regressions. All 84 mutants were killed in two batches with
identical product source hashes. The final current suite passed 831 tests with
22 skips on bundled Python 3.12.14. Two attempts to
start the canonical full suite timed out in automatic approval review; twenty
version-pinned oracle checks remain pending. See `CYCLE28_LOCAL_BUDGETS.md`.

1. Use the audited CRISP BM25-plus-structure approach as a strong baseline.
   Its advantage is real on the inspected code-search tasks; answer-task
   superiority still needs measurement.
2. Turn confirmed failures into product regressions. Exact local token budgeting
   and irrelevant-query handling need explicit contracts; do not calibrate an
   arbitrary threshold on this inspected dataset and call it general confidence.
3. Compare the strongest retrieval approach on executable answer tasks, including
   SQLAlchemy source expansion. Keep retrieval retention separate from answers.
4. Keep the current tested checkpoint and repeat the required checks after
   product changes. The rival evidence is archived in
   `experiments/results/cycle28-rival-checkpoint.tar.xz`; the SQLAlchemy working
   experiment still needs its final source/response archive and validation.

Mathematical status: all numerical findings here are **EMPIRICAL**. No new
theorem, approximation guarantee, probability or breakthrough is claimed.

### Seed research continuation

The fixed nine-arm seed comparison reached 2,500/5,589 saved selections and is
still incomplete. Its exact execution copy allows continuation without changing
the baseline after product repairs. See `CYCLE28_SEED_ABLATION.md` for the arms,
provenance limits and audit gates. No arm is promoted from partial results.

Eight new explicit-reference failures were reproduced and repaired in the public
selector. The product matches the fixed literal challenger in 920 rank checks
and 21 affected selections. All original rival questions have unchanged ranks,
so this repairs a benchmark blind spot rather than closes CRISP's lead. The
suite now passes 862 tests with the same 22 skips; all 85 mutants are killed.
Fifteen source-informed executable behavior questions also have stable answers
and traces across two fresh local runs. No new LIVE call has been made.

The nine-arm seed run subsequently completed all 5,589 selections and passed
both source/token and seed-ranking gates. At the 2K NIM cap, uniform metadata
raises annotated hits from 148 to 205 of 246; CRISP scoring with literal raise
lookup reaches 225 on the same blocks. The common traceback-construction loss
remains recorded; aggregate gains are not uniform safety or answer gains.
The earlier 2,500-record checkpoint above is historical. Full results and limits
are in `CYCLE28_SEED_ABLATION.md`. Native CRISP behavior contexts and actual local
encoder arrays are ready; hybrid/reranker selections and independent preflight
are the next steps before new NIM answer calls. SQLAlchemy source/answer work
remains open and is not replaced by this smaller behavior diagnostic.

### Current behavior-answer checkpoint

Both native and shared-block behavior selections have passed audit: 405
selections and 6,803 source items at exact NIM caps. The frozen 416-request LIVE
plan has 76 completed attempts: 59 responses, 16 HTTP 503 and one HTTP 429. It
is paused after service overload. Never retry these DONE entries or any
uncertain attempt. All 59 actual input counts match the pinned local tokenizer.
No method has complete answers; all accuracy values are N/A. No winner is
promoted. `CYCLE28_BEHAVIOR_ANSWERS.md` is the current detailed checkpoint.

The reporter now rejects a changing ledger and saves the exact captured bytes;
the failure is a permanent regression. Request pacing waits before STARTED and
records parsed Retry-After hints. These are benchmark-executor changes. The
default runtime still makes zero generative calls. The no-offset tokenizer
challenger saved about 15–17% in paired selection medians but is not promoted.
Exact repeated assembly counting and metadata's short-boilerplate ranking loss
are the next local hypotheses. The current code passes 901 tests with 22 skips
and kills all 88 mutants. Finish the behavior archive before editing the next
candidate; canonical-version and symlink checks remain outstanding.

### Exact-count execution experiments and canonical checks

The behavior archive is complete: `cycle28-library-checkpoint.zip`, SHA-256
`d7fd2de82964cee8547142da1a7e9fff2e84c1537f6863b1ff8e4109fa4a24a6`.
Subsequent piece-count and speculative-batch studies remain outside the product.
The piece cache loses; batching cuts wall time only when it spends more cores.
See `CYCLE28_COUNTING_COST.md` for the fixed plans and measured costs. Both
studies retain exact public evidence, query, risk and fallback behavior.

Canonical `.venv/Scripts/python.exe` now starts with approved execution and
reports CPython 3.12.10. The full suite passes 931 tests with only two symlink
skips; all 91 mutation checks are killed. The older note that 20 pinned oracle
checks remain pending is resolved. Their definitions and the separate frozen
3.12.14 behavior plan were not changed. Product code remains at the repaired
checkpoint while the new implementations are research challengers.

After roughly half an hour of cooldown, a bounded 24-request batch completed
at a minimum 15-second dispatch interval. The LIVE ledger now has 100 DONE
entries and no active request. The independent 100-attempt report is complete:
76 actual answers, 23 HTTP 503 failures and one HTTP 429 failure. All successful
prompt counts match provider usage. Every arm remains incomplete and has N/A
accuracy. The report captures and saves the quiescent ledger. Never retry an
existing DONE or uncertain request. SQLAlchemy work remains open.

The counting/100-answer-attempt checkpoint is independently verified and
archived: `cycle28-counting-checkpoint.zip`, SHA-256
`c935f266789f33fc89790af97de3f0d297a452e14fa3806eef0d4f1a0b5f7636`,
31,490,164 bytes and 4,634 files. The gate checked 1,890 profile rows, 45 exact
contexts and 611 literal source items. A failed relative-path archive attempt
and its regression assertion are preserved. There are no running benchmark,
test or LIVE sessions. Next: continue never-attempted frozen answer requests
with one worker, 15-second spacing and a three-error pause; the first stage
has 48 requests left before all 2K/no-context requests have been attempted.
Return research attention to seed ranking and evidence sufficiency; neither
piece caching nor speculative batching earns default runtime integration.

### Source identity: latest checkpoint

Original LIVE: 108 DONE, 81 answers, 26 HTTP 503, one HTTP 429; paused, no active
request, 40 first-stage requests remaining. Independent report 108 matches all
successful actual input counts. No complete or uncertain request was retried.

Source rendering: 270 audited cells, 3,742 source items, no cap violations;
headers can displace listed implementations and are not promoted. Failure
analysis v2 supersedes its null/malformed-response undercount in v1; it refers
to the frozen 100-attempt report. No exposure metric is called sufficiency.

Target profile cycle28-library-low-effort-v1: 45 planned requests, zero attempts,
plan SHA 5e8164a9243fb334c5f9d30f7c577c9d1fc29f7cd3ecb991c1f227bda09db536.
Preflight passed; two approval timeouts prevented launch. Guidance on retry is
pending. The locally discovered boolean-flag and UTF-8 plan-read failures are
fixed. Latest bundled checks: 924 pass, 22 skip, 96 mutants killed. The final
canonical full rerun remains pending; earlier canonical results are historical.

No test/audit/LIVE session remains active. Archive this cycle before editing
Python candidates. Next: unchanged-evidence target configuration, then header
versus raw answer controls at matched budgets; if unhelpful, investigate source
state and short-boilerplate crowding. Full details: CYCLE28_SOURCE_IDENTITY.md.
Original and SQLAlchemy answer evaluations remain open. Verdict: PIVOT REQUIRED.

The source-identity checkpoint is now archived and verified: 27,977,476 bytes,
2,606 files, SHA ef17eaf4700a93a348c6c02a13f12b9dcd494a99bcc2e239f530b0271697eff6.
All 316 Python hashes still match the 96-mutant baseline. ZIP CRC/member hashes
and 315,946 decoded/SQLite pattern checks pass. No recognized credential match.
No active process remains. User guidance on the next six-call API attempt is
pending after two automatic-review timeouts; do not count either as a request.
The canonical final runner is saved as cycle28-run-render-checks.py but has not
launched. Continue useful offline research while those actions remain pending.

### Packing challengers: frozen matrix underway

The new plan cycle28-packing-v1 has SHA
4efebc4ebd01aa3024462f4b218f5d68a7094ae22f4c61b51c8c238da08ebaf5.
It fixes 222 questions, 13 methods, three caps and 8,658 planned selections.
All algorithms remain research-only. The first 500 cells have an independent
source/token/ordering audit covering 11,461 selected item occurrences. The
continuation is active; track its actual tool handle, not state.json, which is
written only at a completed batch boundary. Do not restart on an observation
timeout or modify captured code while it runs.

Tests currently pass 935 with 22 explicit skips; all 99 mutants are killed.
Scope is 321 Python files (check the actual mutation manifest before relying on
that count). Canonical and API retry guidance remain pending. No new API attempt.
Full cycle details and counterexamples: CYCLE28_PACKING_CHALLENGERS.md.
Next: finish the matrix, audit outputs and assess paired losses/gains. No winner
may be promoted from the first 500 selections. Original and SQLAlchemy answer
work remain open. Verdict: PIVOT REQUIRED.

The immutable packing-500 archive is verified: 29,512,670 bytes, 3,430 files,
SHA 0942bd4fe8714dd7f43b70a485f91376c1608e75ce5f4ea4dd88037a0ef62654.
It binds exactly the 500 audited rows and leaves the larger run open. All 321
Python files still match the current 99-mutant baseline.

A separate read-only reproduction finds false `(raises, exc)` intent in the
traceback query, caused by splitting BaseException and exc_type. Parser.fail
is incorrectly boosted; removing that bonus alone only shifts the constructor
from rank 11 to 10. The fixture and runner are preserved in
cycle28-intent-counterexample-v1; desired future negative/catching cases remain
specifications, not a repaired-parser claim. Do not change the active frozen
matrix. Include a competent corrected-intent baseline in a subsequent study.

### Intent guards and resumed validation (2026-09-08)

The packing matrix is COMPLETE at 8,658 cells. Its old process handle is gone
and the terminal state is verified; it was not restarted. Full independent
audit is now running with query-grouped visits and a bounded 4,096-entry exact
count cache. The slower first audit was deliberately stopped after reporting
600 checks; its source and cancellation are retained. No check was removed.

New research-only action/conservative guards preserve raw queries and lexical
facets while filtering inferred raises bonuses. All 22 regressions pass,
including positive controls and an acknowledged mixed-clause false negative.
The new 2,664-observation plan has SHA
fc5bf682bf179f21f1cab2b6d8c47610d233661cb3234f15724cc8cc6287b58b.
Original ranks reproduce on all 222 questions. Disabled relations alter 46
rankings; each guard alters only the one traceback ranking. Selection and its
independent audit remain open. See CYCLE28_INTENT_GUARDS.md.

Canonical tests now passed 977 with two skips and killed 101/101 mutants across
325 Python files. After the audit-only cache/visit-order change, fresh v2 reports
are being produced; retain the original canonical reports as earlier evidence.

The permission environment changed. The already-authorized target batch was
launched successfully without another approval flow. The 24-request diagnostic
report contains 18 LIVE answers, six 503s, and 18/18 zero hosted prompt-count
deltas. Remaining requests are running. Previous approval timeouts were not API
attempts. No remote optimizer was added. Original and SQLAlchemy studies remain
open. Verdict: PIVOT REQUIRED.

Latest intent-cycle update: selection completed 2,664 observations using 789
distinct public-selector computations; independent audit is active. The v2
canonical checks passed 977/two skips and killed all 101 mutants; all 325 Python
source hashes match. The new target diagnostic paused after three consecutive
503s at 39 attempts: 25 answers, 14 errors, six still unattempted. All 25 hosted
prompt counts match. Identical-evidence target changes yield wins/losses/ties/
missing of 1/0/2/12 (none), 2/0/4/9 (BM25), 2/0/3/10 (CRISP). Only four BM25 vs
CRISP task pairs have two responses in the new profile; all tie. No winner.

### Completed intent audit; length-normalization challenger

Intent audit now passes all 2,664 records, 789 distinct admission orders and
56,381 source-item checks. Both guards preserve the original 182/225/242 hits
across the three caps; disabling all structural lookup gives 168/206/232.
The constructor still misses at 512/2,048 with the narrow guard. This is a
seed-lookup diagnostic, not evidence for graph expansion or answer accuracy.

The length sweep is frozen at 3,996 observations, five penalties plus original
control, plan SHA dc454d58eb98ae2a0ff9af1e3b31d65d95a617fb7808e919eb01ab25d87b04a1.
It reuses the frozen candidate code with per-call parameter scope; all original
and guarded .75 ranks reproduce. Other penalties change all 222 candidate
orders. The selection run is active. Do not edit its captured sources.
Full canonical verification: 990 passed, two skips, 103 killed mutants, all 328
current Python hashes match. A derivative of the pre-bonus term score is proved
under positive-input/fixed-weight assumptions, with symbolic and exact-rational
checks; it proves no relevance or quality result. See CYCLE28_LENGTH_NORMALIZATION.md.

After a 21-minute cooldown the last six new-profile requests were attempted once.
All 45 are terminal: 28 answers, 17 HTTP 503s, no unattempted requests. All hosted
prompt counts match. Correct/answered/planned: BM25 5/8/15, CRISP 7/10/15, none
3/10/15. Seven jointly answered retrieval pairs yield one CRISP win, six ties;
eight pairs are missing. Final accuracy remains N/A for each missing-answer arm.
Both retrieved-source target configurations gain two same-context answers vs
the old profile, but eight pairs remain missing for each. No winner is promoted.

The immutable intent checkpoint is verified: cycle28-intent-checkpoint.zip,
41,016,122 bytes, 4,249 files, SHA
b18384c01abff8062cebf91598175b05c5ea3f898b802f41bad9d926dd4b891d.
All hashes/CRCs pass; 315,511 decoded/SQLite pattern checks find no recognized
credential. It includes the completed intent audit, final 45-attempt target
diagnostic and frozen length-study inputs; larger ongoing work stays open.

The original non-thinking plan was resumed from its 108 terminal requests with
a bounded maximum of 40 new requests, one worker, 15-second spacing and a
three-error pause. The next 40 unique payloads were verified to contain only
2,048-token retrieval arms and no-context controls. No completed or uncertain
request is retried. Track the actual process handle before reporting progress.

The original plan's bounded continuation stopped at 124 terminal attempts:
90 LIVE answers, 33 HTTP 503s and one HTTP 429. The independently captured
`cycle28-library-answer-124.json` verifies all 90 hosted prompt counts exactly.
Twenty-four first-stage requests remained never attempted. After more than an
hour of cooldown, a new maximum-24 continuation started with the same one-worker,
15-second spacing and three-error pause. It is restricted to those original
2K/no-context payloads; no completed or uncertain request is retried.

The full packing audit subsequently completes all 8,658 orders and 172,235
source-item checks. The independent DuckDB summary matches all 39 raw-record
cohorts. Every non-control grouping/fusion arm has more annotation losses than
gains at every tested cap. Reject these default candidates and preserve their
negative evidence. Source-token curves are rendered and visually checked.
No answer-quality, graph-expansion or dollar-savings result follows.

The first summary query failed with DuckDB's default 12.5 GiB memory limit.
Its original source/SQL and terminal error are retained. Typed struct-list
ingestion, bounded 512 MB memory, two threads and fail-fast SQL complete the
aggregation. This analysis-utility repair is not a product speed claim.

The length matrix completes 3,996 observations and 3,333 distinct local
selections. Its independent audit is active. A focused 18-cell check recovers
the annotated traceback factory at 2K with b=0/.25/.5, but not .75/1. All modes
miss at 512 and retain it at 8K. Full-matrix losses are still required before
selecting a parameter.

Captured current rival source separately (11 files, 133,920 bytes, snapshot
ac218827026c7279695721127283c92d9214d93ebd18eaf6ab9257928ea7f38e).
MOCK loader interception reproduces missing explicit revision/offline arguments;
it proves no real cache mismatch or network request. Added NeuralPack regression
tests for those contracts; the core backend already enforces them. Canonical
verification: 993 passed, two symlink skips, all 105 mutants killed; all 328
source hashes match. See CYCLE28_CURRENT_RIVAL_CONTRACTS.md. Verdict remains
PIVOT REQUIRED; this is progress, not completion of the broader goal.

The next original LIVE batch is now terminal, paused at 135 attempts after three
consecutive 503s. It adds four answers and seven missing service outcomes.
Independent report: 94 total answers, 40 HTTP 503s, one HTTP 429, all 94 prompt
counts match. Thirteen first-stage payloads remain never attempted. Original
2K BM25 vs native guarded CRISP has wins/losses/ties/missing 1/2/6/6. Identical-
context target-profile pairs against this checkpoint are BM25 2/0/5/8, CRISP
4/0/5/6, no context 1/0/4/10. No answer winner or accuracy claim is supported.

The README evidence section is shortened from 239 to 39 lines so the current
product, decisive comparison, rejected ideas and remaining uncertainty are
readable. Historical cycle evidence stays in the research documents and evolution
record. This documentation edit changes no runtime or scientific result.

Verified full-packing checkpoint: cycle28-packing-complete-checkpoint.zip,
120,000,937 bytes, 16,966 files, SHA
a791ab07ab806a069cbafa325c1de56241f73389e0898026238ed72b5d0058f5.
All hashes/CRCs pass; 328,227 decoded/SQLite checks find no recognized credential
match. The generated PNG has hash verification only. Both LIVE ledgers were
quiescent and unchanged during archiving. The completed packing audit is
included; the ongoing full length audit is not claimed complete. Its latest
confirmed live process has independently checked 90 queries / 1,620 records.

Next decision: finish that fixed audit, run the prepared DuckDB summary for
length, examine every gain/loss against guarded b=.75, then choose whether the
scoring change deserves harder evaluation. No further target requests while
the service is in its latest error pause. Thirteen first-stage payloads remain
never attempted; all larger answer/economics studies remain open.

Next cycle implements an experimental prepared-interior tokenizer counter.
The old piece cache recomputed whole-text splits and lost; this prototype moves
interior tokenization into explicit reusable preparation and counts joins later.
Its boundary stability is a CONJECTURE for one pinned pipeline, not a theorem
or production fast path. Missing/unsupported parts use the upstream full count.

All 3,860 frozen ID/count attacks pass, including 1,000 added-token rejection
cases. Eight permanent tiny-BPE tests pass. The full canonical suite then passes
1,001 tests with two symlink skips and kills all 107 mutants; all 331 source
hashes match. The new mutants catch naive block addition and query-time
compilation. Core runtime and default selector remain unchanged.

All 405 public-selector profile observations preserve complete output apart
from latency. A subsequent upstream audit verifies every one of 2,700 actual
admission counts and reproduces those 405 final selections. Against the stronger
no-offset baseline, medians are 64.24 to 14.23 ms at 512, 177.28 to 26.26 ms at
2K, and 553.96 to 67.47 ms at 8K. Concurrent independent audit load limits these
timings. Preparation costs 2.335 seconds and accounts for 23.44 MB of Python
objects. The 16-query preparation crossover at 2K excludes startup, persistence,
updates and all API economics. No answer-quality improvement is claimed.

Separate count-only scale tests pass all 50 comparisons. At 100,303 tokens,
median count time is 157.08 vs 8.39 ms; at 250,478 it is 321.43 vs 16.79 ms.
Those are counting times, not query latency. Current data remains in memory,
not persisted in `.npk`. Keep the challenger for broader corpus/Unicode and
incremental-persistence work. See CYCLE28_BOUNDARY_COMPILATION.md.

After a 30-minute cooldown, the original target plan attempted three more
never-attempted payloads; all returned HTTP 503, triggering the configured pause.
It is terminal at 138 attempts: 94 answers, 43 HTTP 503s and one HTTP 429.
Independent report `cycle28-library-answer-138.json` again verifies all 94
successful prompt counts. Ten first-stage payloads remain never attempted.
No completed request was retried. The length audit is separately live and has
checked 210 queries / 3,780 of its 3,996 records. Overall PIVOT REQUIRED remains.

The length audit is now terminal and complete: 3,996 records, 3,333 distinct
admission replays and 73,914 source-item checks. Audited source hits at
512/2K/8K are b=0:172/215/238, .25:181/222/239, .5:180/225/241,
.75:182/225/242 and 1:180/228/242. Original unguarded .75 has the same totals
as the guarded control. At 2K, b=0/.25/.5 gains/losses are 4/14, 4/7 and 3/3.
b=1 gains three and loses none at 2K, but gains three and loses five at 512.
Reject weaker normalization as a general fix; retain b=1 only as a further
2K challenger. The motivating traceback recovery does not establish broad
retrieval gain. No default parameter or answer-quality winner is promoted.

Verified cycle checkpoint: cycle28-boundary-checkpoint.zip, 63,604,927 bytes,
8,175 files, SHA
b2298837cb64976e4ea013cf226f99763d0fc9fbcc5c589ede81744c9308f976.
All hashes/CRCs pass. 319,437 decoded/SQLite checks find no recognized credential
pattern. It captures completed length and boundary experiments, 1,001/two-skip/
107-mutant checks and the quiescent 138-attempt answer evidence. All processes
launched in this cycle are terminal; the broader goal remains active.

Next highest-value work: compact persistence and incremental invalidation of
prepared token interiors, plus broader Unicode/corpus attacks. Boundary stability
is still conjectural. A possible stronger guard is to compare the whole upstream
pre-tokenization against the proposed reusable partition before summing model
counts; that needs an actual cost/equivalence benchmark and may lose the speedup.
Do not call either persisted storage or this guard implemented. Keep the stronger
no-offset counter and frozen in-memory prototype as controls. No target request
is currently active; ten first-stage requests remain never attempted after the
latest three-503 pause. Overall verdict stays PIVOT REQUIRED.

Counter-barrier cycle complete: the whole-piece guard was implemented, attacked,
repaired and discarded as a runtime candidate because it slows 2K queries
176.09 to 228.96 ms. Numeric barriers improve only to 134.66 ms from 176.32.
Complete ASCII-word barriers retain most original speed, 182.49 to 26.62 ms at
2K, while allowing a narrower conditional argument. All three 405-observation
profiles and all three 2,700-count admission audits complete. Each replays the
same 3,860 old cases; the word candidate also passes 44,816 declared exhaustive
finite cases. Current full suite: 1,011 pass, two skips, 112/112 mutants killed,
336 current Python source hashes match. No default or `.npk` schema change.

The new candidate's 50 count-scale observations pass, but 250,478 tokens cost
50.23 ms versus 8.95 ms at 100,303. A block-wide ASCII restriction leaves
emoji/spinner tables largely uncached. At 250K, non-ASCII blocks contribute
38,306 of 47,452 standalone boundary tokens; these are workload components,
not total available tokens or a causal timing breakdown. The next high-value
counter hypothesis is safe word delimiters within mixed-Unicode blocks, then
compact persistence and incremental updates. Do not assume the current proof
applies after relaxing the ASCII restriction. No new general theorem or
answer-quality advantage is established. See CYCLE28_COUNTER_BARRIERS.md.

The original LIVE trial is quiescent at 141 attempts after a further three-503
pause. It still has 94 answers; the independent 141 report verifies all their
prompt counts. Seven first-stage requests remain unattempted. Do not retry DONE
payloads or repeatedly probe the known failing service without a recovery signal
or a substantially longer cooldown. This does not block offline research.

Verified counter checkpoint: cycle28-counter-checkpoint.zip, 18,048,862 bytes,
1,254 files, SHA 43e0ab613369e3ef9542ec1b7bfe83209657995659b87ac8f652a5d3b1e2efa9.
All member hashes/CRCs pass, and 122,839 decoded/SQLite pattern checks have no
recognized credential match. The new experiments, input data, source/tests and
quiescent target ledger are preserved. All processes launched in this cycle
are terminal. This goal turn is PROGRESS, not blocked or complete.

The persisted-count cycle is now terminal and complete. Delimited-word barriers
within mixed-Unicode blocks pass 3,860 replayed cases, 90,480 finite stress cases,
405 selections and all 2,700 actual admission counts. Count-only improvement at
250,478 tokens is 39.66 to 25.84 ms, but the 100,303-token case is slightly slower.
The conditional barrier argument remains pinned to the inspected pipeline.

Compact source-bound records retain 4,255,187 accounted bytes versus 23,274,103
for ID lists. The 1,216,512-byte SQLite sidecar reuses trusted counts, fully checks
unknown caches and recompiles only changed records. A reproduced post-commit
receipt race is fixed and permanently tested. Its initial harness TypeError is
preserved separately. V1's declared/actual cache-setting mismatch is explicitly
nonconforming; v2 reruns the declared setting and supplies the accepted evidence.

V2's 540 complete selections match, and another upstream audit replays all 2,700
admission counts. Warm 2K median is 176.22 to 23.82 ms; fresh-counter first-query
cost remains worse, 1,022.77 vs 843.41 ms. Nine real source updates compare exact
incremental cache state with full rebuilds. A one-file cache update costs 21.20 ms
vs 2,251.21 ms; the whole source-plus-cache phase still takes 820.19 ms. One/2/16
changed source files compile only 1/2/18 records; actual calls are checked by spies.

Canonical checks complete: 1,031 pass, two symlink skips, all 118 mutants killed,
341 source hashes unchanged. No new LIVE calls; the earlier 141-attempt checkpoint
is unchanged. Keep optional research persistence, not a default format change.
Next highest-value hypothesis: remove redundant startup serialization/decode,
then attack the counter on the larger SQLAlchemy corpus and consider optional
`.npk` integration. Current verdict PIVOT REQUIRED; this cycle is PROGRESS.
See CYCLE28_PERSISTED_COUNT_CACHE.md for costs, failures, assumptions and evidence.

Verified persistent checkpoint: cycle28-persist-checkpoint.zip, 73,826,824 bytes,
2,393 files, SHA 8a762d4057838d06ae214971818e133514f378bdbc40e7fbad35a5ff64ffef93.
All hashes/CRCs/SQLite checks pass, with 1,361,462 decoded/SQLite pattern checks
and zero recognized credential matches. All cycle processes are terminal. The
broader active goal continues with tokenizer startup and larger-corpus attacks.

The startup challenger and SQLAlchemy attack now complete. Direct backend metadata
access removes the extra vocabulary serialization/decode without changing the
counter algorithm, format or safety guards. A new class preserves frozen controls.
Fourteen new tests pass. Full suite: 1,045 pass, two symlink skips; all 120 mutants
are killed and all 343 Python source hashes match. Sessions 97571 (libraries),
94120 (SQLAlchemy) and 87528 (canonical tests/mutants) are terminal exit0.

Both profiles preserve all 135 fresh and 1,215 warm selection observations and
pass 8,100 individual admission counts against the full upstream encoder. Exact
available compiled-block tokens per request are 559,083 and 2,342,422. SQLAlchemy's
65,347,584-byte input artifact hash matches the older compilation report:
92e00bf27d8deac7ddefacc64bafffdceabc66138f09d20ab739a47a17db8501.
Full content/index verification passes; its original uniform-character chunking
is retained. Prior 558,878 library source tokens and SQLAlchemy character/4 counts
describe other representations and are not interchangeable with these counts.

Library startup drops 922.26 to 656.18 ms; SQLAlchemy drops 913.49 to 645.58 ms.
Fresh init+load+2K-query medians are 750.44 and 851.59 ms vs no-offset 834.02 and
889.83 ms. Three SQLAlchemy fresh pairs are slower. Warm 2K is 24.65 vs 181.40 ms
and 72.79 vs 241.18 ms. No material warm gain over the previous compact cache.
SQLAlchemy's 1,806,336-byte cache costs 9.20 seconds to build, excluding 1.06-second
writer init. The preparation-only 2K crossover estimate is 61 warm queries.

Keep the simpler metadata constructor, discard full vocabulary copying. Next:
selectively load already compiled candidate counts instead of hydrating all source
blocks, with source/engine/receipt checks and no hidden query compilation. Product
integration remains optional research. No new LIVE call, retrieval advantage or
answer-quality result; target checkpoint unchanged at 141 attempts. Overall
PIVOT REQUIRED; goal active and turn PROGRESS. See CYCLE28_LEAN_STARTUP.md.

Verified lean checkpoint: cycle28-lean-checkpoint.zip, 29,438,221 bytes, 490 files,
SHA 684fdd155ae708cf84ee0824c8b936fed279c405aa4272281ccb3cdac7077e74.
All hashes/CRCs/SQLite integrity checks pass. 630,683 decoded/SQLite checks find
no recognized credential match. All processes launched this cycle are terminal.
No default promotion, new target call, or goal completion is claimed.

Lazy-count cycle now complete. A private receipt-verified SQLite snapshot loads
count records only for encountered exact source text. Parent/owner checks use the
same query transaction; missing records use full encoding and never compile.
Unknown caches have no fast self-trust path. Twelve tests and six new mutants
attack these contracts. Canonical result: 1,057 pass, two symlink skips, all 126
mutants killed and all 345 source hashes match. Sessions 15999 (libraries), 16926
(SQLAlchemy), 65964 (tests/mutants) are terminal exit0.

All 135 fresh/1,620 warm selections and 8,100 admission counts pass. Fresh 2K
medians improve 761.59 to 702.23 ms and 858.67 to 743.40 ms versus eager loading.
Warm 2K regresses 24.20 to 25.60 ms and 72.90 to 74.84 ms. The SQLAlchemy source
count cache falls 12,794,267 to 1,192,198 accounted bytes, excluding its separate
1,806,336-byte SQLite snapshot and backend memory. Keep both strategies for their
measured tradeoffs. No retrieval/default/schema promotion is claimed.

After 6,022 seconds cooldown, session 86385 sends exactly seven remaining original
first-stage payloads: five answers and two503, then terminal exit0. No DONE payload
is retried. The target is quiescent at 148 attempts: 99 answers,48 HTTP503,one429.
Reporter session24338 terminates exit0 and verifies all99 prompt counts. Ledger
SHA 8a0500a8610486c02ca5cfd1413090f77102e4a6cfe9ee00868b90ad0412392a;
reporter SHA 73eb34f1670725255563a1f4a6a3999148e40ec28f30f19a3f616ad2498614a1.
`cycle28-library-answer-148.json` has zero never-attempted first-stage keys but
49 transport-missing answers. All original 2K/no-context per-method accuracies
remain N/A. The later 512/8K sweeps still have268 never-attempted payloads.

Next priority: a separate recovery plan for known failed transports, preserving
original attempt records and importing successful replies as explicit REPLAY.
Never overwrite/resubmit original DONE entries or retry uncertain in-flight work.
Use bounded, paced batches because the provider remains intermittent. Then
integrate useful compiled-count options deliberately and return to seed quality;
more counting micro-optimization is lower priority. Current goal turn PROGRESS,
overall PIVOT REQUIRED, goal active. See CYCLE28_LAZY_COUNTS.md.

Verified lazy checkpoint: cycle28-lazy-checkpoint.zip, 32,373,729 bytes,1,045 files,
SHA 9285dfd16f64355fd3874b384157a148525f811d3e8036610bf0c92d8a433a7b.
All hashes/CRCs/SQLite checks pass, with631,238 decoded/SQLite pattern checks and
zero recognized matches. All launched processes are terminal. The next goal turn
can prepare explicit recovery lineage for49 known failed first-stage payloads;
the original148-attempt ledger must remain intact. This turn is PROGRESS.

### Transport recovery checkpoint

The separate cycle28-library-stage1-recovery-v1 freezes49 eligible HTTP429/503
payloads and imports99 LIVE-origin REPLAY answers. It preserves the original
plan/ledger/records and rejects uncertain attempts or changed experiments.
Canonical session21562 is TERMINAL exit0:1087 pass,2 skips,132/132 mutants killed,
347 source hashes unchanged. First LIVE batch49484 is TERMINAL exit0:10 attempts,
8 answers,2 HTTP503. Second batch49682 is TERMINAL exit0:8 attempts,4 answers,
4 HTTP503, with an ACTIVE failure pause after3 consecutive503s. All reporters
and post-hoc diagnostic commands are terminal. Do not rerun stale --after10.

Independent report cycle28-recovery-answer-18.json:111 returned unique answers,
37 missing (31 eligible never retried,6 failed retry attempts),166 cumulative
API attempts. All111 prompt deltas0. Recovery ledger SHA
9aff6c4ca3614f08c22ed1014ed97cc3b273f1ce9a0fd63b4fdf8d537a972782;
original ledger remains8a0500a8610486c02ca5cfd1413090f77102e4a6cfe9ee00868b90ad0412392a.
BM25-vs-nativeCRISP:1win,2losses,7ties,5missing; accuracy N/A.

New post-hoc counterexample checks exact source/context hashes and full function
plus literal table presence for two wrong MIME answers; see
cycle28-recovery-counterexample.json. No new calls for this diagnostic.
Next independent work: freeze compact manually seeded reference evidence to
investigate distraction versus omission/target reasoning, without representing
it as a deployable retrieval win. Resume only the31 never-retried eligible keys
after inspecting the pause and cooldown; do not retry the6 failed new records
or any existing answer. No further recovery chain is authorized by the new
tooling. General user autonomy remains; do not ask again for routine work.
Current turn PROGRESS, verdict PIVOT REQUIRED, goal active. See
CYCLE28_TRANSPORT_RECOVERY.md for full policy, evidence and limitations.

Verified recovery archive: cycle28-recovery-checkpoint.zip,5,469,646 bytes,798 files,
SHA ef10081a495486f36881dd51c168a951e1207d44c95229ce41e07f93eb16792e.
All member hashes/CRC and347 source bindings pass,798 decoded pattern checks,
zero recognized matches. The parent and child ledgers are quiescent and unchanged.
All process handles are terminal; live failure pause remains active. Normal
git diff --check passes (core.autocrlf warnings are informational). Next turn
should proceed with independent LOCAL reference-evidence diagnostics while
respecting the target cooldown, not repeatedly send requests into the pause.

### Reference diagnostic and completed transport-recovery pass

Previous turn was PROGRESS. Revalidated347 source hashes and the18-attempt recovery
ledger before editing. New module benchmarks/reference_evidence.py is a manually
seeded research diagnostic, not automatic retrieval or a sufficient-context test.
It extracts full functions and optionally direct top-level declarations using
Python scope tables, pins MultiDict.getlist implementation line262, rejects
ambiguous references and enforces exact complete context budgets. Frozen source
audit reconstructs all30 observations/24 unique payloads,96-1383 tokens each,
and re-hashes155 public source files/558878 tokens per request. No runtime/core
schema change, no optimizer LLM calls, no source execution.

Reference planSHA8986f0dcc3ab257553bf7707ed23fe2221036745d02c7abd877d08a60a8f60f5.
Reference ledgerSHA7c5c8ad240965329090e20f83682969e69926c74e64abbe1e5a34065e8126f3f.
Reference sessions95709,56760,29778 TERMINAL exit0:24 attempts,19 answers,5 HTTP503s.
All19 prompt deltas0. Canonical41564 TERMINAL exit0:1106 pass,2 symlink skips,
138/138 mutants killed,349 source hashes unchanged. Additional local scripts
audit exact payloads, raw-answer comparisons, three dependency limitations and
strict exception-class formatting; those do not add to unit-test counts.

Reference primary4/13 answered (2missing), bindings5/11 (4missing). Primary-only
upper total6<CRISP known7 in the fixed trial. Do not promote. Direct bindings
vsprimary2wins/0losses/8ties/5missing, five ties sharing identical payloads.
One failure per reference arm has the expected TypeError prefix plus unrequested
message text; official strict grades unchanged. Other mismatches remain and are
not automatically attributed to retrieval/target reasoning. Defaults, conditional
declarations and transitive initializers are known reference-builder omissions.

Following a2431s cooldown and four observed successful reference transports,
resumed only31 never-retried original eligible keys. Sessions88035,54054,16028
TERMINAL exit0, plus final single-call command TERMINAL exit0:31 attempts ->23
answers +8 HTTP503. Recovery pass now49/49 attempted,35 returned answers,14 failed
retries. No second attempt of these49 is permitted by this plan. Original99 answers
reused, total134 returned original payloads from197 cumulative attempts.
Recovery ledgerSHA2294dd818912eea05a7acdb1e64162636293166e3974cbe2cf369030ee1d8006.
Original ledger8a0500a8610486c02ca5cfd1413090f77102e4a6cfe9ee00868b90ad0412392a unchanged.
All134 prompt deltas0. Current pause active=false, no running target process.
Do not rerun any stale --after wrapper or resume-after18. No pending recovery keys.

Current target report cycle28-recovery-answer-49.json: BM25 5/15, native CRISP7/14
with1 missing; field-weighted lexical7/12 with3 missing. CRISP wins this frozen
trial regardless of missing outcome; BM25-vsCRISP1win/3losses/10ties/1missing.
Final reference comparison cycle28-reference-comparison-24-baseline-49.json,
preserving earlier baseline18/38 comparisons and analysis-source snapshots.
This turn55 newAPI attempts,42 returned responses; across both families221 total
historical attempts. Later268 original512/8K/full payloads still never attempted.

Next: fully specified executable diagnostic cases to separate target reasoning/
format limits from missing dependencies; freeze any stronger target configuration
as a separate control, not NeuralPack gains. Field-weighted lexical is a stronger
baseline than plain BM25 on these tasks, but no advantage overCRISP is established.
Research/code archive and docs are being finalized; goal staysactive, turnPROGRESS,
overallPIVOT REQUIRED. Details in CYCLE28_REFERENCE_EVIDENCE.md.

Verified reference archive: cycle28-reference-checkpoint.zip,6,873,164 bytes,1076
files, SHA3899f1aeb37aa9cae08b28b8fad1cae1c10080ef15956517a8a60f9989603f26.
All member hashes/CRCs and349 source bindings pass,1076 decoded pattern checks,
zero recognized matches. All target, test, report, analysis and archive processes
are TERMINAL. No pending recovery payloads remain; do not rerun old wrappers.
Reference5 and original14 missing answers are terminal transport failures, not
uncertain in-flight requests. Additional sampling needs a separately declared
experiment; do not silently chain retries. Current goal remainsactive and this
turn is PROGRESS. Next work should address the diagnosed reasoning/dependency/
format ambiguity with fresh controlled evidence, not reintroduce primary-only
selection or keep polishing counting costs.

## Complete-program controls and typed audit repair

Current goal ACTIVE, turn PROGRESS, overall PIVOT REQUIRED. Frozen new run:
`experiments/runs/packs/cycle28-complete-programs-v1`. All16 unique requests are
terminal and answered; there are no pending or retry-eligible payloads in this
study. Direct6/8 vs thinking8/8; two wins, zero losses, six ties. Both target arms
receive the identical complete programs and question,46–313 source tokens per
task, mean126.25. Both actual mean input counts235.25; all16 prompt deltas0.
Output15.375 vs136.5 tokens and latency2.944 vs7.640 seconds. These are eight
inspected diagnostic programs, not a retrieval or large-context advantage.

Two direct-mode counterexamples: generator reversal returns2 instead ofTypeError;
the chained initializer case returns14 forC-B instead of7. Both have complete
source and valid JSON. CPython3.12.10 and3.12.14 executed the fixture oracles with
matching outputs. Thinking fixes both in one sample per case; no retries.

Re-audited the existing45-call library target profile against the final recovered
baseline, without repeating any call. Profile-vs-direct pairs are BM252/0/6/7
and CRISP4/0/5/6 (win/loss/tie/missing). This historical configuration changes
multiple settings and has missing transports. CRISP still wins the original
frozen15-task library comparison:7 known successes versus BM25's complete5.

Typed audit attacks are reproduced before repair: Python equality accepted
true-to1 answer substitution and integer-to-float token-count substitution.
Strict JSON identity fixes both. The archived original builder is provenance
only; current validation reconstructs all fixtures and preserves every frozen
request, source, oracle, ledger, response, and grade. See the typed analysis.

Canonical full tests:1,129 pass, two symlink skips. Initial combined runner31204
then times out in a setup-heavy mutation target; this is not counted as killed.
The isolated mutation runner9934 exits0 with141/141 assertion-killed mutants,
binding351 unchanged Python sources. Two new mutation selectors target their
specific assertion cases; all23 complete-program tests remain in the full suite.
The60-second mutation timeout and kill criterion are unchanged. All16 LIVE
calls and all test/analysis processes are terminal. Do not rerun stale wrappers.

Next: inspect shared answer/replay record comparisons for the same type-coercion
class (the shared validate_response reported/raw usage equality is not changed
in this cycle). Then use paired complete-source controls with explicit executable
inputs on new repository tasks, compare stronger seed systems at matched budgets,
and keep target configuration gains separate from NeuralPack gains. Main report:
research/CYCLE28_COMPLETE_PROGRAM_CONTROLS.md. No product champion is promoted.

Verified archive: cycle28-complete-checkpoint.zip,6,218,053 bytes,986 files,
SHA658f2f7c6b3d38d8a0a3d53b8e549d10041c5b4a7299a2b6fc3981710d7696d7.
Member hashes/CRCs and351 source bindings pass;986 decoded pattern checks find
zero recognized credentials. Archive process69030 exits0; all launched target,
test, mutation, audit and archive processes are terminal. Goal remains ACTIVE.

## Shared record identity continuation

Current goal ACTIVE; turn PROGRESS; PIVOT REQUIRED. Shared answer-record/replay/
recovery validators contained the same bool/int/float equality bug.11 new
regressions fail before repair; all60 focused cases pass after strict JSON
identity and integer recovery-policy version checks. Answer grading semantics
remain unchanged. The old source is captured under
`experiments/runs/packs/cycle28-shared-records-v1/code-before/`.

`cycle28-shared-record-audit.py` revalidates381 saved record files covering233
unique payloads and282 historical API attempts from the six named directories.
There are197 successful LIVE response records and99 replays; these are not
correct-answer counts or project-wide totals. No grade changes. New API calls0.
The result binds every raw record in cycle28-shared-record-reaudit.json.
Median197-record validation cost0.144 ms before vs1.156 ms after on12 alternating
warm pairs. Accept the extra1.012 ms per batch for correctness; no query claim.

Full tests session3565 TERMINAL exit0:1,140 pass,2 symlink skips,85.77 seconds.
Mutation session51635 TERMINAL exit0:144/144 assertion-killed, identical351
source hashes to the full-test snapshot. These use separate processes. Prefix:
cycle28-shared-record-canonical. No target-model process was launched this turn.

Shared response and recovery identity repair is complete for the audited paths.
Next: stronger seed comparisons on new repository questions with explicit
executable input harnesses, matched budgets, and complete-source controls under
the same target settings. Do not resample old answered or terminal failed
requests. The original frozen CRISP comparison still has CRISP7 known correct
against NeuralPack BM25's complete5. The complete-program control still has6/8
direct vs8/8 thinking at higher output usage/latency. No champion promoted.
Report: research/CYCLE28_SHARED_RECORD_IDENTITY.md.

## Cycle 29 handoff: source views rejected as automatic policy

The next research cycle diagnosed remaining seed-to-selection loss, then tested
full blocks, compact docstring views, and compact-on-rejection. Runs
cycle29-source-views-v1 and-v2 are separate. V1 intentionally stopped at292/5,994
because whole-context recounting was slow; all292 saved outputs match V2.
V2 completes5,994 selections on222 inspected questions,3seed lists and3caps.
No new target call; default runtime and format unchanged.

At2,048 source checks:body148→162,fields205→211,frozen CRISP225→233 forcompact.
But field primary non-doc implementation exposure falls10/15→9/15, losing
rich_overshoot; rejection-only also loses it. Body rejection-only loses
rich_zero_unknown. Documentation loss and runtime __doc__ are explicit risks.
Do not promote a higher needle score as answer quality. At8,192 compact CRISP
loses a source check. Allcounterexamples remain in10 new tests.

Available source rendering558,876tokens/request joins153block-owningfiles.
The previous558,878rendering additionally joins2empty__init__.pyfiles. Source
blocks and file bytes are unchanged; do not silently conflate the renderings.

Auditor38758 TERMINAL exit0:5,994full payload checks,859,367replayed admission
decisions using priorpreparedcounter,8,508independent upstream proposalcounts.
AuditSHA7b16666a4c9dd22db70cc8e937454a4b8b0ae106e7a65ee516db4dc260192c70.
PlanSHA8679a5081782cfe3934826694cc272c29c38136d3ca3f5bd28795d98b3caa754.
Profile49170 TERMINAL exit0:72paired identical-output observations on2questions;
whole→prepared medianpacking at512:125.64→9.31ms,2,048:374.75→10.80ms,
8,192:1,382.97→19.54ms. Countsetup2,412ms; excludes retrieval,viewcompile,
artifact I/O,target calls. Existingcounterreuse,notnovelretrievalorproductlatency.

Full46783 TERMINAL exit0:1,150pass,2skip,83.28sec. Mutations73251 TERMINAL
exit0:147/147assertion-killed,same355sourcehashes. Prefixcycle29-final-canonical.
Earlierfull64122passed1,149beforethefinalcounterexample; superseded,notdeleted.
Generation48901 TERMINAL exit0. Initial51795explicitlystopped exit1 after292.

VerdictPIVOT REQUIRED; goalactive,turnPROGRESS. KEEPexplicitviewsasresearch,
counterreuseandregressions. DISCARDautomaticdocstringremoval. NEXTnewrepository
behaviorquestionswithdefinition-complete retrieval,captureddefaults,conditional
bindings,collisions,complete-sourcecontrols,matchedcapsandfixedtargetsettings.
Do not repeat old answered/terminal failed LIVEpayloads. CRISPstillleadsfrozen
15taskcomparison; latestCRISPnotvalidated. See research/CYCLE29_SOURCE_VIEWS.md.

# Cycle 28: lexical fusion and admission-aware grouping

**Selection and independent audit complete; PIVOT REQUIRED.** The product default is unchanged and makes
zero generative optimization calls. This study has not established better answers
or a winning selection method. All reported measurements are **EMPIRICAL**.

## The observed failure

The existing traceback counterexample is `B-b8c5ec3852`. Body BM25 ranks
`Traceback.from_exception` first and retains its annotated source at a 2K NIM
cap. Field scoring ranks it at position 10, after repeated `__exit__` methods
and `Traceback.extract`; the CRISP-derived scorer ranks it at position 11.
Both contain the required block in their candidate pools but omit it from the
selected context. The earlier frozen baselines record this loss. This motivates
testing seed diversity and packing order rather than another dependency walk.

## Frozen challengers

`cycle28-packing-v1/plan.json` has SHA-256
`4efebc4ebd01aa3024462f4b218f5d68a7094ae22f4c61b51c8c238da08ebaf5`.
It fixes 222 question strings: the earlier 207 retrieval questions, carrying 246
source-needle annotations, plus the 15 behavior questions. These are inspected
development questions, not a sealed test set. The three caps are 512, 2,048 and
8,192 exact NIM context tokens. Available source is 558,878 tokens per request.

Thirteen methods create 8,658 planned selections:

| Method family | Seeds | Change |
|---|---|---|
| Rank controls | Body BM25; indexed fields; CRISP scorer plus literal raises | Original rank-first packing |
| Leaf grouping | Each of the three seeds | Prefer groups with fewer accepted items, grouping by unqualified method name |
| File grouping | Each of the three seeds | The same rule, grouping by source path |
| Body fusion, weight 1 | Fields and CRISP-derived seeds | Fuse each with body BM25 at equal rank weight |
| Body fusion, weight 2 | Fields and CRISP-derived seeds | Give the original stronger channel weight 2 and body BM25 weight 1 |

The fusion follows the product's rank-zero reciprocal-rank convention with
`k=60`, a variant of [reciprocal rank fusion](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf).
The paper uses ranks starting at one; its reported results are not claims about
these code questions. We test both declared weights rather than selecting a
weight from the results. Fusion can add candidates from the body channel, so
it is not an isolated same-pool packing comparison. Candidate counts are recorded.
The final evidence score describes rank in the fused list, not a probability.

Grouping preserves original rank as its tie-breaker and only changes visit
order. Rejected candidates do not count as accepted members of their group.
Anonymous blocks have distinct leaf groups. A checked AST adapter replaces the
public selector's loop iterator; source construction, exact admission, query
preservation, risk labels and final budget reconciliation remain public code.
No graph expansion, generated summaries, neural inference or remote call is used.

All ranking inputs and original control digests are frozen. Captured parent
seed calls show zero widened cells in this dataset. The experiment nevertheless
records the per-cap final parent pools rather than assuming widening never
happens. Raw controls must reproduce their earlier evidence IDs, byte hashes,
token counts and fallback flags. No source labels are added in this study.

## Counterexamples before promotion

**FALSIFIED:** admission-aware grouping always retains at least as many
designated source facts as rank-first packing. In a permanent fixture, two
required facts share a group and a third group contains noise. With an exact
character-count cap of 14, rank-first fits `fact A` and `fact B`, including their
two-character separator. Grouping fits `fact A` and `noise`, losing `fact B`.
This is a small counterexample about source selection, not model accuracy or
a claim that characters are the deployed NIM tokenizer.

**FALSIFIED:** adding an independent rank channel always improves a correct top
result. The fusion regression supplies a misleading body ranking that moves an
incorrect candidate above the original correct first candidate. Independence
alone is not a quality guarantee. The full fixed matrix must measure tradeoffs.

**PROVED UNDER ASSUMPTIONS:** if the input IDs are finite and unique, block
metadata stays fixed, and the consumer finishes the iterator, grouping visits
each known candidate exactly once. Initially each candidate belongs to one
queue. Each iteration removes one candidate and never inserts a candidate;
only a nonempty queue's next head is rescheduled. The remaining count decreases
by one until empty. This proves enumeration, not relevance or sufficient context.
In particular, an empty seed set remains empty; grouping cannot create evidence.

Tests also compare the heap implementation with a slower independent reference
over 80 randomized fixtures under both policies. They check that rejection
does not consume a group turn, anonymous blocks remain distinct, query bytes
survive, budgets hold, and request state does not leak between calls. An initial
fixture omitted `python_members=True`; that setup failure and its XML report
are retained. The production compiler was not changed to fix a test fixture.

## Current evidence and open work

The first 500 selections form a completed, quiescent checkpoint. An independent
auditor reconstructs original source spans, recounts whole contexts, recomputes
fusion, and replays every one of these 500 admission sequences with a slower
implementation that imports neither challenger nor public selector. All pass,
covering 11,461 selected source-item occurrences. This is a partial audit of an
incomplete matrix; its cohorts must not be ranked as completed experiments.

The remaining fixed selections are running. Parameters will not change in
response to partial retention totals. Selection timings exclude seed lookup,
use a shared 16 MiB count cache and are diagnostic. The continuation briefly
overlapped local tests. They are not clean cold/warm query latency or economics.
The exploratory first-500 medians were 101.82 ms at 512, 360.29 ms at 2K and
1,321.97 ms at 8K, across mixed policies and questions. These incomplete mixed
medians are not comparative speed results.

The current bundled Python suite passes **935 tests with 22 explicit skips**;
all **99 mutants are killed**. Twenty oracle skips require canonical Python,
and two require symlink permission. The canonical rerun and the prepared
six-call target batch remain pending after the previous approval timeouts.
No new API attempt has been made in this cycle.

Keep the independent controls, source/cost checks and counterexamples. Discard
universal quality claims for grouping or fusion. Neither is promoted. Next:
complete the frozen matrix, independently audit all outputs, compare paired
gains/losses and cost-quality curves, then test actual answers when execution
can proceed. Improved source retention alone will not establish differentiation.

The larger original answer evaluation, unchanged-context target diagnostic and
SQLAlchemy work remain open. Repeated exact token counting remains a potential
performance bottleneck; a future compiler experiment may cache stable token
segments and recompute joins. That is an unimplemented hypothesis requiring
boundary/special-token counterexamples and a defensible fallback, not a speed claim.

## Additional diagnostic while the matrix runs

A separate read-only reproduction finds a false structural-intent signal in
CRISP's frozen query planner. The traceback query's `BaseException` contributes
the split noun `exception`; the planner treats it as a raise verb and combines
it with `exc`, split from `exc_type`. This creates the relation `(raises, exc)`
and promotes the unrelated `Parser.fail` to first place. The identifier regex
also extracts `aseException` from inside `BaseException`.

Clearing just the inferred relation in memory moves the constructor from rank
11 to rank 10, behind repeated context-manager methods. This does not solve the
whole failure or establish answer improvement. The running 8,658-cell plan and
rival source remain unchanged. The reproducible fixture and runner are in
`experiments/runs/packs/cycle28-intent-counterexample-v1`. Its desired future
cases include distinguishing raised, caught and negated exception questions;
those are pending specifications, not claimed passing tests for a repaired parser.
A subsequent strong-baseline comparison should include a validated correction
instead of relying on this known rival weakness.

The fixed 500-row checkpoint is verified and archived as
`experiments/results/cycle28-packing-500-checkpoint.zip`: 29,512,670 bytes,
3,430 files, SHA-256
`0942bd4fe8714dd7f43b70a485f91376c1608e75ce5f4ea4dd88037a0ef62654`.
Every member hash and ZIP CRC passes; 125,015 decoded/SQLite pattern checks find
no recognized credential match. This does not prove absence of every secret
format. The archive explicitly contains a partial audit and leaves the goal open.

## Completed generation; full audit in progress

The fixed matrix completed all 8,658 cells without changing its plan or captured
selector code. Full independent source/count/admission replay is running. The
auditor now visits related queries together and retains up to 4,096 exact-string
counts; its checks are unchanged. The intentionally stopped earlier full-audit
attempt and its source are recorded in the run directory. The historical
500-row audited archive remains valid.

An exploratory DuckDB aggregation of all raw records is saved in
`cycle28-packing-raw-summary.json`, explicitly marked pending full audit.
At 2,048 tokens, every proposed grouping/fusion variant has fewer annotated
hits than the rank control using its same starting seed system. For example,
CRISP-seed rank has 225/246, leaf grouping 206/246, file grouping 172/246, and
the two body-fusion weights 189/246 and 201/246. The two fusion variants each
gain three annotations but lose 39 and 27 respectively. These preliminary
totals do not justify promotion and are not answer-quality results. The SQL
and all raw records are preserved for independent reconciliation.

See CYCLE28_INTENT_GUARDS.md for the parallel intent counterexample, completed
2,664-observation selection study, latest canonical 977/two-skip/101-mutant
verification and resumed LIVE target diagnostic. No product winner is declared.

## Completed independent audit and decision

The full auditor finished all **8,658 selections and admission-order replays**,
checking **172,235 selected source-item occurrences**. Every whole-context count
fits its declared cap, and all source identities and original controls pass.
The report is `cycle28-packing-audit-full.json`. A separate DuckDB aggregation
of its audited rows reproduces all 39 earlier raw-record groups exactly,
including paired gains and losses. No raw-only conclusion is substituted for
the full audit.

Every non-control variant loses more source annotations than it gains against
its own seed/rank control at every tested cap. At 2,048 tokens:

| Seed system | Rank control | Member grouping | File grouping | Fusion 1:1 | Fusion 2:1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Body lexical | 148 | 140 | 118 | N/A | N/A |
| Path/name/body | 205 | 187 | 146 | 182 | 191 |
| Frozen CRISP structural | 225 | 206 | 172 | 189 | 201 |

Values are source hits out of 246 annotations, not answer accuracy. Fusion
weights are starting-seed:body. With CRISP seeds, member grouping gains three
annotations but loses 22; file grouping gains three and loses 56. Fusion 1:1
gains three and loses 39; fusion 2:1 gains three and loses 27. At this cap, none
improves exposure of the listed primary definitions on the 15 behavior tasks.
Definition exposure is not a sufficiency certificate.

![Audited source-retention curves](../experiments/results/cycle28-packing-source-curves.png)

The reduced report `cycle28-packing-audited-summary.json` also records per-arm
mean selected tokens, every paired task loss, and the observed frontier in
mean-evidence-token/source-hit space. It excludes latency, complete prompt
overhead, dollar cost and actual answer quality. Small differences in mean
tokens do not justify a product promotion.

Discard these grouping/fusion policies as default candidates. Keep the
counterexamples, independent auditor and frozen research implementations to
make this negative result reproducible. No graph-expansion claim follows from
the structural seed lookup. The next hypothesis is the already frozen five-
setting length-penalty comparison, which changes seed ranking before packing.

The first summary utility exhausted DuckDB's default memory limit when expanding
one large JSON array through a correlated `json_each`. Its failed source, SQL
and terminal error are preserved. Typed struct-list ingestion with `unnest`,
an explicit 512 MB limit and two threads completes the same aggregation. This
is an analysis-utility repair, not a NeuralPack query-speed improvement.

The full checkpoint is verified as `cycle28-packing-complete-checkpoint.zip`:
120,000,937 bytes, 16,966 files, SHA-256
`a791ab07ab806a069cbafa325c1de56241f73389e0898026238ed72b5d0058f5`.
Every ZIP member hash and CRC passes. It includes both quiescent target ledgers,
the latest 993/two-skip/105-mutant verification and the separate rival loader
counterexample. It contains length-study inputs and the focused traceback
case; the complete length audit remains outside its completion scope.
328,227 decoded/SQLite pattern checks find no recognized credential match;
the generated PNG is hash-verified rather than text-scanned. This is a bounded
pattern screen, not proof that all possible secret formats are absent.

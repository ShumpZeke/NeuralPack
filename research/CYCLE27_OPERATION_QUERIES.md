# Cycle 27: finding operations is not enough to improve answers

**Decision: PIVOT REQUIRED.** Keep the current compiled runtime. Query views
based on Python operations improve some source-passage checks, but do not earn
promotion on actual answers. Ordinary hybrid retrieval is the stronger competitor
on the new scenarios. The new selectors remain research code; no product format,
default flag, provider requirement or generative optimizer call was added.

NeuralPack prepares a searchable local copy of source files, then selects passages
for the application's chosen answering model. This cycle tests whether setup code
and unrelated text overwhelm the part of a question that matters. It also attacks
the resulting parser, retrieval fallback and answer-experiment scheduler.

## Frozen comparison

**EMPIRICAL.** The corpus remains 153 public SQLAlchemy 2.0.43 manual files from
commit `a303102a7bfbbb6da992a89b6610d71f080fb5eb`, with MIT license and complete
source hashes. Each request has 527,598 corpus tokens and 527,807 available tokens
using the stated characters/4 estimate. The same 1,141 compiled blocks and
provenance-budgeted passage assembler serve every method. The assembler is the
research implementation in `benchmarks/unit_passages.py`; these are not timings
of the shipped selector. Existing cycle 24 artifacts are reused, with no new
index or compilation measurement in this cycle.

Ten previously inspected executable scenarios are joined by ten new developer
scenarios involving expiration, explicit flushes, merge identity, nested rollback,
dynamic method lookup and related session behavior. The new scenarios execute
twice with identical labels under Python 3.12.10, SQLAlchemy 2.0.43, greenlet
3.5.5 and typing-extensions 4.16.0 with SQLite. Their code, helpers and labels
are not included in the retrieval corpus. They are not independently sealed
tasks. Every scenario also gets an explicitly irrelevant inventory prefix for
a LOCAL robustness check; those variants are not independent answer tasks.

Eight methods sweep 1,024, 2,048 and 4,096 estimated context-token caps in three
shuffled repetitions: current BM25, clause RRF, balanced clauses, question-only
BM25, operations-only BM25, combined full/question/operation RRF, ordinary local
hybrid, and question-focused hybrid. Clause controls reuse their existing query
splitting over this shared lexical index, not the earlier fielded index. The
experiment has 2,880 observations and 960 unique task/method/cap cells. Every
selection is reconstructed from literal source spans; all three repetitions of
each cell produce identical context bytes. Query and system text are preserved,
and provenance counts toward the cap. Empty results require explicit fallback.

Operation views extract literal call names, keyword arguments and context-manager
attributes using Python's AST without executing query code. Python AST columns
are UTF-8 byte offsets, as documented in the
[Python 3.12 AST reference](https://docs.python.org/3.12/library/ast.html)
(checked September 7, 2026). The parser has size and node limits, and reports
unsupported dynamic behavior. It does not resolve bindings or prove that its
views preserve all query semantics. Negative constraints can occur outside a
question sentence or operation; the full original question still reaches the
answering model. Retrieval uses the existing
[SQLite FTS5 index](https://www.sqlite.org/fts5.html), checked the same day.

The optional local encoder is `sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with 256-token input limit,
2,000-character document prefixes, masked-mean pooling and L2 normalization.
It runs with transformers 4.57.6 and torch 2.8.0+cu126 on CPU with two threads.
Weights and tokenizer were cached; no model download or network call occurred
during LOCAL selection. Hybrid retains the existing similarity gate and records
whether embeddings were actually used. All optimizer calls are non-generative.

## Source gains fail to establish answer gains

**EMPIRICAL.** The following counts require all annotated source passages. Each
fraction has ten unique scenarios. Annotations are partial diagnostics, not
proof of sufficient evidence or answer accuracy.

| Method | Known scenarios, 1K / 2K / 4K | New scenarios, 1K / 2K / 4K | New-scenario median ms, 1K / 4K |
| --- | --- | --- | --- |
| BM25 | 1 / 1 / 3 | 2 / 2 / 2 | 42.82 / 64.18 |
| Clause RRF | 0 / 0 / 0 | 0 / 0 / 0 | 106.76 / 136.75 |
| Balanced clauses | 1 / 1 / 1 | 2 / 2 / 2 | 122.06 / 139.42 |
| Question only | 3 / 4 / 5 | 1 / 1 / 2 | 23.87 / 45.66 |
| Operations only | 3 / 4 / 6 | 2 / 3 / 3 | 27.94 / 46.83 |
| Combined views | 3 / 4 / 8 | 1 / 4 / 4 | 51.32 / 92.41 |
| Ordinary hybrid | 0 / 1 / 4 | 3 / 3 / 4 | 191.28 / 215.79 |
| Focused hybrid | 2 / 5 / 6 | 0 / 1 / 2 | 72.45 / 91.37 |

These medians include ranking and source assembly: median of three trials per
task, then median over the cohort. Host load was uncontrolled. Agent CPU tests,
archive compression and LIVE I/O did not overlap the measured LOCAL run. The
latencies cannot be attributed solely to the encoder or compared directly with
earlier timings of a different selector. No 10× product improvement is claimed.

![All LOCAL source curves](../experiments/results/cycle27-source-curves.png)

**EMPIRICAL.** The full-query encoder truncates 17/20 original queries and all
20 padded variants. In every padded variant it receives none of the actual
scenario. A separate cached-tokenizer reproduction compares complete input
features, not just text lengths: the 20 different padded questions produce
identical features. Across all 40 layouts there are 21 feature groups. The
[formal limitation](math/TRUNCATED_QUERY_COLLISIONS.md) is about this retrieval
representation, not about hybrid's separate lexical channel or the target
model, which sees the original question.

## Actual target answers

**EMPIRICAL.** Before target calls, five methods and two caps were frozen:
BM25, question-only, combined views, ordinary hybrid and focused hybrid, at
1K/4K, on the 20 original scenarios. Full-source and no-source controls are
reported separately, outside matched-cap comparisons. The frozen plan hash is
`801f6945f1f6526ccbc6ce66e498ee74112d4019519d5df9940d4cfee6b66cd5`.
There are 240 observations sharing 217 unique payloads. The target is
`nvidia/nemotron-3-super-120b-a12b`, temperature 1, top-p 0.95, thinking disabled,
2,048 maximum output tokens and 180-second timeout, matching the prior controls.

The final ledger is terminal for all 217 payloads. It contains 168 new LIVE
attempts: 125 answers and 43 transport failures (24 HTTP 503, 15 HTTP 429 and
four HTTP 404). Another 49 byte-verified prior records are explicitly REPLAY:
37 answers and 12 old HTTP 503 failures. Reused responses are not independent
replications or new consumption. Failed and uncertain requests were never
retried; explicit resumptions dispatched only previously unattempted payloads.
Pause snapshots and the exact before/after execution code are retained.

| Comparison with BM25 | Cohort / cap | Strict JSON wins / losses / ties / missing | Supplementary literal-value wins / losses / ties / unresolved |
| --- | --- | --- | --- |
| Combined views | Known / 4K | 0 / 1 / 5 / 4 | 0 / 0 / 5 / 5 |
| Combined views | New / 4K | 2 / 1 / 1 / 6 | 0 / 1 / 1 / 8 |
| Ordinary hybrid | New / 1K | 3 / 0 / 5 / 2 | 2 / 0 / 5 / 3 |
| Question only | New / 1K | 2 / 1 / 5 / 2 | 1 / 1 / 5 / 3 |

The supplementary diagnostic examines literal values despite formatting errors;
it does not rewrite the strict JSON grades. Comparisons use only completed
pairs. Missing transport results are not incorrect answers. Raw correct/completed
counts have differing denominators and must not be interpreted as paired wins.
All arms and pairs appear in the
[answer report](../experiments/results/cycle27-operation-answers.md).

![Paired target results](../experiments/results/cycle27-answer-pairs.png)

The combined method's known-passage improvement from 3/10 to 8/10 at 4K therefore
does not establish an answer improvement. Ordinary hybrid is a necessary strong
control: it has more favorable completed pairs on new tasks despite smaller
annotation gains. Only two scenarios in each cohort have completed responses
across all ten selected arms. Their descriptive cost-quality frontiers are too
small and selectively incomplete for a promotion decision. One stochastic
response per payload also leaves target variability unmeasured.

**EMPIRICAL.** Successful new LIVE responses report 4,416,318 input and 3,206
output tokens. REPLAY separately reports 3,648,148 input and 1,043 output tokens
from prior calls. Full-source controls average about 512K actual input tokens per
completed request, while selected arms range roughly 1.1K–4.2K including prompts.
This is token accounting, not an accuracy-preserving saving. Billing, failed-call
charges, local compute dollars, net savings and break-even requests remain N/A.
No remote preprocessing arm was executed or invented. The target is called once
per new payload; the optimizer makes zero generative calls.

## Counterexamples and repairs

**EMPIRICAL.** Focused lexical views initially returned no seeds without retrying
the full query. Two regression cases failed before repair. Both question-only
and operations-only paths now broaden to the original query after an empty
focused search. This is a retrieval attempt, not proof that its evidence is
sufficient. The repair occurred before the frozen LOCAL measurements.

**EMPIRICAL.** The parser then failed three new cases because `str.splitlines`
treated U+2028 inside a quoted string as a physical Python newline. Physical
CR/LF splitting and conversion from UTF-8 byte columns restore exact query
spans for LF, CRLF and CR inputs. The final parser yields byte-identical views
and signals for all 40 frozen benchmark queries. The measured run predates
this Unicode fix; both executed and final source versions are preserved.

**EMPIRICAL.** The target scheduler previously paused only after four consecutive
transport failures. A rate-limit response followed by a success could allow
another batch. Two LOCAL synthetic-response cases reproduced this with one and
two workers. It now completes the already dispatched bounded batch and pauses
after any HTTP 429, independently of the consecutive-error count. Resumption is
explicit and covers only unattempted requests. The first real dispatch used
the old scheduler; later dispatches used the repaired version. This distinction
is present in the execution-source archive and ledger.

The final full suite has **803 passes and two skips**. All **73 mutation checks
kill their planted defects**, including the four new mutations for focused-search
broadening, UTF-8 offsets, Unicode physical lines and isolated rate-limit pause.
Before-fix failures and intermediate passing suites are retained as raw evidence.
No runtime selector or `.npk` schema changed in this cycle.

## Keep, discard, next

Keep the executable scenarios, source reconstruction, tokenizer-input diagnostic,
strong baseline comparisons, parser counterexamples and experiment-runner fixes.
Discard default promotion of operation views, claims that passage retention
proves answer quality, and any assumption that embedding a long query necessarily
embeds its question. Risk remains uncalibrated.

**CONJECTURE.** The next useful corpus may need referenced API source/docstrings.
The pinned manual's `orm/session_api.rst` contains `autoclass` directives;
some rendered API bodies live in Python source excluded by the manual-only
corpus definition. All 153 declared manual files are present, so this is not a
new compiler omission. Compare pinned manuals alone with manuals plus pinned
API source at matched budgets, including BM25 and ordinary hybrid. First prove
what information is added and whether it helps harder, newly executed scenarios;
do not execute documentation imports or use answers as retrieval labels. Adding
more corpus can also introduce distractors, so a negative result remains useful.

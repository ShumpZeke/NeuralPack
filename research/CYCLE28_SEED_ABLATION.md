# Cycle 28: seed retrieval audited; answer validation remains open

**Open checkpoint; verdict remains PIVOT REQUIRED.** CRISP's previously
audited retrieval lead is the starting point. None of the new experiments below
has established a differentiated answer-quality advantage.

The immediate question is whether NeuralPack loses useful search intent before
ranking starts. Its ordinary query filter removes `get`, `set`, `return`, `value`
and short terms. Eight new public-API counterexamples reproduce empty results
even when the user explicitly encloses the term in backticks and the corpus
contains the answer. The original product correctly requests fallback, but
should have retrieved this evidence. The deliberately failing pre-repair run is
`experiments/results/cycle28-literal-before.xml` (8 failed, 1 passed).

## Fixed comparisons

`cycle28-seed-metadata-v1` declares 5,589 selections: 207 distinct questions,
three exact NVIDIA context caps (512, 2,048 and 8,192), and nine arms. The source
contains Rich 14.2.0, Jinja2 3.1.6 and Werkzeug 3.1.3, frozen with the earlier
rival snapshot. Every request has the same 558,878 source tokens available;
this is a per-request quantity, not a sum across questions. Every arm uses the
same 3,513 method-oriented NeuralPack blocks and the same product packing code.

| Arm | Change under test |
|---|---|
| body60 | Existing lexical retrieval, 60 candidates |
| body160 | Existing lexical retrieval, 160 candidates |
| literal | Restore explicitly backticked atomic terms, 160 candidates |
| retained | Also retain the declared set of meaningful code words |
| subwords | Index whole spellings plus identifier components |
| fields | Also index associated symbol name and source path |
| names4 | Give the name field weight 4; body/path remain weight 1 |
| crisp_shared | Frozen CRISP scoring over these same blocks |
| crisp_shared_raises | Also enable its selective literal-raise relation channel |

The additional index took 1,578 ms to build in this local observation and uses
12,730,368 bytes. It contains several competing indexes simultaneously, so this
is **not** the footprint of a proposed minimal product feature. It requires a
rebuild after parent changes and refuses a stale parent. No incremental benefit
is claimed. Field weighting and underscore tokenization use existing
[SQLite FTS5 facilities](https://www.sqlite.org/fts5.html), not a custom binary format.

CRISP's scoring control preserves its original `cl100k_base` document-length
normalization. All output caps nevertheless use the same pinned NVIDIA
tokenizer, counted over complete assembled contexts. Query/caller wrappers are
excluded equally. Its arbitrary support floor and calibration claims are not
adopted. A syntactic raise site does not prove that an exception executes.

The task file has 246 annotations but only 207 distinct question strings.
Repeated, sometimes ambiguous exception questions will be grouped in paired
comparisons. These questions are inspected development data. Source-needle
retention and candidate-pool coverage are diagnostics, not answer accuracy.

Every selection is saved before the next begins. Batch continuation verifies
source, pack, tokenizer and index hashes. An execution copy materializes the
exact captured product and experiment code so later product repairs cannot
change the original comparison. Two previously uncaptured helper files are
explicitly tied to their unchanged `8ec1214` versions; this omission is recorded
in `execution-copy.json`, not silently backdated.

The run completed all **5,589 selections** from its captured implementation.
The independent output auditor reconstructed 114,890 selected source items,
checked all 3,513 blocks, recounted every assembled context with the pinned
tokenizer, and verified the complete matrix, annotations and fallback flags.
All caps passed. The separate rank gate reproduced 1,863 distinct seed calls
and every recorded reciprocal-rank score across the 5,589 records.
Its first attempt failed on an import guard before checking ranks: the public
`npk.pack.select` function shadows the same-named module attribute. The guard
now resolves the module with `importlib`; the failure and executed script are
preserved, and a permanent regression test passes.

The following numbers are annotated source-needle hits out of 246 tasks,
**not answer accuracy**:

| Arm | 512 tokens | 2,048 tokens | 8,192 tokens |
|---|---:|---:|---:|
| body60 | 120 | 148 | 183 |
| body160 | 120 | 148 | 183 |
| literal | 120 | 148 | 183 |
| retained | 121 | 149 | 183 |
| subwords | 132 | 171 | 201 |
| fields | 162 | 205 | 229 |
| names4 | 162 | 205 | 229 |
| crisp_shared | 168 | 206 | 232 |
| crisp_shared_raises | 182 | 225 | 242 |

At 2,048 tokens, fields wins 58 annotations and loses one versus body160;
CRISP's scorer plus raise lookup wins 78 and loses one. Their common loss is
`B-b8c5ec3852`, Rich `Traceback.from_exception`, on the question beginning
“Which code is responsible for this behaviour: Create a traceback info…”.
This remains a counterexample to uniform improvement. The names4 and fields
aggregate totals tie while individual results differ; name weighting is not
established as universally beneficial.

Increasing the candidate pool from 60 to 160 raises pool coverage from 198 to
215 annotations but yields no selected-hit improvement at these caps.
Metadata raises pool coverage to 241; selective literal raise lookup reaches
243. This supports improving seed ranking and metadata before generic graph
traversal. The raise channel is syntactic seed lookup, not proof that an
exception executes or that transitive graph expansion improves answers.

Grouped by the 207 distinct question strings, the fields gain over body160 is
0.1992 (exploratory paired bootstrap interval 0.1460–0.2543); the raise/scorer
gain is 0.2378 (0.1799–0.2937). These inspected-data intervals are not corrected
for multiple comparisons or independent validation. Timings include shared
count caches and occasional overlapping contract tests; no speed promotion
is based on this matrix.

Audited outputs: `experiments/results/cycle28-seed-metadata-audit.json` and
`experiments/results/cycle28-seed-rank-gate.json`. The fixed plan SHA-256 is
`8f9397d498982c335919d1629d5db6d05c553728963b86eb8cc8ef5ef3843d9b`.

A separate compiler-coverage check found all 52,380 nonblank source lines in
selectable blocks, with no multiply covered nonblank lines. It does not assert
byte-for-byte source-file reconstruction or retention of every blank line.
The additional omission guard and the other output-audit attacks pass 12 tests
in a targeted run after the full suite reported below. Chunk boundaries can
still affect selection; source-line availability alone does not establish a
good representation or sufficient answers.

## Product repair and its limits

The product now restores atomic single-backtick references after its existing
query analysis, including short terms and dotted-name components. It leaves
the query bytes intact. Unknown terms still require fallback when no candidate
exists; this is not a new claim of calibrated sufficiency.

The original eight failing regressions now pass. The current suite passes
**862 tests, with 22 skips** on CPython 3.12.14. Twenty skipped oracles remain
pinned to the canonical 3.12.10 interpreter, whose launch approval previously
timed out; two concern symlink permissions. All **85 mutants** are killed,
including removal of the new literal-intent rule and the original critical
dependency/query/fallback defects. These checks do not close the pending
canonical-version verification.

The product gate checks 230 queries at four candidate limits (920 exact rank
comparisons). The product matches the declared frozen literal challenger on
every comparison. Seven queries change candidate rankings; all 21 affected
query/budget selections match the challenger exactly and obey the independently
recounted NVIDIA caps. An AST comparison verifies that packing logic outside the
query-term functions is unchanged. The seed-stage median is 2.599 ms before and
2.606 ms after in three paired passes with warmed SQLite and uncontrolled host
load; this excludes token packing and establishes no speed improvement.

The changed queries are newly added explicit-reference probes. All 207 original
rival question strings and all 15 new behavior questions have unchanged seed
rankings. Therefore the original rival benchmark does not exercise this bug,
and the narrow repair is **not** a benchmark win against CRISP. Keep the repair
for its reproduced correctness benefit. Broader filtering, subword and metadata
choices now have the diagnostic evidence above; product promotion still awaits
actual answer tests.

## Executable behavior tasks

Fifteen new source-informed questions cover multiple facts, terminal-cell width,
falsey versus missing values, chained undefined attributes, URL encoding,
numeric-conversion fallbacks, duplicate ordering, unsupported generator input,
Windows reserved filenames and relative redirects. Questions and probe code
were declared before the successful oracle runs and before choosing a seed
winner. They are development questions, not sealed holdouts.

The probes import the actual frozen library source and record executed source
lines. Both fresh-process runs produced identical answers and trace lines on
CPython 3.12.14 / Windows, with MarkupSafe 3.0.3 and Pygments 2.21.0. Examples:

- Rich can report 100%, -5 remaining units and `finished=False` for one task.
- Cropping two wide characters to three terminal cells yields a trailing space
  even when explicit padding is false.
- Jinja2's default missing-value handling differs from ChainableUndefined for
  nested attribute access.
- Werkzeug's slash redirect produces `42/?x=1` and status 308 for the declared
  input; the Location header is relative before browser resolution.

The first oracle attempt failed while trying to report the version of an unused
Markdown dependency. Its declaration and failure record remain under
`cycle28-library-behavior-v1`. The corrected v2 declaration has SHA-256
`db22ca7926a7c0b9103e8b61c421c73b66d4c69f8dce2e1d3599a7b761cd4e38`.
At the oracle checkpoint no live model call had been made for these questions.
The subsequent answer evaluation includes no-context controls, since models may
know these public libraries; see the continuation below.
Executed trace lines are provenance, not a proof of minimum sufficient context.

## Next decision

Explicit literal intent is repaired and checked; the fixed seed matrix has
passed both audit gates. Carry the strongest competent baselines into
exact-budget executable-answer tests. Only
then decide which metadata or ranking features earn product integration and
incremental-index support. Generic dependency expansion remains experimental.

All numerical findings here are **EMPIRICAL**. No new theorem, calibrated
probability, optimality or breakthrough claim is made.

The earlier repair checkpoint is saved as
`experiments/results/cycle28-literal-repair-checkpoint.zip`
(9,834,965 bytes, 639 verified members; SHA-256
`4aabacb76c7c29ceb41abf6f08c7a5c9f8ae45c515efe6819afe29ae05c8ffa5`).
It contains the narrow repair, its tests, oracle results and frozen inputs.
The seed study's raw results are outside this repair archive and need their
own completed-study archive. Decoded pattern checks found no recognized credentials in the
archived files; this is not a claim about arbitrary undiscovered secret formats.

The completed seed study is now independently archived in
`experiments/results/cycle28-seed-checkpoint.zip`: 68,391,618 bytes, 9,314 files,
SHA-256 `2e10bd0be6d76f5770f417c1d8a3ebba9b81def3e6a62c9b55641a3fa563823c`.
The bundle includes the complete raw matrix, source contexts, both audit gates,
frozen code, tokenizer, parent artifact, auxiliary index and recorded gate failure.
Every member was read back against its hash and ZIP integrity checked. There
were 320,576 decoded/SQLite-dump pattern checks with no recognized credential
matches. This certifies an archived retrieval study, not target-answer superiority.

### Behavior evaluation preparation

The 15 behavior queries now have 405 selections: seven NPK research variants
and two native CRISP variants, each at 512/2,048/8,192 exact NIM context tokens.
All selections passed independent source reconstruction, token recounting and
packing checks. The auditor checked 6,803 source items including raw native
views; reduced views are explicitly reconstructed, not misrepresented as full
literal source spans. There are no empty selections or recorded cap overruns.

Real local encoder runs indexed the 3,513 shared blocks. MiniLM L6-v2 on CPU
took 112.99 seconds for document encoding and 11.19 ms median query encoding;
Qwen3-Embedding-0.6B on the local GPU took 127.51 seconds and 43.05 ms respectively.
These exclude model loading and use different input/truncation policies, so
they are not an algorithm-only speed comparison. Their document matrices occupy
5,396,096 and 14,389,376 bytes. The local MiniLM cross-encoder reranked 160
candidates in 12,902 ms median across the questions. No answer benefit is yet
attributed to these costs. Exact model revisions and inputs are frozen in the
encoder and selection plans.

The complete current suite passes **878 tests, 22 skipped** on bundled Python
3.12.14. The product hashes still match the run that killed all 85 mutants;
these are not 85 newly rerun mutations. Canonical-version oracle checks remain
pending. The frozen target-answer plan has 435 observations and 416 unique
payloads including knowledge-only and full-context controls. Its SHA-256 is
`4b7685af9b9e2c9e35a782b599d5f0ff3d248435e220e920b8be5c052b3ba88c`.
The dry run passed before requesting a bounded live batch. Direct sandbox
network access returned PermissionError 10013 without any credential or model
request; authorized live execution uses the separately reviewed network route.

### Subsequent behavior checkpoint

There are now 76 new LIVE attempts and 59 actual responses, with 16 HTTP 503
failures and one HTTP 429. All 59 successful prompt counts match local counts.
Every arm remains incomplete; no answer winner or accuracy percentage is
published. The run is paused after service overload. The report race and request
pacing repairs, local model costs, exact grading limitations and no-offset
tokenizer challenger are documented in `CYCLE28_BEHAVIOR_ANSWERS.md`. The prior
preparation counts in this chapter are historical checkpoints.

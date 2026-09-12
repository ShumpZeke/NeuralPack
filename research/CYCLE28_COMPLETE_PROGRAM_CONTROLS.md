# Cycle 28: complete-program target controls

Overall verdict remains **PIVOT REQUIRED**. This diagnostic tests the answering
model with complete programs. It does not test retrieval, reduce context, or
establish a NeuralPack advantage over CRISP.

The earlier reference experiment left an ambiguity: missing dependencies,
reasoning mistakes, and response-contract failures could all produce a wrong
answer. Its source extractor also omitted default-expression, conditional, and
transitive initialization dependencies. The new diagnostic supplies all those
statements, explicit inputs, and a `json.dumps` output operation.

EMPIRICAL local construction: eight programs execute under CPython3.12.10 and
3.12.14 on Windows and produce matching outputs. Two use exact public source
extracts (`jinja2.filters.do_int` and `werkzeug.utils.get_content_type` with its
MIME table), plus synthetic input/output harnesses. Six are synthetic cases for
captured defaults, conditional bindings, chained initialization, closures,
exception class names, and negative constraints with symbol collisions. These
are inspected diagnostic examples, not unseen repository questions.

Per request, available and selected context are identical:46,64,282,73,119,56,57,
or313 NIM tokens, depending on the task. The mean is126.25 tokens. The numbers
describe the entire supplied executable program; they are not large-context
claims. No expected output is inserted into the model's source or question.

The same Nemotron target gets one request per program and configuration. The
question, source bytes, system message, temperature, top-p, timeout, and8,192-token
output ceiling are held fixed. Both arms set `low_effort=True`; only
`enable_thinking` changes. Equal output ceilings do not imply equal actual
compute. The tokenizer and chat template are the previously verified pinned
NVIDIA assets. Actual provider input counts still require checking against each
returned response.

Sixteen unique payloads are frozen before execution, with a seeded interleaving
of configurations. Requests start at least15 seconds apart. A429 or three
consecutive transport failures stops both arms. Each payload receives at most
one attempt; missing responses stay missing. No generative optimizer calls are
made. Dollar cost is N/A without verified endpoint billing.

The earlier45-call low-effort study on the15 library questions already tested a
different target configuration. It was not repeated. Re-auditing its saved
responses against the completed original transport-recovery pass gives:

| Same evidence: earlier low-effort profile vs direct | Wins | Losses | Ties | Missing pairs |
| --- | ---: | ---: | ---: | ---: |
| No context | 2 | 0 | 7 | 6 |
| NeuralPack BM25 | 2 | 0 | 6 | 7 |
| Native CRISP | 4 | 0 | 5 | 6 |

That historical comparison changes thinking, low-effort, and output allowance
together. It is not an isolated flag experiment. The saved profile has28
returned answers and17 HTTP503 responses from45 attempts. Different sets of
answered tasks prevent a complete aggregate accuracy comparison. For BM25,
observed mean output tokens are28.27 direct vs140.75 profile, and mean target
latency2.58 vs6.42 seconds; these means use different answered-task subsets and
are not paired causal cost estimates. CRISP also benefits; this cannot be
attributed to a NeuralPack improvement.

Artifacts: `experiments/runs/packs/cycle28-complete-programs-v1/` holds the plans,
source, local oracle records, and pinned tokenizer assets. The explicit execution
policy lives alongside them. `cycle28-target-profile-pairs-recovered.json`
regrades the saved library responses and records their provenance. No previous
ledger or strict grade was changed.

Verification before live execution:1,127 canonical tests passed, two symlink
tests skipped, and140/140 mutation checks caught their injected defects. These
checks bind351 Python sources. New tests reject altered evidence, query/system
messages, output allowances, missing/duplicate cells, invented context sizes,
unknown attempts, orphan responses, and incomplete executable oracles. They
also retain the default/conditional/transitive counterexamples permanently.

A pre-execution audit initially assumed LF for captured subprocess stdout.
Windows emitted CRLF. The audit was corrected to compare the actual Windows
serialization; no fixture answer, context, or API request changed, and no API
call was made before that check passed.

EMPIRICAL live result: all16 requests returned answers. Both arms had identical
source and question bytes and identical measured mean input tokens. All16 local
prompt counts matched provider usage exactly. Every response ended with `stop`.

| Target configuration | Strict task success | Mean input tokens | Mean output tokens | Mean target latency |
| --- | ---: | ---: | ---: | ---: |
| Direct | 6/8 | 235.25 | 15.375 | 2.944 seconds |
| Thinking, low effort | 8/8 | 235.25 | 136.5 | 7.640 seconds |

Paired outcomes are2 wins,0 losses,6 ties,0 missing for thinking. The higher
setting used8.88 times the output tokens and2.59 times the observed latency.
This small inspected diagnostic does not establish general model accuracy or
justify choosing that configuration for every application.

The direct target makes two concrete errors with complete source:

- Generator reversal: expected `[2, "StopIteration", "TypeError"]`, returned
  `[2, "StopIteration", 2]`.
- Chained initialization: expected `[7, 99, 7, 14]`, returned
  `[14, 99, 7, 14]`; the supplied return expression is `C - B`, with14 and7.

Both are valid JSON with incorrect values. They cannot be explained by missing
source or extra exception-message formatting. The executed fixture tests retain
these cases. Their exact request, response, and program hashes are recorded in
`cycle28-complete-analysis-16-typed.json`. No optimizer or target answer was
retried. The earlier45-call configuration study remains a separate historical
comparison; this cycle adds16 calls only.

ATTACK / REPAIR: two further regression tests expose native Python equality
accepting `true` as1 in a frozen answer and accepting an integer token count
changed to a float. Both tests fail before repair. The study validator now uses
JSON identity that preserves types, and the focused suite passes23 tests.
The original builder source is archived and hash checked for provenance; the
stronger current validator reconstructs its programs without executing archived
builder code. Re-auditing all saved payloads and grades produces identical
outcomes. All old requests, responses, and ledgers remain intact. The earlier
analysis file's generic statement that framing changes input counts is also
superseded: here the observed counts are identical in both configurations.

KEEP the complete-program controls, exact executable oracles, stricter audit
identity, and separation of target configuration from retrieval quality.
DISCARD the assumption that providing complete source guarantees a correct
answer. No retrieval champion or product default is promoted. The overall
CRISP comparison still favors CRISP:7 known successes against BM25's complete5
on the frozen15-task library trial. This small diagnostic does not change that.

NEXT HYPOTHESIS: future retrieval comparisons need a paired complete-source
control under the same target settings and explicit executable input harnesses.
That can reveal which tasks are sensitive to omitted evidence and which fail
even with complete input. Apply it to new repository tasks with matched budgets;
do not report this tiny-program ceiling as large-context retrieval performance.
The product still needs stronger seed retrieval to beat competent alternatives.
The broader research goal remains active.

The full suite after the identity repair passes1,129 tests with two explicit
symlink skips. The first mutation invocation times out while running the entire
16-case tampering group under one mutant. That timeout is a harness failure,
not a killed mutant. Two mutation targets are narrowed to their specific
assertion cases; the full23-case fixture suite remains unchanged. Mutation
testing is rerun in a fresh process after the full-suite process exits. This
changes neither the mutation logic nor the assertion-only kill criterion.
The new isolated runner retains the original60-second timeout. No product
performance or controlled memory improvement is claimed from that adjustment.

Final verification:1,129 tests pass, two symlink tests skip, and141/141 mutations
are killed by assertion failures. None survives, including the three original
critical mutants. The mutation run binds351 Python sources and verifies they
remain unchanged. All model-call, test, and mutation processes are terminal.
Reports use the `cycle28-complete-typed-canonical` prefix. The earlier timeout
remains recorded as a failed harness attempt; it is never counted as a kill.

Verified archive: `experiments/results/cycle28-complete-checkpoint.zip`,
6,218,053 bytes,986 files, SHA-256
`658f2f7c6b3d38d8a0a3d53b8e549d10041c5b4a7299a2b6fc3981710d7696d7`.
All member hashes and CRCs pass;351 current Python sources match their mutation
bindings. The986 decoded pattern checks find no recognized credential matches;
this is not proof against every secret format. The checkpoint explicitly leaves
the overall research goal open.

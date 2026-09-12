# Cycle 28: recover missing answers without resampling existing answers

Verdict: **PIVOT REQUIRED**. NeuralPack remains a local context compiler/runtime;
the calls here are separate target-answer experiments. This cycle changes
evaluation tooling, not the compiler, selection algorithm or `.npk` schema.

The original first stage had 148 terminal API attempts but only 99 answers.
Calling that a completed quality evaluation would hide 49 transport failures.
The full frozen plan also contains 268 later-stage payloads never attempted.
No full 558K-context LIVE request has been sent.

## Repair and validation

`benchmarks/answer_recovery.py` creates a separate stage from explicit expected
parent plan and ledger hashes. It archives every original attempt verbatim,
including failures. Successful responses become REPLAY records with LIVE origins
and zero new API calls, even when the answer is wrong. Only known terminal HTTP
429/503 failures without an answer/usage/raw success response qualify for one
new LIVE attempt. Unknown outcomes, removed successes, changed contexts,
questions, oracle answers, selection metadata and generation settings are refused.

The new stage preserves the parent's ordering, 150 observations, 148 unique
payloads, 15 tasks and 2,048-token caps plus the no-context control. It does not
change failed attempts in the original ledger. A recovery retry that itself
fails remains DONE in the new ledger; this policy does not repeatedly retry it.
Reusing those failures in a further generation would require a separately
declared policy and lineage. No such generation was created here.

The executor invokes recovery validation before dispatch and requires one worker,
at most ten requests per invocation, at least 15 seconds between starts, and a
pause after at most three consecutive transport failures. An isolated HTTP 429
also pauses under the existing executor policy. The continuation wrapper preserves
the interval across invocations. All executions in this cycle are terminal.

The independent answer reporter now records `attempt_stage_complete` separately
from `answer_stage_complete`. The legacy `status` field remains an attempt-status
label; it must not be cited as evidence of complete answer quality. Recovery
accounting retains historical API attempts and original failures alongside the
new attempts. Missing answers keep accuracy N/A.

Canonical validation: **1,087 passed, two symlink skips, 132/132 mutants killed**.
The mutation report binds 347 current Python sources. Six new mutants attack
unknown parent outcomes, broader retry eligibility, lineage, payload identity,
unbounded dispatch and false answer completeness. Tests use synthetic records
and a fake transport; none contacts a model. An initial fixture error used an
unsupported empty template-flags dictionary; corrected before LIVE execution.
The successful focused run passes 46 checks; the canonical suite includes five
additional direct execution-bound cases.

## New answer evidence

The first bounded batch sent ten requests and recovered eight answers. The second
sent eight requests and recovered four answers, then paused after three consecutive
HTTP 503s. Original and new records remain separate.

| Measure | Before recovery | Current checkpoint |
|---|---:|---:|
| Cumulative API attempts | 148 | 166 |
| Unique payloads with a returned answer | 99 | 111 |
| Unique payloads still unanswered | 49 | 37 |
| Eligible payloads not yet attempted in recovery | 49 | 31 |
| Failed new recovery attempts | 0 | 6 HTTP 503 |
| Generative optimizer calls | 0 | 0 |

All 111 returned prompt-token counts match the pinned local tokenizer and prompt
template. Two shared payloads serve multiple observations; 150 observations are
not 150 independent model samples. The original ledger remains SHA-256
`8a0500a8610486c02ca5cfd1413090f77102e4a6cfe9ee00868b90ad0412392a`.
The recovery ledger at this checkpoint is
`9aff6c4ca3614f08c22ed1014ed97cc3b273f1ce9a0fd63b4fdf8d537a972782`.

| Frozen method at 2,048-token cap | Correct | Answered | Missing |
|---|---:|---:|---:|
| NeuralPack BM25, 60 candidates | 5 | 12 | 3 |
| Native CRISP with NIM budget guard | 7 | 13 | 2 |
| Field-weighted lexical, 160 candidates | 5 | 10 | 5 |
| MiniLM hybrid, body | 4 | 12 | 3 |
| MiniLM hybrid, fields | 2 | 10 | 5 |
| Qwen hybrid, fields | 4 | 13 | 2 |
| Qwen reranker, fields | 1 | 10 | 5 |
| No-context control (0 evidence tokens) | 1 | 10 | 5 |

Each method has 15 planned tasks; all complete-accuracy fields remain N/A. The
NeuralPack BM25 versus native CRISP comparison has one win, two losses, seven
ties and five missing pairs. It establishes no winner. Source availability is
558,878 tokens per request in the frozen source-file representation. Do not
substitute the different 559,083-token compiled-block representation from the
counting study. Actual selected means differ slightly under the same caps.

This is one stochastic returned answer per payload, with transport recovery
spread over time. It cannot exclude hosted-service changes between attempts.
Tasks are inspected public-library cases, not a sealed holdout. No dollar cost,
pricing assumption, universal sufficiency claim or broad retrieval advantage
is inferred. The report is `experiments/results/cycle28-recovery-answer-18.json`.

## Counterexample and next hypothesis

**EMPIRICAL:** in the `werkzeug_mime_charset` task, both the native CRISP and
field-weighted contexts contain the complete `get_content_type` implementation
and complete `_charset_mimetypes` literal assignment. Both returned answers
incorrectly add a charset to JSON media types. The executed oracle disagrees.
`cycle28-recovery-counterexample.json` binds the two response origins, exact
context hashes, source-file hash and complete source spans. This diagnostic
makes zero new API calls and does not count those responses twice.

The observation rejects the assumption that exposure to a named implementation
and its table guarantees a correct target answer. It does not prove that every
dependency is present, or distinguish reasoning errors from distraction or
ordering effects. It also does not establish that graph expansion adds value.

**CONJECTURE:** a compact reference arm, manually seeded from inspected source
and supplied with required literal configuration, may reduce distraction enough
to change target answers. Freeze this as a separate diagnostic, with exact token
caps and unchanged questions/settings, before making any calls. It is not a
deployable retrieval algorithm or a proven quality upper bound. Compare it with
the existing contexts to decide whether omission, context presentation or target
reasoning is the next bottleneck. Keep all unsuccessful counterfactuals.

Keep the recovery provenance and honest completeness fields. Discard any claim
that attempt completion, structure exposure or tokenizer speed proves answer
quality. Continue the remaining 31 never-retried eligible payloads only after
reviewing the active service pause and an appropriate cooldown. Existing answers
and the six failed retry records must remain untouched. Further tokenizer
micro-optimization stays below answer-quality investigation in priority.

Verified checkpoint: `experiments/results/cycle28-recovery-checkpoint.zip`,
5,469,646 bytes, 798 files, SHA-256
`ef10081a495486f36881dd51c168a951e1207d44c95229ce41e07f93eb16792e`.
All member hashes/CRCs and source bindings pass. Its 798 decoded text pattern
checks found zero recognized credentials; this is not a proof for every secret
format. The previous counting checkpoint is referenced by digest. The research
goal remains active and this cycle records progress, not completion.

This49-eligible-payload pass was subsequently finished during the reference-evidence
cycle. See CYCLE28_REFERENCE_EVIDENCE.md and `cycle28-recovery-answer-49.json`:
35 recovered answers,14 failed retry attempts,134 original-or-recovered answers,
197 historical API attempts, no never-retried eligible payloads. The original
ledger is unchanged. BM25 now has all15 answers and5 successes; native CRISP has
7 successes with one answer missing and therefore wins this frozen comparison.
The18-attempt checkpoint above remains the earlier frozen snapshot, not the latest
accounting. Current canonical checks are1106 pass,2 skips,138 killed mutants.

# Stored types and answer diagnostics

Status: accepted for artifact boundary checks; retrieval promotion remains gated
on answer evidence. Compiled format 5 and compiler 5.2 remain unchanged.

## Problem and repair

**EMPIRICAL:** SQLite's column affinity allowed binary values in text fields.
A resealed binary source block crashed verification. A binary manifest mode
could pass verification and query/update acceptance. An initialization failure
after opening a writable connection could leak that connection and expose a raw
SQLite exception. Permanent regression tests reproduce these failures.

Full verification now checks stored value types against the compiler's own
schema before interpreting source text. The check derives constant SQL queries
from trusted local schema code; it does not accept SQL supplied by an artifact.
Query and update share the same manifest reader, which rejects non-text keys
and values. Connection ownership is released on initialization failure,
including cancellation. Expected storage failures become `PackError`; unrelated
exceptions are re-raised.

The full scan runs on artifact acceptance, not each query or cached update.
Cached updates still assume an already accepted base and correct invalidation.
These checks establish neither external source authenticity nor every semantic
constraint on an arbitrary, self-declared artifact. Internal hashes and valid
storage types alone cannot establish those properties.

## Measuring answers rather than source coverage

Cycle 13 freezes a diagnostic follow-up on eight known Click 8.5.0 questions.
Each model has its own immutable plan, with 80 unique prompts. The artifact,
source hashes, exact rendered contexts, questions and settings are checked before
dispatch. Two independently reconstructed same-source arms compare bare passages
with file/span/symbol labels; headers must fit inside the declared budget.
Normal BM25 is also retained to expose the source displaced by those headers.

Required-definition and called-definition controls are privileged diagnostics.
The latter observe Python function identities while executing trusted test
oracles, then extract literal pinned library source. They do not include oracle
bodies, locals, expected outputs or branch values. Class context is included;
unmapped comprehensions are disclosed. These are not deployable retrieval
algorithms, proven sufficient contexts, MSC results or matched-budget baselines.

**CONJECTURE:** source identity labels may reduce a target model's confusion
when a passage begins inside a class or function. The same-source comparison
tests this separately from changing retrieval. A useful control answer indicates
possible headroom; a failed control does not prove the model received every
needed fact. See the [complete result](../../experiments/results/cycle13-answers.md)
and [cycle record](../../EVOLUTION_LOG.md) for outcomes and promotion decisions.

## Honest grading and limitations

**EMPIRICAL:** the old JSON parser accepted duplicate keys by keeping the last
value. Strict grading now rejects duplicates, including nested and escaped-key
duplicates, and the non-JSON numeric constants NaN and Infinity. Regression
tests and an assertion-killed mutant cover the defect. Regrading 339 archived
completed-answer observations changed no prior grades; those observations are
not all independent trials.

The answer models use distinct declared configurations. Compare methods within
each model; do not attribute cross-model differences to architecture alone.
Requested non-thinking settings do not prove server implementation details.
Provider overloads and missing answers are separate from wrong answers, and
failed or uncertain requests are never silently retried. Actual provider token
usage is separate from estimated context budgets. Dollar pricing is unverified.
There is no remote LLM preprocessing comparison or savings claim in this cycle.

The runtime makes zero generative calls. Diagnostic orchestration, live answer
evaluation and downloaded challenger models are development tooling, not default
product dependencies.

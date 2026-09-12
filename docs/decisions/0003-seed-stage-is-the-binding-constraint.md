# ADR 0003 — Validate seeds before relying on dependency expansion

**Status:** Corrected in cycle 10, 2026-09-06. Previous accuracy, cost, threshold
calibration and sealed-evaluation claims are withdrawn. They were invalid
evidence for the public compiled runtime.

## Decision

Default selection uses BM25 lexical search. Exact symbols and local embeddings
are optional hybrid channels. Graph indexing and expansion remain experimental
and disabled by default. Neither challenger has earned general promotion against
the corrected baseline. See [ADR 0004](0004-npk-is-an-llm-independent-context-compiler.md)
and [the evolution log](../../EVOLUTION_LOG.md).

An empty candidate set requires another retrieval path or an explicit fallback
request. A nonempty set does not prove that the needed facts were retrieved.
Applications retain the question and system instructions separately. An explicit
token budget is never silently enlarged.

## Defensible negative result

**PROVED.** For bounded directed reachability from seeds S,
`Closure_D(empty) = empty`. A path must start at a seed; with no seeds there
are no such paths. See [the proof](../../research/math/theorems.md).

This does not bound expanded evidence recall by the number of required facts
already in the seeds. A seed can lead to a required fact not retrieved directly.
Increasing depth can reach a more distant fact. Neither operation helps when
no seed or relevant path exists. Budgeted assembly can discard reachable facts,
so connectivity alone is not an end-to-end recall guarantee.

## Evidence and unresolved work

**EMPIRICAL.** Cycle 9's corrected executable urllib3 workload did not establish
a same-budget answer-quality gain from method chunks or hybrid retrieval. Its
local cross-encoder challenger added seconds of preprocessing and had mixed or
worse source-span coverage. The dataset was small and developer-known.

The current hybrid cosine floor is an uncalibrated heuristic. The old sample
separation does not establish a general threshold, probability or safety rule.
Default BM25 does not use that floor.

**CONJECTURE.** Better seed construction, explicit source scope and iterative
local evidence acquisition may improve difficult semantic-gap questions. Test
these against competent baselines across budgets before adding default
complexity. Evaluate graph traversal after improving seeds, with the same
available source and selection budget.

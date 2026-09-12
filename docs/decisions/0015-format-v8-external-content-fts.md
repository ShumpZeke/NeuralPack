# ADR 0015: Use external-content FTS5 for incremental packs

Status: accepted

Date: 2026-09-11

## Context

The format-v7 lexical index used contentless FTS5 with explicit delete rows.
That avoided storing a second copy of each block body, but a changed document
that was deleted and reinserted could receive different BM25 document-frequency
normalization from a clean rebuild. SQLite's FTS5 `integrity-check` still passed,
so the failure was observable as a ranking difference rather than a structural
error.

NeuralPack needs a portable `.npk` that can be updated in place while keeping the
exact source body available for evidence emission. The index must also support
the normalized identifier and path fields used by the zero-generative runtime.

## Decision

Format v8 uses an external-content FTS5 table whose content row is `blocks.id`.
The authoritative body stays in `blocks.text`. The compiler inserts normalized
search values into the FTS index, while `blocks.path` stores the normalized path
metadata required by the external-content schema. The updater deletes the exact
old normalized `(text, name, path)` values before deleting or replacing block
rows. It does not rebuild the whole FTS index for a one-file update.

The format version and integrity digest domain are bumped. Readers reject older
packs and the updater requires an explicit recompilation, which prevents an old
posting contract from entering the new update path.

Full verification runs FTS5's internal maintenance check and, for an otherwise
valid artifact, builds a rollback-only temporary contentless index from values
derived from `blocks` and `files`. It compares actual and expected FTS5 instance
postings by `(term, document, column, offset)`, then compares document-length and
configuration metadata. This source-parity check is an acceptance-time safety
check; query selection remains deterministic and LLM-independent.

## Consequences

Incremental updates preserve BM25 scores and query payloads relative to a clean
rebuild on the measured 153-file corpus. The artifact is about 1.56% larger than
the prior definition-only v7 artifact because of the normalized path metadata and
SQLite storage history. The source-parity check adds roughly 0.68 seconds to full
verification on the 3,513-block frozen code pack; callers should verify restored
or externally supplied artifacts rather than repeating verification per query.

The external-content index is deliberately not a general source-edit interface.
Direct changes to authoritative block search fields must be followed by a correct
source-aware index update; otherwise verification rejects the artifact. A
self-declared root remains an integrity checksum, not publisher authentication.

Evidence: [Cycle 37 AlphaEvolve record](../../research/CYCLE37_ALPHAEVOLVE.md),
[final artifact audit](../../experiments/results/cycle37-final-audit-v5/report.json),
and [full mutation report](../../experiments/results/cycle37-contract-mutations-v7.json).

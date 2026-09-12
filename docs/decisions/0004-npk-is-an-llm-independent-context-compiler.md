# ADR 0004 — A local context compiler and runtime

**Status:** Architecture retained; evidence and implementation description
corrected in cycles 10–11, 2026-09-06. Former accuracy, dollar savings, break-even and
graph-superiority tables are removed. They were invalid evidence.

## Product

NeuralPack prepares a searchable local copy of source files. It selects passages
for a question and returns their original text and locations. Your application
then asks its chosen AI to answer using those passages.

```text
Source files → compile → project.npk
                             ↓
Question → local selection → evidence → application's target model
```

The compiler and default selector make zero generative model calls. No API key
is required. Development agents and explicit LIVE answer benchmarks are outside
that runtime. Provider metadata does not alter the core source representation
or silently trigger a remote optimizer.

## Artifact

The current artifact is a versioned SQLite database with source hashes, metadata,
chunks, provenance, FTS5 search and symbol indexes. Embedding and dependency
indexes are optional. It requires no provider-specific model state.

SQLite supplies indexed reads and transactions in a portable file. This is an
engineering choice, not proof that SQLite beats every ZIP or directory design.
Earlier container microbenchmarks used different indexing capabilities and do
not validate current product latency. No new custom binary container is justified
by current evidence.

Format 5 verification checks schema, actual data, derived FTS storage and SQLite
structure. A trusted external root can pin an artifact's identity. Its own digest
does not authenticate its publisher or recover lost data. Full verification is
separate from the query fast path. Recompilation replaces the prior artifact
only after a successful temporary build. Applications must serialize writes;
this does not establish power-loss recovery. Version 5 reuses file digests during
controlled updates, while full verification rereads all files. Queries have
consistent read transactions; busy timeouts remain possible. See
[ADR 0005](0005-incremental-integrity-and-read-snapshots.md) for the cache's trust
assumptions, transaction behavior and required recompilation of older artifacts.

## Selection and fallback

Deterministic mode uses CPU lexical search by default. Optional semantic mode
stores vectors from a pinned local encoder; hybrid queries use an offline
non-generative encoder for the query. Missing weights never cause a remote call.
Initial semantic compilation can report an unavailable encoder and retain a
lexical artifact. Updates to an existing semantic index require a compatible
encoder and roll back if it is unavailable or mismatched.

Graph expansion and conflict deletion are experimental and disabled by default.
The local fallback sequence can widen retrieval, optionally expand dependencies
when explicitly enabled and seeds exist, or report that the caller needs more
context. It does not silently enlarge budgets or send full source to a provider.

Selected source remains source text. The original question survives in the
selection result; callers keep system instructions and question separate.
Empty results report fallback required and no reduction win. Nonempty evidence
and an ordinal `uncalibrated` risk band do not certify answer sufficiency.
Budgets currently use chars/4 over selected text and default separators,
excluding caller query, instructions and wrappers. They are not exact provider
token counts.

## Compilation and economics

Unchanged files skip parsing and indexing. Semantic updates can reuse unchanged
block vectors under a matching encoder identity. Scanning and integrity sealing
still perform repository-wide work. No-change updates do not rewrite the
artifact. Ordinary changed-file updates are not constant-time.

**EMPIRICAL.** Post-fix cycle records report compilation, updates, memory, disk
and query costs by workload and cache state. They retain completed answers,
transport failures, actual reported usage and exact-prompt replays. LOCAL span
coverage is not target answer accuracy. See [EVOLUTION_LOG.md](../../EVOLUTION_LOG.md)
and its raw reports for numbers and limitations.

Dollar savings and an economic break-even point remain unestablished. They
require verified prices, cache treatment, actual success and deployment costs.
Zero-generative selection is a design constraint; an invalid old cost table
cannot serve as its empirical proof.

## Boundaries and checks

Runtime tests block network/provider calls, preserve query/budget contracts,
exercise updates and check integrity. They cover tested paths, not arbitrary
future code. Known credential filenames are excluded, but arbitrary source may
contain secrets and must be reviewed. Invalid UTF-8, oversized eligible files
and unreadable eligible files/directories abort builds instead of dropping data.

The old byte-container implementation remains behind explicit legacy commands.
It is not evidence for this selector. A differentiated retrieval or answer-quality
advantage remains unsubstantiated; BM25 is the operational baseline.

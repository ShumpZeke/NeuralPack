# ADR 0005 — Incremental integrity and consistent reads

**Status:** Adopted in cycle 11 for the compiled infrastructure after paired
whole-operation measurements and 16/16 killed contract mutants. Retrieval
quality remains unsubstantiated; this is not promotion of a new seed algorithm.

## Problem and proposed change

Version 4 rehashed all symbols and source rows after even a one-file edit.
The version 5 candidate stores one digest per source file and records which
files a transaction changes. It refreshes those digests during sealing. Full
verification independently rereads all source rows and compares them with the
cache. The query path still performs no generative model calls.

The schema adds `integrity_files` and `integrity_dirty`, plus eighteen
triggers: insert, update and delete for files, provenance, blocks, symbols,
assignments and embeddings. A move marks both owners. Deletes mark the owner
before cascading deletes remove the relationship. Inserts and updates mark
afterward. Dirty IDs have no foreign key so deleted IDs survive until sealing.
SQLite defines these events and the OLD/NEW row references in its
[trigger documentation](https://www.sqlite.org/lang_createtrigger.html).

File digests include sorted rows from all six file-local tables. The root
includes schema SQL, sorted file digests, the persisted cache, the clean journal,
manifest fields other than the root itself, dependency edges, and all known FTS
shadow storage. Fields use type tags and byte-length framing. Unknown tables,
views and triggers are rejected; arbitrary SQL schema extensions and ANALYZE
tables are not part of this format. A root's exact serialization is defined by
`npk/pack/integrity.py`, not by a provider or a model.

Before a changed update, the cached base must be complete and clean, its
tracking schema must match, and its schema/global storage/cache root must match
the recorded root. Refreshing leaves, clearing the journal, changing the root
and changing source data are in the same transaction. An injected exception
after refresh must leave the artifact byte-identical to its prior state.

## Claims and assumptions

**PROVED UNDER ASSUMPTIONS — incremental sealing equals full recomputation.**
Let each file have digest H(L_i) of its file-local rows. Assume the accepted
base's cache equals those digests, all changes to those rows mark both affected
owners, deleted owners are removed, new owners are hashed, and the operation
uses one transaction. For every unchanged owner the old digest still equals
H(L_i). Every changed or new owner gets a freshly computed H(L_i). Therefore
the resulting ordered list of file digests equals full recomputation. Hashing
the same global rows, cache, journal and schema with that list gives the same
root. This is a decomposition argument, not a claim that hash collisions are
impossible or that SQLite has no implementation defects.

**FALSIFIED — a cached root alone verifies arbitrary changed bytes.** If a
block is changed while its dirty entry is removed, a cache-only root can miss
that change. The permanent attack changes both block text and its stored text
hash, then clears the journal. Full verification must still reject the artifact.
The update preflight does not read every unchanged file and is not a replacement
for full verification. Verify externally obtained or restored packs before
accepting them as update bases. A self-declared root cannot authenticate a
publisher; use a separately trusted expected root when identity matters.

**EMPIRICAL — supported mutation paths.** Regression checks cover file and
block moves, metadata edits, symbol/assignment removal, embedding insertion,
deletion, rename, dependency-policy changes and a formerly unembedded semantic
artifact gaining vectors for unchanged files. This evidence covers the tested
compiler SQL paths. It does not authorize arbitrary external SQL manipulation.

**PROVED UNDER ASSUMPTIONS — work avoided by the cache.** Under the same
invalidation assumptions, leaf hashing reads rows for changed files only.
Sealing still rereads global FTS storage; source scanning still reads the tree.
Neither updates nor full verification are constant-time in corpus size.

## Concurrent readers and writers

**EMPIRICAL — reproduced query race.** A query could first retrieve old block
IDs, then read source rows after an update removed those IDs. A controlled
interleaving returned a failed seed instead of the previously available evidence.
Readonly pack contexts now begin an explicit read transaction. Update preflight
starts inside `BEGIN IMMEDIATE`, so another writer cannot change the base
between validation and mutation. The regression checks both sides.

SQLite read transactions retain their snapshot, while an immediate write
transaction reserves the writer. In rollback-journal mode an open reader can
delay commit, and a busy error remains possible. See SQLite's
[transaction documentation](https://www.sqlite.org/lang_transaction.html).
The current connection timeout is five seconds. Long optional encoder loads or
full verification can delay writes. Applications must serialize writes,
including compilation by replacement, and handle explicit update failures.
This work does not benchmark crash/power-loss recovery or promise unlimited
concurrent writes. Source-directory changes during scanning are not an atomic
repository snapshot; callers should compile a stable checkout.

## Compatibility and evaluation

The implementation uses format 5 and compiler 5.0. Older artifacts are rejected and
must be recompiled from source. Relabeling a version-4 root cannot migrate its
contents. Indexes and retrieval rules are unchanged; new root values are not
supposed to match old-format values.

The paired harness compares the committed version-4 champion against an exact
candidate source snapshot. It uses 105 real Click source, documentation and test
files, three deterministic trials, an optional local semantic comparison,
identical edits, and queries at 512/2,048/8,192 estimated token budgets. It checks
exact selected text hashes, spans and token counts after initial builds and
updates. Each updated result is also compared with independent fresh compilation.
No model-answer call is needed to test whether these selections are identical.

The report must include compilation, no-change updates, small and large file
edits, 1% and 10% file changes, delete/rename, full verification, queries, disk
and process memory. Any compile/update amortization is wall time only. It is
not dollar savings, query break-even, target accuracy or proof of better retrieval.

**EMPIRICAL — quality verdict remains PIVOT REQUIRED.** Faster incremental
bookkeeping cannot establish a quality advantage over BM25 or hybrid search.
Graph expansion remains experimental and disabled by default.

**EMPIRICAL — adoption evidence.** The first candidate's three-trial default
small-file update median fell 381.5 to 68.4 ms; eleven-file updates fell 592.0
to 249.0 ms. A final-build repeat retained the gains and identical evidence.
Its new build transaction starts inside `executescript`, before schema DDL;
otherwise Python/SQLite commits individual CREATE statements. Three local
challengers measured this fixed overhead: at 2,186 available tokens, first-v5
compilation medians were 316.0 ms with separate DDL, 176.4 ms with only tracking
DDL batched, and 35.4 ms with all build writes batched. All-build batching is
adopted; the partial solution is discarded. Source and query snapshots remain
provider-independent. Full results and limitations are in the cycle record.

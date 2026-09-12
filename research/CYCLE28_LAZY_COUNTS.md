# Cycle 28: hydrate candidate counts instead of every source block

Overall verdict remains **PIVOT REQUIRED**. This is a cost and memory improvement
to the experimental count cache. It does not change ranking, evidence selection,
target answers or the product `.npk` format. The compiler/default runtime continue
to make zero generative calls. Separate real target-answer testing is reported
below, not attributed to this counting change.

## Observation, implementation and attacks

The previous trusted loader read every source block, hashed every text and created
all prepared count records before answering a question. On SQLAlchemy, this took
about 129 ms after tokenizer startup and retained 5,227 records. Most queries
consider only 60 candidate blocks.

`LazyCount` captures and verifies the same bounded SQLite index bytes, checks
schema/tokenizer/engine identity, and opens a private read-only SQLite snapshot.
It looks up count records by the complete UTF-8 source-text hash when they are
first encountered. Hydrated records remain under the existing byte/entry limits.
Missing records use full upstream encoding; no record is compiled during a query.
This counting fallback preserves the selected evidence and is distinct from a
retrieval failure requiring more context.

`LazyCountSelector` checks the index's parent root and ownership digests inside
the selector's existing source read transaction. A stale or foreign index raises
an explicit error. The reader does not open a second source snapshot during
selection. Count records are content-specific; source provenance continues to
come from the public selector's current source blocks.

A trusted build receipt is mandatory. Unknown caches must use the separate full
verification path before adoption. Computing a hash from an unknown file is not
independent trust. The whole count-index snapshot is still read, hashed and
deserialized; this is lazy source hydration, not mmap or sublinear verification
of arbitrary external bytes. The existing compiled schema is unchanged.

Reuse is explicitly limited to the inspected engine version. A simulated future
engine identity tests fallback only; it does not claim to execute that future
engine. The previous conditional barrier argument and pinned-asset assumptions
remain unchanged. No new universal tokenizer theorem is proposed.

Twelve new tests use real BPE and SQLite. They attack hidden query compilation,
unbounded record reads during hydration, equal-length text aliases, missing
records, absent/wrong receipts, malformed records, partial hydration after an
error, post-load index modification, source updates, concurrent source snapshots,
parallel requests, memory limits and close behavior. The live index is a captured
snapshot, so changes to the external file cannot alter it. A newly opened reader
rejects those changed bytes under the old receipt.

## EMPIRICAL: two frozen public-source workloads

The library corpus has 153 files and 559,083 available compiled-block tokens per
request. SQLAlchemy 2.0.43 has 409 source/documentation files and 2,342,422 available
tokens per request. Both input artifacts pass full content/index verification.
Their exact hashes, previous source chunking and questions are retained. These
are neither accumulated context sizes nor the older character/4 estimates.

Three fresh-counter arms are compared: no-offset whole encoding, eager loaded
counts, and lazy counts. Four warm-query arms additionally include a lazy reader
whose hydrated source records are cleared before every query. All use the same
public lexical retrieval, 60 candidates and exact caps of 512, 2,048 and 8,192.
Whole-text count caches are disabled. The retained lazy arm gradually caches
encountered records; cold-record timings include fetching them again.

All **135 fresh and 1,620 warm observations** match the previous frozen selections
completely apart from latency. Final query text and exact whole-encoder context
counts are checked. An additional audit checks every actual candidate admission:
**2,700 library and 5,400 SQLAlchemy trials**, reproducing all 135 task/budget
selections without compiling a region. Ranking is reused; the independent oracle
is the full upstream encoder, not a second retrieval implementation.

| Workload / phase | No-offset control | Eager counts | Lazy retained counts | Lazy cold records |
| --- | ---: | ---: | ---: | ---: |
| Libraries, fresh 2K request | 834.07 ms | 761.59 ms | 702.23 ms | Same initial state as lazy |
| SQLAlchemy, fresh 2K request | 889.18 ms | 858.67 ms | 743.40 ms | Same initial state as lazy |
| Libraries, warm 512 | 65.28 ms | 14.58 ms | 14.66 ms | 15.85 ms |
| Libraries, warm 2K | 186.82 ms | 24.20 ms | 25.60 ms | 26.05 ms |
| Libraries, warm 8K | 551.72 ms | 66.61 ms | 66.84 ms | 66.61 ms |
| SQLAlchemy, warm 512 | 128.79 ms | 63.86 ms | 65.54 ms | 65.92 ms |
| SQLAlchemy, warm 2K | 242.24 ms | 72.90 ms | 74.84 ms | 74.12 ms |
| SQLAlchemy, warm 8K | 686.70 ms | 114.40 ms | 117.25 ms | 117.62 ms |

Values are within-run medians. Fresh totals include counter construction, cache
setup, selector construction and the first query. They exclude initial index
compilation, interpreter startup, garbage collection and cold-OS effects. Both
profiles run sequentially with no simultaneous NeuralPack benchmark; other host
load is uncontrolled. The subsequent live batch and full tests begin only after
both timed profiles finish.

Lazy fresh requests beat the no-offset control in all 45 paired questions. They
beat eager loading in 14/15 library pairs and all 30 SQLAlchemy pairs. The one
library loss is preserved. Warm queries have modest extra checks/lookup overhead:
the candidate is not faster in every phase. Eager loading remains a useful
long-lived-process control rather than being declared obsolete.

## EMPIRICAL: source-cache allocation

Every fresh 2K lazy query hydrates 60 records. After the entire warm workload,
the library lazy reader retains 508 records / **835,762 accounted bytes**, versus
3,451 / **4,255,187 bytes** eagerly. SQLAlchemy retains 473 / **1,192,198 bytes**,
versus 5,227 / **12,794,267 bytes** eagerly. The SQLAlchemy count-record allocation
is about 10.7 times smaller on this workload; that is not a 10.7x process-memory
or product-speed claim.

The reader also retains a SQLite snapshot of the 1,216,512-byte or 1,806,336-byte
index. SQLite internal structures, model/backend memory and allocator retention
are outside the Python count-record accounting. Cold-record mode ends with only
60 hydrated records, but pays their lookup costs again on the next request.
These measurements do not support a universal cache-size ratio.

## Keep/discard and next hypothesis

Keep lazy loading as an experimental alternative for short-lived queries and
large corpora. Keep eager loading for warm-throughput comparison. Discard the
assumption that every query must hydrate every available source record, and the
claim that lazy loading uniformly improves warm latency. No retrieval champion
is promoted from a count-equivalence experiment.

Further counting micro-optimization is now lower priority. The next product step
is a deliberate optional compiler/runtime integration, with a provider-neutral
profile identity, atomic source/profile updates, explicit trust and unsupported-
engine fallback. The current sidecar remains research-only until those contracts
and economics are tested. Separately, restore complete real-answer evidence and
return to seed-quality comparisons; counting improvements do not close the CRISP
retrieval gap.

Evidence directories: `cycle28-lazy-{libraries,sqlalchemy}-v1`, containing frozen
plans, execution sources, phase timings and individual observations. The existing
verified count indexes are reused by receipt. `cycle28-lazy-summary.json` checks
pair identities, counts, phase sums, cache bounds and all source/input hashes.

Canonical checks complete: **1,057 tests passed**, two explicit symlink skips,
**126/126 mutants killed** by assertions, and all 345 Python source hashes match.
The six new mutants cover parent identity, hidden compilation/full scans, source
aliases, unsupported-engine reuse and partial hydration. Every previous critical
query, fallback and dependency mutant is still caught.

## LIVE: the first attempt stage finishes, but answers remain missing

After a verified 6,022-second cooldown, the unchanged original target plan sends
its remaining seven never-attempted 2K/no-context payloads. Five return answers
and two return HTTP 503. No completed payload is retried, no optimizer model is
called, and no larger-budget request is dispatched. The batch is terminal.

The independent `cycle28-library-answer-148.json` audit binds the stable ledger
`8a0500a8610486c02ca5cfd1413090f77102e4a6cfe9ee00868b90ad0412392a`.
There are 148 original LIVE attempts: 99 answers, 48 HTTP 503s and one HTTP 429.
All 99 successful prompt-token counts match the pinned tokenizer/chat template.
Every first-stage payload has been attempted, but **49 lack an answer**. No
complete per-method accuracy is reported; missing results remain N/A.

At 2K, the available BM25 outcomes are four correct of eleven answered, and the
native CRISP control has six correct of twelve answered. Their jointly observed
questions have one BM25 win, two losses and six ties; six pairs remain missing.
These incomplete inspected tasks do not establish an answer-quality winner.

Next quality step: an explicit recovery plan for known failed transports, with
separate attempt lineage and successful answers preserved as REPLAY. Do not
overwrite or resubmit DONE entries in the original ledger. Do not retry any
uncertain in-flight request. Provider recovery is intermittent, so retain bounded
batches, pacing and failure pauses. This is higher priority than further counting
micro-optimization; the broader goal remains active.

Verified checkpoint: `cycle28-lazy-checkpoint.zip`, 32,373,729 bytes, 1,045 files,
SHA `9285dfd16f64355fd3874b384157a148525f811d3e8036610bf0c92d8a433a7b`.
All member hashes/CRCs and SQLite integrity checks pass. 631,238 decoded/SQLite
pattern checks find no recognized credential match; this is not a proof covering
every possible secret format. Code, tests, both local profiles, count indexes,
source artifacts and the stable 148-attempt target evidence are preserved. All
processes launched in this cycle are terminal.

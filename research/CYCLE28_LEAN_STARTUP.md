# Cycle 28: remove vocabulary copying, then test a larger corpus

Overall verdict: **PIVOT REQUIRED**. The optional counting cache improves local
costs; it does not establish better retrieval or target answers than CRISP.
The core `.npk` format and default runtime remain unchanged. Every new trial
is LOCAL with zero generative calls.

## Discovery and implementation

The earlier startup profile exposed a whole-vocabulary serialization followed
by a second JSON decode. `LeanCompactBoundaryCount` now reads the already loaded
backend's normalizer and added-token metadata directly. It inherits the same
compact region algorithm, source-keyed cache, fallback and persistent format.
The original no-offset and compact constructors remain frozen controls.

The underlying `LocalTokenizer` still reads one bounded byte body, checks model
dropout, constructs the backend from those same bytes, hashes them, and disables
padding/truncation. The new constructor preserves the asset restriction and all
normalizer, whitespace, word-boundary and cross-separator added-token guards.
The tokenizer library exposes these metadata accessors and AddedToken flags.
[Tokenizer API](https://huggingface.co/docs/tokenizers/api/tokenizer),
[AddedToken API](https://huggingface.co/docs/tokenizers/api/added-tokens).

Fourteen new regression cases use a real tiny BPE backend. They check each guard,
Unicode/added-token fallback, memory-limit validation, previous-cache compatibility,
zero unexpected network access, no hidden compilation and the absence of the full
JSON round trip. This changes initialization only; it adds no new mathematical
exactness claim. The restricted assumptions from the
[persisted-count study](CYCLE28_PERSISTED_COUNT_CACHE.md) still apply, including the
inspected tokenizer asset, tokenizers 0.22.2, and trusted immutable prepared state.

## EMPIRICAL: fresh requests and warm queries

Both frozen public corpora pass full `.npk` content/index verification. The first
contains 153 Rich/Jinja/Werkzeug files and 3,513 blocks. The second contains 409
SQLAlchemy 2.0.43 source/documentation files and 5,228 blocks. It retains the older
study's uniform physical-line character windows; the source is not recompiled
under a different chunking rule to make this comparison.

Each request can access **559,083** or **2,342,422 exact NIM tokens**, respectively,
in the assembled compiled-block representation. These are per-request counts,
not accumulated totals. The earlier 558,878 figure describes the library source
representation used in the rival experiment; it is not interchangeable with the
block-assembled count here. Old SQLAlchemy character/4 estimates are likewise
not substituted for this newly measured exact count.

All arms use the same public lexical selector, 60 candidates and exact context
caps of 512, 2,048 and 8,192. No-offset counting encodes the whole candidate
assembly. Both cache arms load identical precompiled compact records. Complete
selection objects agree apart from latency; final assembled counts are checked
with the upstream encoder. Queries survive unchanged, and no generative optimizer
is called. This is a counting-cost comparison, not a stronger-retrieval comparison.

| Workload / phase | No-offset control | Old loaded cache | Lean loaded cache |
| --- | ---: | ---: | ---: |
| Libraries, fresh 2K request | 834.02 ms | 1,019.57 ms | 750.44 ms |
| SQLAlchemy, fresh 2K request | 889.83 ms | 1,116.52 ms | 851.59 ms |
| Libraries, warm 512 | 63.31 ms | 14.15 ms | 14.39 ms |
| Libraries, warm 2K | 181.40 ms | 24.75 ms | 24.65 ms |
| Libraries, warm 8K | 536.76 ms | 65.69 ms | 66.02 ms |
| SQLAlchemy, warm 512 | 124.92 ms | 63.30 ms | 62.89 ms |
| SQLAlchemy, warm 2K | 241.18 ms | 71.92 ms | 72.79 ms |
| SQLAlchemy, warm 8K | 679.93 ms | 114.70 ms | 113.84 ms |

Values are within-run medians. Fresh trials instantiate a new counter for every
task/arm: 45 observations across 15 library questions and 90 across 30 SQLAlchemy
questions. The reported sum includes constructor, trusted-cache load and first
query. It excludes initial cache compilation, interpreter startup, selector object
construction, garbage collection and cold-OS effects. All occur in one interpreter;
this is not a CLI cold-start benchmark. No concurrent NeuralPack benchmark ran
during the timed phases; other host load was uncontrolled.

Lean initialization medians are 656.18/645.58 ms, versus 922.26/913.49 ms for the
old cache constructor. Against the simpler no-offset control, fresh requests are
faster in all 15 library pairs and 27 of 30 SQLAlchemy pairs. Three SQLAlchemy
requests are slower. The larger workload's modest median improvement must not
be described as a uniform or dramatic first-request gain.

Warm trials use three shuffled repetitions: 405 library and 810 SQLAlchemy
observations. The new constructor does not materially improve warm-query time
relative to the old compact cache; the persisted count algorithm supplies those
savings. A subsequent count audit checks every actual admission using the full
upstream encoder: **2,700 library and 5,400 SQLAlchemy trials**. It reproduces all
135 task/budget selections. Ranking code is reused, so this is an independent
counting oracle, not an independently implemented retrieval engine.

## EMPIRICAL: preparation economics and limits

The library index is 1,216,512 bytes and takes 2,156.14 ms to build, plus 1,004.75 ms
for the measured writer constructor. The SQLAlchemy index is 1,806,336 bytes and
takes 9,197.63 ms to build, plus 1,061.67 ms for the writer constructor. The existing
compact constructor builds both; lean loading must produce the same records.
SQLAlchemy has 5,227 unique source records and one reused duplicate block.

Trusted loading costs about 72 ms on the libraries and 129 ms on SQLAlchemy.
The loader currently reads and validates all source blocks and hydrates all count
records. This is real scale-dependent startup work. Unknown caches still require
full record recompilation before admission; the faster trusted route cannot be
claimed for an unverified external cache.

**EMPIRICAL ESTIMATE:** dividing writer initialization plus cache-building time
by measured mean warm-query savings gives preparation crossovers of 65/21/7
queries for the libraries and 165/61/19 for SQLAlchemy at 512/2K/8K. These are
stage estimates, not measured end-to-end break-even requests. They exclude `.npk`
source compilation, query-counter startup/load and all target-API economics.
There is no dollar-cost or answer-accuracy result in this cycle.

## Keep, discard, next

Keep direct metadata inspection for the experimental compact counter. Discard
the redundant vocabulary copy. Preserve the old constructor as a reproducible
control, rather than silently replacing earlier measurements. There is no reason
to promote a new retrieval winner or a universal tokenizer theorem.

The next system hypothesis is selective loading of already compiled count records
for retrieved candidates, instead of hydrating every source block at startup.
It must retain source/engine/receipt checks and whole-encoder fallback; lazy
loading must not hide query-time compilation. Benchmark it before `.npk`
integration. Separately, retrieval quality remains the unresolved product
bottleneck; none of these timing improvements closes the frozen CRISP gap.

Evidence: `cycle28-lean-{libraries,sqlalchemy}-v1`, with frozen plans, execution
sources, raw fresh/warm rows, selections, exact counts, cache files and input
artifact hashes. `cycle28-lean-summary.json` rechecks pairing, observation counts,
phase sums and evidence hashes before calculating comparisons. No LIVE call was
made; the prior 141-attempt target checkpoint remains incomplete and unchanged.

Canonical verification completes with **1,045 tests passed**, two explicit symlink
skips, and **120/120 mutants killed** by assertions. The two new mutants bypass
the metadata guards and secretly reintroduce vocabulary serialization. All prior
critical query, fallback and dependency mutants are caught. All 343 current Python
source hashes match the tested snapshot. Both profile processes and the test/
mutation runner are terminal; the larger research goal remains active.

Verified checkpoint: `cycle28-lean-checkpoint.zip`, 29,438,221 bytes, 490 files,
SHA `684fdd155ae708cf84ee0824c8b936fed279c405aa4272281ccb3cdac7077e74`.
All member hashes, CRCs and SQLite integrity checks pass. 630,683 decoded/SQLite
pattern checks find no recognized credential match; this is not proof for all
possible secret formats. The previous persistence/update and target checkpoints
are referenced by immutable archive hashes rather than duplicated here.

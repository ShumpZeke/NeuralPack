# Cycle 28: reusable counts survive restarts and source changes

Overall verdict: **PIVOT REQUIRED**. This cycle improves local computation and
storage. It supplies no new retrieval or target-answer advantage over the frozen
CRISP baseline. The implementation is an experimental SQLite cache beside an
unchanged `.npk`; the product format and defaults are not promoted yet. All new
experiments are LOCAL and make zero generative calls.

## What changed

The previous counter required an entire block to be ASCII before using word
barriers. The new rule recognizes complete ASCII words whose immediate neighbors
are ASCII or source boundaries, even if the rest of the block contains Unicode.
Adjacent Unicode letters and combining marks exclude a candidate word. Other
inputs retain the narrower numeric rule or ordinary full counting.

**PROVED UNDER ASSUMPTIONS:** the neighbor test makes a maximal ASCII letter run
maximal for the pinned regex's letter alternatives as well. Keeping complete
first/last eligible runs, including their actual leading prefix pieces, isolates
the intervening pre-token inputs. Unicode inside that fixed region does not alter
the argument. The inspected isolated-split semantics, two-LF join, deterministic
per-piece model, inactive normalization/added tokens and trusted prepared state
remain assumptions. This is not an arbitrary-tokenizer theorem. The asset and
tokenizers 0.22.2 are bound in every plan.

The new rule retains all 405 public selections in its three-arm comparison and
passes all 2,700 actual admission-count checks against upstream full encoding.
Its 2K median is 23.81 ms versus 24.61 ms for the whole-block ASCII restriction
and 176.61 ms for no-offset counting. It replays the original 3,860 cases.
An additional 90,480-case finite stress construction checks Unicode middles,
adjacent marks, complete IDs and compact-count round trips without a mismatch.
That construction is exhaustive only over its declared alphabet and lengths.

The count-only scale comparison also passes all 75 observations. At 250,478
actual context tokens, the whole-block ASCII rule takes 39.66 ms, the new rule
25.84 ms, and the no-offset control 289.42 ms. At 100,303 tokens the corresponding
times are 8.54, 9.00 and 134.09 ms: the relaxation is not faster at every size.
These are counting times, not retrieval latency or answer quality.

## Compact persistent representation

`CompactBoundaryCount` retains only prefix/suffix text and the interior token
count instead of every interior token ID. On the 3,451 unique source texts,
accounted prepared objects fall from 23,274,103 to **4,255,187 bytes**. This is
object accounting, not a process peak-memory claim. The compact type explicitly
does not pretend to provide reconstructed token IDs; its counts are audited
against the real encoder.

`compiled_count_index.py` stores this data in ordinary SQLite tables:

- version, algorithm, tokenizer hash, engine version and parent artifact root;
- file ownership digests and block-to-source-hash references;
- source character lengths, prefix/suffix offsets and interior counts.

The cache does not store source text, token-ID lists, model weights, provider
state or credentials. Records are reused by source-content hash. Updating a
changed file derives only new records and preserves shared records still used
elsewhere. Deleted references are pruned. The parent `.npk` remains the source
of text and provenance. Hash-based identity assumes the digest binds the intended
source; it does not authenticate a publisher.

Two loading paths distinguish trust explicitly. A checksum retained from a
trusted local build/update allows byte-verified reuse. Without that independent
receipt, loading recompiles every record and compares the result before admitting
anything. Taking a checksum from the same unknown cache is not authentication.
Both paths validate format, engine, source ownership, current block mapping and
record bounds. All validation finishes before memory-cache mutation.

The loader reads one bounded byte snapshot and deserializes it into SQLite,
avoiding a separate hash/open race. Updates use a write lock before checking
the existing receipt and retain an exclusive connection lock through checksum
capture. SQLite documents that exclusive locking retains locks beyond a commit;
Python's deserialize API consumes a captured database byte sequence.
[SQLite locking modes](https://www.sqlite.org/pragma.html#pragma_locking_mode),
[Python deserialize](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.deserialize).

The experimental reader requires SQLite deserialize support and caps the index
at 64 MiB. Initial creation may expose an uncommitted empty cache, which readers
reject; it is not atomic publication of a complete multi-file product bundle.
Ordinary cooperative SQLite writers are covered, not arbitrary external file
replacement. The caller must already accept the source `.npk`, fully verifying
external artifacts. Whole-cache hashing and source scanning remain real costs.

## Failures found and repaired

A competing writer initially could commit between our commit and checksum
capture. The returned receipt could then describe a different update than the
reported statistics. A real SQLite regression reproduces this race; retaining
the writer lock through receipt capture fixes it. Before/after XML and the
pre-fix source are preserved. The first version of the race test itself wrapped
unrelated SQLite connections incorrectly; its TypeError is recorded as a harness
failure, not evidence of the product defect. The corrected test fails with the
actual race before the repair.

Tests additionally attack altered bytes, self-declared trust, unsupported
identities/schema, malformed offsets, stale source, partial hydration, deleted
files, shared records, rollback and hidden full recompilation. File IDs may be
replaced during source updates, so side-index metrics are named ownership-row
changes rather than claiming that source files were deleted.

The first storage profile declared 64 MiB prepared caches but used 32 MiB defaults.
It remains preserved with a protocol-nonconformance note and is excluded from
the declared-configuration results. The replacement v2 passes the limit explicitly
to every comparison arm and asserts the observed configuration. No records were
evicted in either run. Auxiliary writer/verification instances are separately
recorded and are not warm-query comparison arms.

## New post-fix measurements

The v2 cache contains **3,451 records for 3,513 blocks in 153 files**, occupies
**1,216,512 bytes**, and builds in **2,132.18 ms**, excluding tokenizer construction.
The same public lexical selector, 60 candidates, 15 inspected questions, three
caps and three repetitions produce 540 matched selections. Every complete
selection agrees apart from latency, and all final upstream counts fit the cap.

| Exact context cap | No-offset control | ID-list preparation | Compact preparation | Loaded compact cache |
| --- | ---: | ---: | ---: | ---: |
| 512 | 62.15 ms | 13.30 ms | 12.98 ms | 13.26 ms |
| 2,048 | 176.22 ms | 24.72 ms | 25.73 ms | 23.82 ms |
| 8,192 | 547.10 ms | 67.00 ms | 66.71 ms | 65.03 ms |

These are within-run medians. All 135 loaded-cache pairs beat the no-offset
control, with ratios of medians 4.69x, 7.40x and 8.41x. A subsequent audit checks
all 2,700 individual admission counts with the upstream encoder and reproduces
the 540 outputs. Ranking code is reused; this is independent counting validation,
not an independently implemented retrieval algorithm. Per-request corpus,
available and selected tokens are recorded separately. Prompt tokens are N/A
because no target-model envelope is involved.

Loading the trusted cache takes **73.38 ms** versus **2,145.44 ms** to prepare
compact records again. Unknown-cache verification takes **2,152.15 ms**, as it
recomputes the records. Those numbers exclude constructor cost. On a fresh
counter, initialization plus setup plus the first 2K query costs **1,022.77 ms**
for the loaded cache versus **843.41 ms** for no-offset counting. Thus a single
fresh-counter request is still slower in this measurement. Reusing an initialized
instance is important. These are not cold-OS or fresh-interpreter measurements;
initial cache compilation and API dollars are also excluded from that comparison.

Real source-update trials append explicitly synthetic module assignments to
verified public source copies and never execute the altered modules. Three repeats
are measured per scenario. Each incremental cache matches a full rebuild logically,
each updated `.npk` passes full root verification, and its entire assembled context
count agrees upstream. Spies verify the actual number of region compilations.

| Source files changed | Actual file fraction | Cache update | Full cache rebuild | `.npk` update + cache update | `.npk` update + full cache rebuild |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.65% | 21.20 ms | 2,251.21 ms | 820.19 ms | 3,067.22 ms |
| 2 | 1.31% | 21.82 ms | 2,350.52 ms | 838.38 ms | 3,166.54 ms |
| 16 | 10.46% | 50.60 ms | 2,245.12 ms | 1,246.85 ms | 3,426.69 ms |

All are medians of measured phases or measured phase sums. The scenarios compile
1, 2 and 18 count records while reusing 4, 8 and 339 records inside changed files.
The roughly 106x one-file cache-only improvement is not a 106x product speedup.
Source scanning, `.npk` sealing, copy setup, counter initialization, source changes,
cache load and validation are separately recorded or explicitly excluded. The
underlying `.npk` update remains about 0.8–1.2 seconds here. CPU intervals smaller
than the host's timing resolution can be reported as zero; this does not mean
zero work.

## Current validation and next hypothesis

The full canonical suite passes **1,031 tests**, with two explicit symlink skips.
All **118 mutants are killed**, including the six new count-cache/barrier attacks
and all previous critical mutants. All 341 Python source hashes match. No LIVE
call was made in this cycle; the earlier 141-attempt target checkpoint is unchanged
and incomplete. Accuracy remains N/A where answers are missing.

Keep the compact persistent prototype and delimited-word rule for further
integration work. Discard full cache recompilation for trusted unchanged records,
but retain explicit full verification for unknown caches. Do not promote a generic
tokenizer theorem, answer-quality claim or default `.npk` schema change.

The next immediate bottleneck is tokenizer initialization. A six-observation
constructor profile finds an extra full tokenizer JSON serialization and a second
JSON decode in the prepared counter. The serialization alone takes roughly
137–145 ms under cProfile; compact construction has median 952.77 ms versus
672.80 ms for the no-offset counter. Profiling adds overhead. Removing that
redundant work while preserving every added-token/normalization guard is the next
testable hypothesis. Then validate on the larger SQLAlchemy source corpus and
evaluate integration as optional versioned `.npk` data, keeping provider-specific
profiles out of the mandatory core representation. Retrieval and real answer
quality still need stronger evidence; faster counting does not close that gap.

Evidence directories: `cycle28-delimited-{attack,profile,scale,stress}-v1`,
`cycle28-count-cache-profile-v2`, `cycle28-count-cache-updates-v1` and
`cycle28-counter-startup-v1`. Reports: `cycle28-{delimited,persisted}-admission-audit.json`,
`cycle28-persist-summary.json`, `cycle28-persist-canonical-full.xml` and
`cycle28-persist-canonical-mutations.json`. V1 storage timings remain explicitly
nonconforming rather than being silently replaced.

Verified checkpoint: `cycle28-persist-checkpoint.zip`, 73,826,824 bytes, 2,393
files, SHA `8a762d4057838d06ae214971818e133514f378bdbc40e7fbad35a5ff64ffef93`.
All member hashes/CRCs and SQLite integrity checks pass; 1,361,462 decoded/SQLite
pattern checks find no recognized credential match. This is pattern screening,
not proof for all possible secret formats. Earlier unchanged target payloads
remain in the separately hashed counter checkpoint referenced by this archive.

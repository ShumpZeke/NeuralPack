# Cycle 28: restrict the boundary argument instead of paying for a full check

Overall product verdict: **PIVOT REQUIRED**. These are LOCAL tokenizer and
selector experiments, with zero generative optimization calls. They do not
improve retrieval or establish better answers than CRISP. Keep the restricted
ASCII-word counter as a research candidate; it is not a default or persisted
`.npk` feature.

## What failed

The first challenger compares the entire assembled pre-token sequence with a
proposed partition before using compiled counts. It removes the original
boundary-stability assumption for accepted partitions, conditional on correct
compiled counts and per-piece model semantics. It passes all 3,860 replayed
ID/count attacks and all 2,700 actual admission-count checks, but loses on cost.

| Exact cap | No-offset baseline | Whole-piece check |
| --- | ---: | ---: |
| 512 | 60.22 ms | 77.31 ms |
| 2,048 | 176.09 ms | 228.96 ms |
| 8,192 | 540.42 ms | 736.11 ms |

These are median public-selector times within the same randomized-order run.
Discard this challenger as a runtime route; retain its implementation and
failure evidence for research. No storage implementation was built for it.

Attacking its new code found two real defects before profiling. A BPE vocabulary
containing only `a` silently tokenizes `z` into zero IDs; the challenger initially
accepted that count despite the existing public counter rejecting it. It now
rejects non-whitespace input with zero tokens. Separately, splitting `zaz` around
its known `a` could abort preparation because a boundary fragment was unknown.
That optional decomposition now falls back to full counting. Before/after XML
reports preserve both reproduced failures. Permanent tests and mutation checks
cover the zero-count acceptance, gate bypass and query-time compilation.

## Narrower barriers

All experiments bind the exact 17,077,484-byte tokenizer asset with SHA-256
`623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7`,
tokenizers 0.22.2 and captured Python sources. This is not an inferred model
match. Padding and truncation are off, and BPE dropout is rejected.

**PROVED UNDER ASSUMPTIONS — numeric barrier.** In the pinned split expression,
the number alternative consumes one character. The letter alternatives exclude
numbers from their optional prefix; punctuation and whitespace alternatives
cannot consume digits. An ASCII digit therefore separates neighboring matches.
Keeping the first and last such pieces in the freshly encoded boundaries leaves
the intervening piece inputs independent of exterior text. This assumes the
inspected left-to-right isolated split semantics, no active added token or
normalization, a fixed deterministic per-piece model and no token-changing
postprocessing.

Digit-only reuse covers just 974 of 3,451 unique source texts and caches 170,734
interior tokens. It reduces 2K median query time from 176.32 to 134.66 ms, with
1.587 seconds of preparation and 11,915,341 accounted Python-object bytes.
Keep it as a conservative subcase, not the main speed candidate.

**PROVED UNDER ASSUMPTIONS — complete ASCII-word barrier.** Restrict a source
block to ASCII and consider its maximal `[A-Za-z]+` runs. In the pinned regex,
only the two letter alternatives consume these characters. Each stays inside
one such run, with at most one leading non-letter/non-number character; the
other alternatives cannot cross a letter run. A run may contain several case
pieces, so cutting inside it is excluded. Keeping the whole first run on the
left and the whole last run, including its actual optional prefix, on the
right prevents exterior text from changing intervening matches. The public
join is two LF characters, which cannot extend a letter run. Whitespace
lookahead near either interior cut sees fixed source letters. Under the same
pipeline assumptions, the model receives the same interior pieces and IDs.

The implementation checks contiguous source offsets and full isolated ID
reconstruction during preparation. It uses complete word boundaries only on
ASCII blocks; other blocks use the numeric rule. Missing, rejected or evicted
records use the upstream encoder. Added-token settings that could cross the LF
join disable preparation. These arguments do not cover an arbitrary tokenizer,
changed engine semantics, altered separator, mutable model or forged cache.

The upstream implementation applies its model to each pre-tokenized piece;
the inspected ByteLevel postprocessor adjusts offsets and sequence metadata,
without adding token IDs. These are the relevant pipeline assumptions, not
an inference from matching benchmark counts.
[Tokenizer implementation](https://raw.githubusercontent.com/huggingface/tokenizers/v0.22.2/tokenizers/src/tokenizer/mod.rs),
[ByteLevel implementation](https://raw.githubusercontent.com/huggingface/tokenizers/v0.22.2/tokenizers/src/pre_tokenizers/byte_level.rs).

The original more general alphanumeric-boundary claim remains **CONJECTURE**.
No universal tokenizer decomposition or evidence-sufficiency theorem is claimed.

## What improved

The ASCII-word candidate reuses interiors in 3,426 of 3,451 unique texts and
caches 495,649 interior tokens. This is a reuse measurement, not available
context size. Each profiled request has the same actual available corpus;
the raw rows record its whole-assembly count, selected count and cap separately.
Baseline prompt tokens are N/A because there is no target-model envelope.

| Exact cap | No-offset baseline | Original prototype | Restricted word candidate |
| --- | ---: | ---: | ---: |
| 512 | 63.39 ms | 14.07 ms | 13.35 ms |
| 2,048 | 182.49 ms | 25.57 ms | 26.62 ms |
| 8,192 | 550.75 ms | 66.83 ms | 70.20 ms |

These are medians from 15 inspected behavior queries, three caps, three
randomized repetitions and the same public lexical selector with 60 candidates.
All 405 complete selections agree apart from latency. All 135 paired timings
beat the stronger no-offset control. Ratios of medians are 4.75x, 6.85x and
7.85x. This is comparable speed with a narrower argument, not a new speed win
over the original prototype. Timings from different challenger runs must not
be treated as a causal comparison; each includes its own controls.

Preparing all 3,513 blocks costs 2,051.74 ms wall and 2,046.875 ms CPU. The cache
accounts for 22,199,408 bytes of Python objects. RSS snapshots rise from
220,561,408 to 243,429,376 bytes; they are not a peak-memory bound. The measured
mean savings repay this preparation phase after about 43, 14 or five queries,
depending on cap. This excludes tokenizer construction, persistence, source
updates, disk, target inference and API dollars. Query never compiles a miss.

No other NeuralPack benchmark ran during these profiles; general host background
activity was uncontrolled. This does not establish production latency.

## Attacks and independent count checks

Each of the three challengers passes the original 3,860 frozen synthetic/source
cases. These are repeated cases, not 11,580 independent task questions. The
restricted word candidate additionally passes 44,816 combinations covering every
string of length zero through four over a declared seven-character alphabet,
wrapped by complete words and four left/right exteriors. This is exhaustive only
over that finite construction. All actual token IDs and counts agree upstream.

For every challenger, a subsequent audit checks all 2,700 actual admission
trials against upstream whole-text encoding and reproduces all 405 profiled
outputs. This independently checks counting; public ranking itself is reused.
Final budget reconciliation also remains the existing upstream implementation.

The canonical suite passes **1,011 tests with two explicit symlink skips**.
All **112 mutants are killed**, including all previous critical mutants and
five new defects covering the restricted barriers and whole-piece checker.
All 336 current Python source hashes match the mutation snapshot. These checks
establish covered contracts, not answer quality or universal correctness.

## Keep, discard and next hypothesis

An additional count-only scale sweep checks all 50 observations against the
upstream count. These are fixed prefixes of actual source blocks, not query
latency or cumulative context-size claims:

| Actual assembled context | No-offset count | Restricted-word count |
| --- | ---: | ---: |
| 2,113 tokens | 0.951 ms | 0.528 ms |
| 25,185 tokens | 34.34 ms | 2.46 ms |
| 50,212 tokens | 67.93 ms | 4.26 ms |
| 100,303 tokens | 144.15 ms | 8.95 ms |
| 250,478 tokens | 299.55 ms | 50.23 ms |

The 250K result exposes a remaining limitation: a single non-ASCII character
forces an entire block to the weaker numeric rule. Component accounting finds
41 non-ASCII blocks at that prefix, including Rich's emoji and spinner tables.
They account for 38,306 of 47,452 standalone boundary tokens still requiring
encoding. These component sums are not the assembled context count and are
not a causal timing breakdown. At 100K, only one source block is non-ASCII.
The original prototype's 250K result must not be substituted for this new
candidate's slower 50.23 ms measurement.

Keep the restricted word candidate for compact persistence and changed-block
invalidation research, with the numerical rule as its non-ASCII subcase. Discard
the whole-piece runtime gate because it costs more than the work it saves.
Do not promote either old or new prototype to product default yet.

The next immediate hypothesis is to recognize safely delimited ASCII-word
barriers inside a block containing Unicode, instead of requiring the entire
block to be ASCII. Neighboring combining marks and non-ASCII letters can extend
a word, so the existing proof cannot simply be assumed for that relaxation.
Keep it **CONJECTURE** until the delimiter rule is derived, attacked and measured.

Then test whether a versioned, source/tokenizer-bound compiled
representation can retain this speed across process restarts and single-file
updates at a reasonable disk and verification cost. Benchmark trusted local
reuse separately from verification of an external artifact; a self-declared
hash cannot authenticate a maliciously rewritten token cache. Test the current
candidate on the larger SQLAlchemy corpus and additional tokenizer pipelines
before considering broader support. Then combine only justified counting and
seed improvements for matched-budget answer testing. Faster counting alone
does not close CRISP's reproduced retrieval lead.

The original target trial is terminal at 141 attempts: 94 answers, 46 HTTP 503s
and one HTTP 429. The latest three never-attempted 2K requests all returned 503
after a cooldown, triggering the configured pause. No completed request was
retried. The independent report verifies all 94 successful prompt counts again.
Seven first-stage payloads remain never attempted; answer comparisons remain
incomplete and their accuracy stays N/A.

Reproducible evidence: `cycle28-{verified,digit,ascii}-{attack,profile}-v1`,
`cycle28-ascii-stress-v1`, `cycle28-ascii-scale-v1`,
`cycle28-ascii-scale-breakdown.json`, the three `cycle28-*-admission-audit.json` reports,
`cycle28-counter-summary.json`, `cycle28-counter-canonical-full.xml`,
`cycle28-counter-canonical-mutations.json` and `cycle28-library-answer-141.json`.

Verified checkpoint: `cycle28-counter-checkpoint.zip`, 18,048,862 bytes,
1,254 files, SHA-256
`43e0ab613369e3ef9542ec1b7bfe83209657995659b87ac8f652a5d3b1e2efa9`.
Every member hash and ZIP CRC passes. The archive contains these completed
experiments, current code/tests, input pack and tokenizer, failures, count audits
and the quiescent 141-attempt target checkpoint. It records 122,839 decoded or
SQLite pattern checks with no recognized credential match; this is not proof
against every secret format. Earlier retrieval evidence remains in separately
hashed checkpoints. The broader goal and answer evaluation remain open.

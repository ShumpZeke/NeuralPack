# Precompile token interiors; count joins locally

Status: **promising LOCAL performance prototype, not a default runtime change**.
Overall product verdict remains PIVOT REQUIRED: retrieval differentiation and
broad answer quality are not established. Measurements below are EMPIRICAL.

The previous piece cache still ran the pre-tokenizer over the entire assembled
context on every admission trial and lost to the upstream no-offset counter.
The new hypothesis moves reusable segmentation and interior tokenization into
an explicit preparation step. Query time encodes only the portions around joins.
It changes no selected source text and makes zero generative calls.

## Mechanism and limits

CONJECTURE: for the inspected pinned tokenizer pipeline, source portions between
the first and last pre-tokenizer pieces containing an alphanumeric character
remain stable when blocks are joined with two newlines. The experiment stores
their token IDs and retains the outer source portions for fresh joint encoding.
Passing finite tests does not prove this for all Unicode strings, engine versions
or tokenizers. No universal decomposition or additivity theorem is claimed.

The prototype checks each isolated block against full upstream encoding during
preparation. Missing/evicted blocks, recognized added tokens and unsupported
assets fall back to ordinary whole-context counting. Added tokens spanning the
separator disable the hypothesis. Query calls do not prepare missing blocks.
The ordinary `count()` method and the public selector's final whole-context
reconciliation remain upstream implementations.

Eligibility is restricted to the captured tokenizer JSON, SHA-256
`623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7`.
Experiments use CPython 3.12.10 and tokenizers 0.22.2. Other engine versions are
unvalidated even if they accept the same asset. This is tokenizer data processing;
no model weights, provider key or remote Python are loaded.

The prepared representation is currently **in memory**, using a 64 MiB budget
in the experiments. It is not yet a persisted `.npk` feature. It stores token
IDs for differential inspection; a compact persisted representation, integrity
rules and incremental invalidation still require design and measurement.

## Attacks and verification

The frozen attack plan `cycle28-boundary-attack-v1` checks 3,860 cases: 3,700
synthetic combinations and 160 combinations of real public-source blocks.
Every token-ID sequence and count matches the upstream whole-text tokenizer.
The synthetic cases include whitespace runs, punctuation, Unicode marks,
empty blocks and all 1,000 added tokens. There are 1,000 preparation rejections
for added-token inputs and 2,000 fallback invocations across separate ID/count
checks. Fallbacks are reported, not silently counted as optimized paths.

Eight permanent tests use a real tiny trained BPE pipeline, independent of the
downloaded artifact. They test joins, empty inputs, bounded cache eviction,
unsupported assets, cross-separator added tokens and absence of query-time
compilation. The synthetic fixture explicitly opts into its test hash; the
product does not accept arbitrary assets as equivalent to the pinned pipeline.

The full canonical suite passes **1,001 tests with two explicit symlink skips**.
All **107 mutants are killed**, including naive independent-block addition and
compilation during a query. All 331 current Python source hashes are checked.
Reports: `cycle28-boundary-canonical-full.xml` and
`cycle28-boundary-canonical-mutations.json`.

## Public selector measurement

`cycle28-boundary-profile-v1` freezes 15 inspected behavior queries, three caps,
three randomized-order repetitions and three counters. It uses the same public
lexical ranking, 60 candidates and source blocks; only the candidate admission
counter differs. Every arm starts with an empty whole-text cache. Prepared block
interiors persist across queries. All 405 output records agree on the complete
selection apart from measured latency, and every final count fits the same cap.

| Exact context cap | Ordinary counter | Stronger no-offset counter | Prepared boundaries |
| --- | ---: | ---: | ---: |
| 512 | 73.25 ms | 64.24 ms | 14.23 ms |
| 2,048 | 214.16 ms | 177.28 ms | 26.26 ms |
| 8,192 | 687.69 ms | 553.96 ms | 67.47 ms |

These are median local query times in this run, under concurrent independent
audit load. Against the stronger counter, ratios of medians are 4.52x, 6.75x
and 8.21x. The 10.19x ratio at 8K applies only to the slower ordinary counter;
it is not the strong-baseline result. All 45 measured pairs per cap were faster.
This does not establish uncontended production latency or faster CRISP retrieval.

A subsequent check verifies **all 2,700 actual admission counts** against the
upstream full-text tokenizer, rather than checking only final contexts after
reconciliation. It reproduces the 405 profiled observations across 45 distinct
query/budget cells. This reuses public ranking; it is an independent count check,
not a separately implemented retrieval algorithm or answer-quality audit.
`cycle28-boundary-admission-audit.json` records per-cell available/corpus size
as 558,878 tokens, bound to the earlier independent source-corpus audit. There
is no target-model prompt envelope in this local trial, so baseline prompt
tokens are explicitly N/A.

Preparing all 3,513 blocks (3,451 unique texts) takes 2,335.04 ms wall time and
2,312.5 ms process CPU. No source blocks are evicted or rejected. Accounted
prepared Python objects occupy 23,440,731 bytes; observed process RSS increases
from 192,475,136 to 206,897,152 bytes. Those are different measurements: RSS
snapshots include allocator reuse and are not a peak-memory bound.

Using this run's mean savings, the extra preparation phase is repaid after
approximately 47, 16 or five queries at the three caps against the stronger
counter. This is a conditional local-compute calculation. It excludes tokenizer
construction, persistence I/O, source updates, storage and API dollars; it is
not a complete first-query or product economics claim.

## Counting-only scale check

Separate fixed prefixes of actual source blocks give these upstream-verified
whole-context sizes. Approximate requested sizes are never substituted for
the measured counts. Five randomized-order repeats are used per cell.

| Actual context tokens | Source blocks | No-offset count | Prepared-boundary count |
| --- | ---: | ---: | ---: |
| 2,113 | 2 | 0.750 ms | 0.043 ms |
| 25,185 | 175 | 38.18 ms | 2.03 ms |
| 50,212 | 328 | 77.17 ms | 4.01 ms |
| 100,303 | 767 | 157.08 ms | 8.39 ms |
| 250,478 | 1,295 | 321.43 ms | 16.79 ms |

These are **counting-only** times with prepared interiors, not retrieval or
target-answer latency. All 50 counts match upstream. The run is
`cycle28-boundary-scale-v1`. No optimizer uses a generative model.

## Keep, discard and next decision

Keep the prototype as a performance challenger. Discard any claim that it is
already a portable `.npk` feature, universally exact, or evidence of better
answers. Its current memory representation and one inspected tokenizer are
material limits. The product default remains unchanged.

Next: attack other corpora and Unicode boundaries, validate a compact persisted
representation with source/tokenizer integrity and changed-block invalidation,
and measure startup, incremental cost and memory. Couple a successful counter
with the strongest justified seed system, then repeat matched-budget answer
evaluation. The concurrent length-penalty audit remains a separate retrieval
decision; a counting speedup cannot close a seed-quality gap by itself.

The verified checkpoint is `cycle28-boundary-checkpoint.zip`: 63,604,927 bytes,
8,175 files, SHA-256
`b2298837cb64976e4ea013cf226f99763d0fc9fbcc5c589ede81744c9308f976`.
All member hashes and ZIP CRCs pass. It includes the completed length audit,
all three boundary experiments, the admission-count audit, current source/test
snapshots and the 138-attempt LIVE checkpoint. Its 319,437 decoded/SQLite pattern
checks find no recognized credential match; this is not proof of absence of
all possible secret formats. Overall goal and product validation remain open.

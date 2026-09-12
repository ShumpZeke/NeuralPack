# Cycle 28: exact counting costs and rejected accelerators

The default product is unchanged by these experiments. They test lower-cost
execution of the same selection decisions, not better retrieval or answers.
Overall product verdict remains **PIVOT REQUIRED**. All measurements below are
**EMPIRICAL** and use the pinned local NIM tokenizer; no optimizer makes a
generative call.

## Cache smaller pieces: reject

The first hypothesis was that caching BPE counts for repeated smaller pieces
would save work across candidate assemblies. The prototype recomputes the real
pre-tokenizer splits on the whole assembled text, then caches model counts for
those transformed pieces. It does not add independently counted source blocks.
Normalizers, unsupported processors and possible added-token matches fall back
to the ordinary encoder. A permanent synthetic counterexample shows why the
added-token gate matters: `a b` can be a single added token while naive piece
counts return two.

On 6,903 differential inputs, all token IDs and counts matched the ordinary
encoder. There were 3,000 fallback cases. All 540 profiled selections matched
the full public output, including evidence, query, risk and fallback status.
The workload was 15 inspected library questions, three exact budgets and three
paired repetitions. Count caches were cleared before every query; tokenizers
were already loaded and host background load was uncontrolled.

| Exact context cap | Ordinary median | No-offset median | Piece counts without cache | Piece counts with cache |
|---|---:|---:|---:|---:|
| 512 | 59.26 ms | 51.20 ms | 86.50 ms | 68.46 ms |
| 2,048 | 158.31 ms | 131.62 ms | 246.20 ms | 185.91 ms |
| 8,192 | 494.55 ms | 394.77 ms | 794.53 ms | 578.76 ms |

The cached prototype is slower than the ordinary encoder, and slower still
relative to the simpler no-offset API. Reject product integration. Its frozen
implementation, generated adversarial cases and results remain research evidence
under `cycle28-piece-tokenizer-v1`. The upstream BPE already has a word cache;
duplicating work across Python/Rust is a plausible explanation, not a measured
causal attribution. See the [BPE API](https://huggingface.co/docs/tokenizers/api/models)
and [pre-tokenizer API](https://huggingface.co/docs/tokenizers/api/pre-tokenizers).

The run also contains separate counting-only profiles on progressively larger
literal source prefixes. Their measured token counts must be reported instead
of the requested approximate size labels. Those profiles are not query latency.

| Actual input tokens | Ordinary count median | No-offset count median | Cached piece median |
|---|---:|---:|---:|
| 3,343 | 2.70 ms | 2.23 ms | 3.09 ms |
| 23,350 | 28.89 ms | 24.35 ms | 34.20 ms |
| 44,888 | 59.65 ms | 49.15 ms | 69.30 ms |
| 90,818 | 127.23 ms | 98.94 ms | 145.00 ms |
| 281,550 | 367.71 ms | 271.44 ms | 424.16 ms |

## Batch exact candidate counts: a tradeoff

The second hypothesis is simpler: after rejecting a candidate, count several
upcoming candidate assemblies in a local batch. Preserve their original order.
If a candidate is accepted, its changed prefix gets a new exact-text cache key.
Unused speculative work may be wasted but cannot supply the count of a
different assembled context.

The research adapter changes only the iterator in the public selector's
admission loop, through a checked AST transformation. Ranking, admission checks,
evidence construction, risk, query preservation and final budget reconciliation
remain the same statements. The adapter refuses a non-unique admission loop.
Batch size and total candidate characters are bounded. The prototype does not
change global thread settings from inside the product; the benchmark explicitly
sets its own process's Rayon thread count before loading tokenizers.

The four-thread run completed 675 selections with identical public outputs and
independently recounted final tokens. Medians at a 2,048-token cap:

| Method | Wall time | Process CPU time |
|---|---:|---:|
| Ordinary encoder | 152.46 ms | 156.25 ms |
| No-offset encoder | 128.62 ms | 125.00 ms |
| Batch up to 4 | 77.22 ms | 203.13 ms |
| Batch up to 8 | 76.25 ms | 218.75 ms |
| Batch up to 16 | 76.55 ms | 203.13 ms |

At an 8,192-token cap, batch-8 took 283.74 ms wall / 500.00 ms CPU, versus
384.28 ms / 375.00 ms for no-offset sequential counting. Larger batches were
also constrained by the 131,072-character batch cap. These observations do not
support a universal best batch size. Reduced wall time does not imply reduced
local compute cost. No verified dollar saving follows from these numbers.

The four-thread plan and raw records are under `cycle28-batch-tokenizer-4t-v1`.
A separate one-thread control completed another 675 identical selections. At
2K, no-offset sequential counting took 129.52 ms, while batches of 4/8/16 took
138.03/142.55/153.32 ms. At 8K those methods took 390.39 ms and
412.22/414.91/415.96 ms. Batching loses when it cannot spend extra CPU cores.
Keep it as an explicit latency/CPU tradeoff, not the default efficiency path.
These are matching inspected questions and one host, not a cross-hardware
deployment claim. The one-thread timing run overlapped the paced network answer
executor, whose small local request/record overhead is part of uncontrolled host
load; no other heavy benchmark or test suite ran alongside the timing studies.
No batching option is promoted to the runtime.

## What can actually be proved

**PROVED UNDER ASSUMPTIONS — exact speculative counts preserve greedy decisions.**
Let a fixed ordered list of candidates be admitted one at a time according to
`T(join(current_evidence, candidate)) <= budget`. Assume `T` is a deterministic,
total function, source text is immutable during selection, the order is
unchanged, and cached values are exact counts keyed by the full joined text.
At the first candidate both executions have the same evidence and count. If
they agree through candidate i, they have the same evidence before candidate
i+1 and test the same string with the same count. They therefore make the same
decision. Induction establishes identical final evidence. Counts need not be
additive or monotone. Speculating about unused strings does not alter this
argument.

This proposition establishes neither evidence sufficiency nor speed, and it
assumes counting succeeds. The implementation is tested rather than formally
verified. Random nonadditive-count tests attack candidate order and changing
prefixes; real tokenizer tests cover added tokens and exact keys. Performance
must still earn the extra work and concurrency complexity.

## Next decision

Discard the Python piece cache as a product candidate. Keep the simpler
no-offset API as the low-complexity speed challenger, and evaluate batching as
an explicit latency/CPU tradeoff. Do not spend more
architectural complexity chasing a timing headline when stronger seed ranking
and actual answer validation remain the more important open problems.

The original project interpreter is now launchable through the approved local
execution route. The full suite passes **931 tests with two symlink-related
skips** on CPython 3.12.10, including the 20 previously skipped version-pinned
oracle checks. This resolves that environment gap without changing their oracle
definitions or the separately frozen CPython 3.12.14 LIVE behavior plan.
All **91 mutation checks** also catch their planted defects on the canonical
interpreter. New tripwires attack stale-prefix reuse, reordered candidates and
the added-token bypass. The baseline binds all Python code in the product,
benchmarks and tests; results are in `cycle28-counting-mutations.json`.

The completed counting study and 100-attempt answer checkpoint are archived in
`experiments/results/cycle28-counting-checkpoint.zip`: 31,490,164 bytes, 4,634
files, SHA-256 `c935f266789f33fc89790af97de3f0d297a452e14fa3806eef0d4f1a0b5f7636`.
The archive gate checked all 1,890 profile rows against the complete matrix,
independently recounted 45 distinct contexts and checked 611 literal source
items. Every member was read back against its hash and ZIP CRCs passed. There
were 126,219 decoded/SQLite pattern checks with no recognized credential match.
The first archive attempt failed before writing an archive because `run_path`
supplied a relative script path. Its source/failure are retained; normalization
now has a regression assertion for relative and absolute references. This
archive explicitly leaves the wider research goal open.

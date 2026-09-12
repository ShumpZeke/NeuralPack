# Cycle 28: local token budgets and the cost of correctness

Status: **PIVOT REQUIRED** for the retrieval approach. This is a repair and
performance checkpoint, not evidence of better answers or completion of cycle 28.
All measurements below are **EMPIRICAL**, LOCAL, with zero generative calls.

## Repair

The runtime accepts a caller-supplied local tokenizer JSON. It hashes the captured
asset, disables truncation and padding, rejects stochastic BPE dropout, and counts
the complete assembled context. Final evidence edits get another exact budget
check. Empty selections still require fallback. The original query survives
unchanged; applications keep system instructions outside retrieved source text.
Target-model names do not trigger inferred codecs, downloads, API calls or prices.

Counts cover context and default `\n\n` separators, excluding query, system,
chat template and caller formatting. Exact selected counts are never divided by
estimated corpus counts: `available_tokens` and `reduction_pct` are null in exact
mode, with the old estimate in a separate field. Sufficiency remains unverified.
Without a tokenizer, the dependency-free path retains its labeled character
estimate and running character total. That estimate is not a true BPE token cap.

## Audited experiment

Every arm uses the same freshly compiled, method-chunked 155-file frozen
rich/Jinja2/Werkzeug corpus: **558,878 available source tokens per request** under
the pinned NVIDIA tokenizer. The 246 inspected tasks contain 207 distinct
questions. Three budgets and four arms produce 2,484 selections. A separate
profile has 12 deterministically sampled questions, three shuffled repetitions,
and cold-count-cache / immediately repeated requests: 864 observations.

An independent script recounted every context and checked **44,158 source items**
against literal file spans. All 621 cached-exact contexts matched uncached exact
contexts byte for byte. Character estimates overran on 61/621 distinct
question/budget combinations. Neither exact arm overran.

| Budget | Estimate: needle hits | Exact: needle hits | Additive: needle hits |
|---:|---:|---:|---:|
| 512 | 113/246 | 120/246 | 119/246 |
| 2,048 | 148/246 | 148/246 | 149/246 |
| 8,192 | 180/246 | 183/246 | 183/246 |

These are attributed source-needle counts, not answer accuracy. The estimate
column includes overruns and is not an eligible matched-budget champion. This
tokenizer differs from the earlier CRISP `cl100k_base` comparison; the caps and
numbers cannot be substituted into that comparison.

## Speed and the discarded shortcut

Median query milliseconds, excluding tokenizer construction:

| Budget | Exact, cold | Cached exact, cold | Cached exact, immediate repeat | Additive, cold |
|---:|---:|---:|---:|---:|
| 512 | 138.87 | 132.53 | 8.41 | 50.13 |
| 2,048 | 363.72 | 359.26 | 9.29 | 59.92 |
| 8,192 | 1,091.69 | 1,080.75 | 10.12 | 78.55 |

Caching barely improves a new request. It reduces repeated counting when the
same text returns. Immediate repeats do not represent arbitrary new questions.
Host load was uncontrolled; this agent ran no overlapping benchmarks, tests or
LIVE requests during measurement.

The additive challenger sums standalone passage/separator counts, then performs
exact final reconciliation. It changed 42, 78 and 144 contexts at the three caps.
At 512 it lost `B-f8718f3e0c`, about `rich.progress.Task.percentage`; at 2,048 it
gained `C-2d02e03405`, one of the repeated Jinja2 `Impossible` questions. No other
needle outcomes changed. One gain is not general quality improvement. Arithmetic
addition is not equivalent to counting joined text; this shortcut stays out of
the product admission rule.

A permanent synthetic real-BPE counterexample also demonstrates the mechanism:
`a`, the separator, and `b` cost three tokens separately but two when joined.
The additive rule discards `b` at a two-token cap even though the complete text
fits. This is a representation counterexample, not a claim about all BPE codecs.

The product cache uses exact text keys, a 4 MiB text-plus-entry allowance and
4,096-entry ceiling, with serialized concurrent access. That allowance is not a
whole-process RSS claim. `cache_bytes=0` disables it. Each tokenizer owns its cache;
different text cannot reuse a stale count after source updates. Failed counts are
never cached. Separate CLI invocations do not share it: reuse needs a retained
tokenizer instance. The product timing/equivalence gate is recorded separately.

The subsequent product gate matched 1,441 distinct saved context counts, all
621 default selections and 216 sampled exact selections. Its cold medians at
512/2,048/8,192 tokens were 52.99/141.54/447.18 ms, versus 4.15/4.33/4.75 ms
for immediate repeats. This separate run was faster overall; uncontrolled host
conditions prevent attributing that cold difference to the implementation change.
One tokenizer construction took 695.33 ms. Process RSS snapshots increased
from 112,209,920 to 158,543,872 bytes; these are not isolated peak allocations.

**PROVED UNDER ASSUMPTIONS:** with a deterministic tokenizer and fixed state,
memoizing by exact input strings preserves its count function. The cache starts
empty. Insertions store that function's result; hits return it; eviction causes
recomputation. This proves neither evidence sufficiency nor a speed guarantee.

## Validation and remaining work

The product suite passed **831 tests with 22 skips** on bundled CPython 3.12.14.
Twenty executable-oracle tests require CPython 3.12.10; two skips concern symlink
permissions. All **84 mutation checks were killed**, including the old dependency,
query and fallback mutants. The original 83-check run and the added BPE-boundary
mutant used identical product source hashes; both batches are preserved.

The project interpreter cannot launch under ordinary workspace permissions.
Automatic approval review timed out twice before launching the canonical full
suite, without a substantive safety rejection. The twenty version-pinned checks
remain pending, not passed. Earlier failures remain in separate XML files: a CLI
test wrongly expected exit 0 for fallback (corrected to 1), and alternate-runtime
attempts needed workspace-local temp files and explicit child package/cache paths.
No product expectation was weakened to resolve those environment errors.

Next hypotheses: preserve explicitly named code identifiers such as `get` and
`set`; index path and qualified-name information; test strong lexical/structural
seeds on executable answer questions. Exact budgeting does not close the CRISP
retrieval gap. Cold exact counting remains a measured bottleneck; a cheaper exact
implementation is preferable to silently assuming additivity.

## Evidence

- `benchmarks/local_budget_eval.py`: four-arm experiment.
- `benchmarks/local_budget_report.py`: independent count/span audit.
- `benchmarks/local_budget_gate.py`: product-versus-captured-output gate.
- `experiments/results/cycle28-local-budget-audit.json`: audited metrics and
  individual additive wins/losses.
- `experiments/runs/packs/cycle28-local-budget-v2`: raw contexts, artifact,
  source capture, plan and observations.
- `experiments/results/cycle28-budget-acceptance-sandbox.xml`: final executed suite.
- `experiments/results/cycle28-exact-budget-mutations.json`: 83 killed mutants.
- `experiments/results/cycle28-additive-mutation.json`: the added boundary mutant.
- `experiments/runs/packs/cycle28-local-budget-product-v1/report.json`: final
  product equivalence, initialization, memory snapshots and latency measurements.

Tokenizer SHA-256:
`623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7`.
NVIDIA revision: `2dc98e2afe4face0e4ce40972a915c45368bd34a`.
Runtime package: `tokenizers==0.22.2`. No weights or remote Python code are needed.
The earlier 74-record provider-usage comparison is a separate REPLAY-based check
of this asset and the published chat template. This experiment made no new API calls.

The verified checkpoint archive is
`experiments/results/cycle28-local-budget-checkpoint.tar.xz` (8,532,844 bytes),
SHA-256 `5f9d5cdbfea204059ef0313aad5b3505ef26a4fd2326d754ef7acd92f4ea7823`.
It contains 1,999 files / 159,912,544 uncompressed bytes. Every member was read
back and hash-checked; 123,584 decoded-text/SQLite-dump pattern checks found zero
recognized credential matches. That is a limited pattern screen, not universal
secret detection. The manifest explicitly leaves the cycle and goal incomplete.
Source changes remain in the working tree; no Git commit or remote was created.

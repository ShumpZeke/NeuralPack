# Cycle 24: source omission repair and unit-to-passage selection

**EMPIRICAL.** The experiment acquired all non-changelog RST documentation under
`doc/build` from SQLAlchemy 2.0.43, pinned to commit
`a303102a7bfbbb6da992a89b6610d71f080fb5eb`. There are 153 files and 2,110,162 raw
bytes, approximately 528K chars/4 tokens available per request. Source hashes,
the archive hash and the MIT license are retained locally. The corpus is new
to these NeuralPack experiments; the tasks are developer-authored, not an
independently sealed evaluation.

## Repair before research

The first run indexed zero files. Compiler 5.2 blindly excluded directories
named `build`, including this repository's authored documentation. Full artifact
verification accepted the internally consistent empty pack; it could not prove
that the intended source corpus had been indexed. The failed run did not publish
retrieval scores or make model calls.

Compiler **5.3** makes `build` directories eligible for normal source scanning.
Extension, encoding, file-size, path and credential checks still apply. This
can include generated text where a project places it under that name; a generic
directory name cannot establish which text is generated. Existing 5.2 artifacts
require recompilation before incremental updates, so a change in scan rules
cannot silently mix generations.

A separate benchmark contract compares every compiled file path and raw source
hash with the declared source manifest. Valid-but-empty and valid-but-partial
artifacts now fail this gate. Regression tests cover both nested documentation
and top-level source in `build`, subsequent updates and version migration.
The corrected source scan found all 153 expected files without renaming or
flattening their paths.

The second preparation completed three valid artifacts, then caught a benchmark
adapter error: a list-returning helper had been unpacked as a pair. Tests now
cover zero, one and three returned passages. The third run reused the verified
artifacts with their original build measurements and identities. It did not
claim another compile or spend model calls on either preparation failure.

## What the selector tests

The research path compiles 512-character units, retrieves them with BM25, then
optionally includes neighboring units or expands to nearby paragraph boundaries.
It reads the compiled SQLite artifact only. It never reads raw repository files
at query time or calls a generative optimizer. Missing source lines are not
invented during coalescing. Unresolved paragraph boundaries and expansions that
do not fit are reported; risk remains uncalibrated. These rules do not prove
semantic sufficiency or understand complete RST directive structure.

Controls use 2,048-character units with BM25 or a real local neural hybrid.
Both the public PackSelector flow and a common assembly flow are included. The
latter accounts for source-label overhead while selecting, which avoids giving
the challenger an unmeasured formatting advantage. Every final rendered context
fits the same declared cap, including provenance labels. Query bytes survive.

The neural baseline uses `sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU inference, masked mean pooling and
L2 normalization. Its input limit is 256 model tokens and the document prefix
limit is 2,000 characters; long queries can be truncated. All 80 unique hybrid
cells actually used the embedding channel. Embeddings remain optional.

Ten fresh SQLite scenarios were executed twice using SQLAlchemy 2.0.43 in an
isolated Python 3.12.10 environment. They cover flush boundaries, nested rollback,
failed-flush recovery, expiration, reusable versus permanent close, unflushed
refresh, joined collection uniqueness, streaming incompatibility, loaded
collection state and disabled implicit transactions. Observed outputs are frozen
as answer labels and never enter the compiled evidence.

## Completed LOCAL measurements

Three shuffled query sweeps produced 960 observations across eight methods,
ten questions and 512/1,024/2,048/4,096-token caps. All repeated cells reproduced
the same selected bytes. All source spans and token counts were checked again
before preparing any LIVE requests.

| Method | 512 | 1,024 | 2,048 | 4,096 |
| --- | ---: | ---: | ---: | ---: |
| Public BM25 | 0/10 | 0/10 | 0/10 | 1/10 |
| Shared assembly BM25 | 0/10 | 1/10 | 1/10 | 3/10 |
| Micro units alone | 0/10 | 0/10 | 0/10 | 0/10 |
| Micro + one neighbor | 0/10 | 0/10 | 0/10 | 1/10 |
| Micro + two neighbors | 0/10 | 0/10 | 0/10 | 2/10 |
| Micro + paragraph | 0/10 | 0/10 | 0/10 | 5/10 |
| Public hybrid | 0/10 | 0/10 | 1/10 | 2/10 |
| Shared assembly hybrid | 0/10 | 0/10 | 1/10 | 4/10 |

These counts require every annotated manual passage, not every possible source
of equivalent evidence. They are not answer accuracy or evidence-sufficiency
probabilities. The two public paths require fallback in all 512-token cells
after source labeling; zero context is not counted as a successful optimization.
Other methods can return nonempty yet unhelpful evidence.

One initial build per artifact measured 3.54 seconds for deterministic 2,048-char
blocks, 4.78 seconds for micro units, and 113.95 seconds for semantic compilation.
The semantic timing includes initial framework/model loading. Process RSS after
these sequential builds was about 46 MB, 48 MB and 750 MB respectively; these are
process endpoints, not isolated peak-memory measurements. Disk sizes were 15.18,
16.61 and 17.53 MB. Original build records were reused by the successful query
run, and that reuse is explicit.

Median query latency varied by budget: public BM25 30–32 ms; shared BM25 36–54;
micro-only 44–64; paragraph expansion 57–76; public hybrid about 185–186;
shared hybrid 195–248. Query measurements share a process with the local encoder
loaded. Host load was uncontrolled. No other agent CPU benchmarks, tests or LIVE
calls overlapped the query sweep. There is no sub-millisecond or 10× claim.

## Frozen answer evaluation

The plan contains 80 observations and 78 unique requests: shared BM25, shared
hybrid and the paragraph challenger at 1,024 and 4,096 estimated evidence tokens,
plus no-source and full-source controls on all ten scenarios. The paragraph
challenger was selected after this LOCAL diagnostic, so subsequent outcomes are
not independent evidence for promoting it.

Each new request calls only the final answering model:
`nvidia/nemotron-3-super-120b-a12b`, temperature 1, top-p 0.95, thinking disabled,
2,048 maximum output tokens, 180-second socket-operation timeout. The
[model card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard),
checked September 7, 2026, describes support up to 1M tokens. Hosted capacity is
not assumed to equal that maximum. The full source is approximately 530,352
estimated tokens with labels; service rejection or timeout remains missing
evidence, with no silent truncation or automatic retry.

Plan SHA-256:
`169c240f1dd2f079bcbf13bda992f366023cfa7319f420fe744fe9b10a984282`.
All 960 LOCAL contexts were reconstructed before this plan was frozen. No-source
answers measure the model's prior knowledge and do not reward context erasure.
Actual target success and token usage are reported from raw completed
responses. NIM dollar prices remain N/A without applicable verified pricing.

## Completed LIVE measurements and attacks on the conclusion

All 78 unique requests finished: 61 responses and 17 HTTP 503 failures. No failed
request was retried. Two additional planned observations reused identical
payloads within this run; they are not independent responses. Only the final
answering model was called. Every raw response, request hash, usage counter and
strict JSON grade is retained. See the [complete answer report](../experiments/results/cycle24-unit-answers.md).

| Method | 1,024: correct / completed | 4,096: correct / completed |
| --- | --- | --- |
| Shared BM25 | 2 / 8 | 3 / 8 |
| Shared hybrid | 1 / 7 | 2 / 7 |
| Micro + paragraph | 4 / 9 | 2 / 9 |

Every arm planned ten tasks. The no-source control passed 2/8 completed tasks;
the full-source control passed 0/7 under the exact JSON-and-values contract.
Missing calls are not wrong answers. Full-source prompts averaged 512,590 actual
input tokens. Six completed full-source responses reported 506,880 cached input
tokens each. Reported cache reuse affects hosted latency and possible billing;
missing cache counters cannot establish that other requests were uncached.
There is no claim that sending the full source guarantees correct answers, or
that these results estimate the model's general ability.

At 1K, paragraph expansion versus BM25 had two wins, no losses, five ties and
three missing pairs. At 4K it had no wins, one loss, six ties and three missing.
Inspection found that one 1K win and the 4K loss were caused by correct values
being returned in Python dictionary syntax instead of JSON. A supplementary
post-hoc diagnostic accepts only bounded literal containers, rejects calls,
duplicate keys and ambiguous output, and leaves the primary grades untouched.
It leaves one confirmed value-level paragraph win at 1K and zero at 4K.
This diagnostic does not repair answers or normalize differing class-name strings.

Only three tasks have completed responses in all six selected-method/cap arms.
The descriptive complete-case frontier therefore uses those same three tasks,
retains all other outcomes in the report, and cannot support a general promotion.
One stochastic response per payload and selection of the challenger after LOCAL
diagnostics add further limits. Neither the 5/10 passage result nor four strict
passes in one arm establishes a reliable answer-quality gain.

Final acceptance: **765 tests passed, two skipped; all 63 mutation tripwires were
killed**, including source erasure, corpus substitution, evidence reconstruction
and neighbor-expansion attacks. The three original critical mutants remain killed.
The seven supplementary-format regressions preserve strict grading and reject
unsafe or ambiguous literal interpretations.

**Current decision: PIVOT REQUIRED.** Keep the compiler omission repair and
corpus-identity gate. No new selector is promoted on these LOCAL passage checks.
Small pieces and nearby text have not shown reliable recovery from weak or
irrelevant seeds here. Keep the exact corpus gate, source-preserving assembler
controls and failure regressions. Discard promotion of paragraph expansion or
embeddings based on passage coverage or format-dependent wins. The next highest
value hypothesis is whether deterministic query views can separate the actual
operation from shared schema and answer-format instructions before retrieval.
First measure which useful query terms and symbols the current lexical and
256-token neural inputs retain, and compare to the existing clause baselines.
This is an untested hypothesis, not an established cause of the observed failures.

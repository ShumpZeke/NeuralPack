# Modern seeds remain challengers; acceptance checks known metadata semantics

Status: accepted for artifact validation; retrieval experiments not promoted.

## Artifact acceptance

Cycle 14 reproduced fifteen failing checks against `be28ae5`: a resealed artifact
could claim false counts, invalid numeric values, unsupported flags/mode, a bogus
embedding status, malformed encoder JSON, or false per-block token estimates.
Unknown mode was silently accepted by query, stats and update. Matching hashes
alone were insufficient to establish these known storage contracts.

All product readers now reject unsupported mode/flag/status values and malformed
nonnegative integer claims. Full verification additionally compares file/block
counts, joined-source token estimates, block token estimates, dependency policy,
and supported embedding-state/dimension metadata with stored contents. It checks
encoder identity without loading a model. Default queries gain no corpus scan.

The optional encoder identity remains unnecessary for lexical retrieval of a
legacy semantic artifact; hybrid retrieval requires a matching encoder. Full
acceptance rejects missing identity for an artifact claiming indexed vectors.
Valid empty, unavailable and deterministic compilation states remain supported.

This does not authenticate a publisher, prove that external source is complete,
validate every semantic field or vector value, or fully validate arbitrary schema
DDL. Fast queries assume an accepted artifact and do not independently recompute
positive count claims. Cached incremental sealing still assumes an accepted base.

## Retrieval decision

The default remains ordinary lexical BM25, with graph expansion off. Nine LOCAL
challengers share literal window chunks and 512/2,048/8,192 estimated budgets.
The larger corpus contains Click 8.5.0 plus selected CPython 3.12.10 source and
documentation, with 559,738 available compiled tokens per request. Source fields
are normal weighted FTS5 BM25, not a novel retrieval algorithm.

Qwen3-Embedding-0.6B runs locally through pinned safetensors, with last-token L2
pooling and the documented query-instruction form. It makes no generative calls.
Experiments use a 512-token truncation cap, GPU float16 inference and float32
vectors; these differ from the MiniLM CPU/256-token baseline. Plain and
path/symbol-prefixed embeddings are separate variants. The encoder is not wired
into the production semantic artifact contract; the complete sidecars and their
limitations are archived.

LIVE Nemotron answers did not establish a consistent improvement over BM25.
The twelve prospective standard-library cases are developer authored, eight share
one module, and one observation per unique prompt cannot establish statistical
significance. Eight reused Click questions are controls, not a fresh holdout.
Weighted search helped some Click-only cases but lost that advantage after corpus
expansion. Qwen sometimes won and sometimes lost, with higher local compute.

Keep the research encoders, frozen tasks, literal source and raw answers for
reproduction; do not add their dependencies or experimental indexes to the
default installation. A larger index and larger evidence budget are not monotonic
answer-quality improvements in these observations. That statement is EMPIRICAL,
not a theorem about all models.

## Next experiment

CONJECTURE: selecting a relevant module/document before selecting its passages
may address weak seeds more cheaply than global dense retrieval. Compare this
hierarchical retrieval against flat BM25 and metadata-weighted BM25, including
multi-module questions and misleading module names. Avoid forcing every query
into one module. Evaluate corpus relevance and missing-source detection
separately from passage ranking; all 324 out-of-corpus diagnostic selections in
cycle 14 returned text, with uncalibrated risk. Their nonempty output was not
evidence that the needed source existed.

References: [SQLite FTS5 BM25](https://www.sqlite.org/fts5.html#the_bm25_function),
[Qwen3 embedding model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
[CPython pinned source](https://github.com/python/cpython/tree/0cc81280367df838c4b199f8f0378837165071c2),
and the exact observations in `experiments/results/cycle14-answers.json`.

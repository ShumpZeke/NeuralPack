# Explicit client encoders and honest context boundaries

Status: accepted repairs. Compiled `.npk` retrieval remains the BM25 baseline.
No new answer-quality advantage is established.

The older optional prompt client constructed an embedding-enabled selector by
default. Merely using this client could import torch/transformers and load local
MiniLM weights, even when the chosen plan eventually sent the full source. The
compiled `.npk` query path already avoided that initialization.

The selector and retriever now default to lexical-only operation. The legacy
planner and client expose `use_local_embeddings=True` for explicit experimental
fusion. Their lower-level selector/retriever retain the existing
`enable_escalation=True` option, which refers to a local non-generative encoder.
Missing weights leave lexical retrieval available. Runtime downloads remain
disabled. `NPK_ENABLE_EMBEDDINGS=0` still disables an explicitly requested encoder;
setting it to 1 does not opt the default client into using one. Explicit semantic
`.npk` compilation is unchanged.

The repair also addresses three separate correctness problems:

- A seed larger than the caller's budget could be kept unconditionally. Costs
  were summed per block without accounting for separators or rounding. Seeds now
  obey the joined-text estimate. Dependency output is checked again. If the result
  cannot fit, the retriever returns the original source with `fallback_required`,
  `seed_failed`, `budget_exceeded` when applicable, and zero tokens avoided. It
  does not describe that full-context output as a budget-respecting optimization.
- The invariant guard counted a long current query as context and could accept
  deletion of the source. It also searched for the query across all conversation
  roles, and its query helper guessed the last paragraph of long messages. It now
  excludes the same original question on both sides of the context-presence check,
  preserves the full current query in the latest user slot, and retains ambiguous
  input in full. A single combined legacy prompt supports the explicit blank-line
  `QUESTION:` delimiter outside backtick fences; structured separate input is clearer.
- The client's estimator label said chars/4 although its arithmetic uses
  floor(chars/3.8), with a minimum of one for nonempty text. The new label is
  `planner_chars_div3_8_estimate`. The analyzer rejects the old mislabeled v2
  traces instead of silently reinterpreting them. Historical files are retained
  as evidence of the old behavior. The compiled estimator remains chars/4.

The presence guard does not prove evidence sufficiency or general semantic safety.
Risk remains uncalibrated. Neither character estimator bounds a target tokenizer.

## Controlled performance evidence

Three shuffled fresh-process trials compared the previous default, previous code
with its encoder disabled, the repaired default, and explicit repaired encoder
opt-in. Both code snapshots used the same installed cache. Enabled arms had to
load the pinned MiniLM revision; disabled arms had to avoid even probing it.
Network access was denied. The target was MOCK, with one invocation per request.

The table gives medians for the older optional client only. Available-context
sizes use chars/4 for comparability with the previous profile. Actual dispatch
estimates use the declared legacy estimator. RSS is measured after each call,
not peak memory. First-call times exclude imports and process startup; only the
first row also pays initial model load. Later sizes can reuse the loaded model.

| Available context estimate | Old first call ms | New first call ms | Old warm ms | New warm ms | Old/new RSS MB |
|---|---:|---:|---:|---:|---:|
| 2,202 | 4,077.04 | 7.33 | 5.32 | 4.65 | 684.81 / 29.13 |
| 26,004 | 1,063.25 | 56.89 | 50.13 | 49.58 | 724.16 / 30.42 |
| 51,938 | 1,401.21 | 93.47 | 94.91 | 95.04 | 731.22 / 31.58 |
| 102,491 | 1,754.08 | 180.72 | 192.13 | 175.76 | 734.96 / 33.64 |

Library imports separately cost about 72 ms before and 78 ms after. The old
explicitly disabled configuration has similar costs to the new default. This is
removal of an unnecessary default dependency, not a novel retrieval speedup.
All 96 calls preserved query, system and nonempty source, made one MOCK target
call, and dispatched identical messages across arms at each size. No CPU tests
or mutations overlapped these profiles; OS activity and caches were uncontrolled.

## Seed comparison and promotion decision

The frozen comparison fed 2,183 real compiled blocks into the legacy seed selector,
with no graph edges, at 512/2,048/8,192 legacy estimated-token caps. It used 28 known,
correlated tasks from pinned CPython and Click source. Each request had 589,197
available tokens by the joined legacy estimate; summing block estimates yields
587,038, a different representation. Neither is a cumulative context-size claim.

The real local model was `sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU, max length 256, masked mean pooling
and L2 normalization, with the existing 2,000-character document limit. Its load
cost 9,769 ms in this separate experiment; the first document/query scoring call
cost 45,787 ms. Later queries reused document vectors and had median scoring cost
25.27 ms. Those real scores were replayed identically into both code snapshots.
Selection timings exclude the encoder and averaged 2,157 ms: this legacy scanner
is not the compiled-index query runtime.

Across all three budgets, lexical selection had mean required-span coverage
0.0476 and embedding fusion 0.0298. Neither retained every labeled required span
on any task. These are source diagnostics, not answer accuracy or sufficient-context
proofs. There were no public-grid budget violations; the violations were separately
reproduced by permanent synthetic counterexamples. All 84 lexical and all 84
embedding selections matched before/after when their mode was explicitly held
constant. Changing the default switches to the cheaper existing lexical channel.
No encoder, graph or legacy optimizer is promoted as a better retrieval method.

All 504 rows were independently reconstructed from block IDs, text, source spans,
task requirements and declared budgets. The seed snapshot predates the final
message-boundary and token-label repairs. Both exact versions are archived; the
measured selector, retriever, scorer, estimator and encoder files match the final
source. This distinction is explicit in the cycle record.

Keep the repaired infrastructure and deterministic default. Continue the seed
research with original-query plus verbatim-clause retrieval against competent
compiled BM25 and weighted BM25, and require new answer evidence before promotion.
The current verdict remains **PIVOT REQUIRED**.

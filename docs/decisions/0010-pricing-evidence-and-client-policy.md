# Quotes require provider identity; reports require raw evidence

Status: accepted. Retrieval algorithms and compiled-artifact representation unchanged.

The old cost API returned a made-up rate for unknown models, aliased mock providers
to paid models and treated placeholder source descriptions as verification. The
planner also forecast 100 output tokens, arbitrary latency and unobserved cache hits.
Those values escaped through client metadata and trace aggregation.

The supported registry now contains only exact `gpt-4o` and `gpt-4o-mini` IDs,
scoped to an explicitly supplied OpenAI provider. Their standard text rates were
checked on 2026-09-07 against the official [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o)
and [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) pages.
No mock, default, gateway, NVIDIA or other-provider inference is permitted. Other
models return None/N/A, or raise an explicit lookup error in strict mode. Rates
have source URLs, calendar review dates and a scope. Metadata validation does not
authenticate a price or prove current billing, so the old `is_verified` claim is removed.

Cost calculations reject negative/fractional/boolean token counts and cache counts
larger than input. Tiny request quotes retain precision. Hypothetical savings may
be negative; a zero baseline denominator yields None. Quotes exclude tools, images,
audio, taxes, output changes and local compute; they are not measured net savings.

The optional legacy planner can rank comparable uncached input quotes. Without a
documented provider/model combination it ranks estimated input tokens. It no longer
forecasts output length, latency or cache hits. The unused latency-filter parameter
is deleted. All risk scores, including full-context passthrough, are uncalibrated;
preserving all source is evidence about omission, not answer correctness.

The optional client had inverted a maximum risk score into a minimum confidence
score. Its configured 0.05 risk ceiling now maps to the intended 0.95 retrieval
score threshold. These remain uncalibrated scores. Shadow mode records the full
prompt that was actually dispatched and zero executed reduction. Hypothetical
selection stays in separately labelled plan metadata. Optimized trace counts use
one estimator consistently; provider-adapter usage is stored separately.

Trace schema 2 labels token basis, mode and evidence class. Analysis rejects corrupt
JSON, duplicate IDs and inconsistent token differences, separates incompatible
bases and ignores legacy cost/savings assertions. It does not produce actual billing
or net-savings claims. Reading old records does not retroactively validate them.

Six obsolete benchmark runners are removed: evaluation_suite, msc_ablation,
sealed_suite_200, context_optimization_benchmark, component_ablation and
live_validation. They used inspected/mismatched fixtures, fake completion counts,
mislabelled mock/string results or old claims. Static input data needed by the
profiler survives in legacy_fixtures. Historical reports and exact old source remain
in the cycle archives; their claims are not preserved as current behavior.

The economics command now consumes one frozen experiment:

```sh
python -m benchmarks.economics RUN_DIRECTORY --output REPORT.json
```

It verifies request/context hashes, raw responses, usage, every planned observation
and grades. The report is REPLAY/LOCAL, with zero new API calls. Its optional
`--quote-provider` argument supplies an explicit hypothetical pricing assumption.
Returned model IDs must match exactly. Missing full-context/preprocessor arms,
local compute costs, failed-call billing and break-even remain N/A. It never inserts
quality figures from a separate run. Shared responses are not independent samples
and per-arm quotes cannot be added together as actual experiment billing.

EMPIRICAL: the final three paired legacy-client profiles retain the query, system
instruction and nonempty source in all 96 calls. More conservative selection
substantially increases dispatched context on uncertain questions. This is a
policy correction, not evidence of superior retrieval. Warm ~102K-source-token
calls take about 192 ms here; no sub-millisecond claim is made. The core `.npk`
compiler and selector are byte-identical to the prior cycle.

EMPIRICAL: a separate fresh-process probe measured ~26 MB RSS for compiled search,
~684 MB for the optional legacy client with its neural libraries, and ~24 MB with
that client's existing embedding-disable setting. This configuration comparison
does not establish equal evidence quality or a new product speedup. CONJECTURE:
making optional client encoders explicit, after paired evidence checks, can remove
most of its initialization cost. This should precede further query-decomposition
experiments. Default compiled retrieval already avoids these imports.

# Cycle 29: compact source views

**PIVOT REQUIRED. Automatic docstring compaction is rejected as the product default.**
The experiment improves some source-check totals but loses other evidence. It
does not establish better answers or an advantage over the frozen CRISP scorer.
The compiler/runtime default still makes zero generative model calls.

## What the diagnosis found

EMPIRICAL: on the previously inspected 246 annotations, field retrieval finds
the required source in its candidate pool for 241 cases but selects it for only
205 at a 2,048-token cap. Its 41 selected misses include five pool misses and
five targets spread across multiple blocks. None has a supporting block larger
than the entire 2,048-token cap. More seed candidates alone cannot explain the
remaining losses. Source ranking and allocation deserve separate tests.

## The challenger and its limits

The source-view compiler parses complete Python files locally, identifies literal
docstrings, and prepares exact surviving source spans. It retains mixed statement
lines and trailing comments. It does not run repository code, generate summaries,
or turn a block beginning inside a docstring into invented code. Each omission
has a visible marker and source-line metadata; marker-only evidence is refused.
All marker and separator tokens count against the budget.

Three policies use identical frozen candidate lists: full blocks; compact views
whenever smaller; and compact views only after full-block rejection. The latter
is called `rescue` in the raw records, but it is **not** a safe-fallback guarantee.
Selections containing omissions report `selected_with_omissions` and an explicitly
uncalibrated risk label. These research modules are not imported by the product.

FALSIFIED: docstring deletion always preserves answers or execution. A permanent
fixture returns its function's `__doc__`; the complete program returns a string,
while its compact view returns `None`. A documentation question also loses its
only literal answer. Python exposes docstrings as runtime data.
[Python data model](https://docs.python.org/3/reference/datamodel.html#user-defined-functions)

FALSIFIED: compacting ranked blocks cannot lose implementation evidence. Another
fixture first encounters oversized noise, then the required definition. Full
packing skips the noise and retains the definition; compaction makes the noise
fit and crowds out the definition. This requires no documentation-dependent query.

The physical-span tests account for Python AST's UTF-8 byte columns, Unicode,
partial docstrings, inline statements, empty seeds, query preservation, marker
cost, and cross-request isolation.
[Python AST source locations](https://docs.python.org/3/library/ast.html#ast.AST)

## Matched-budget results

EMPIRICAL: the frozen `cycle29-source-views-v2` matrix completes all 5,994
selections: 222 questions, three seed methods, three view policies, and caps of
512, 2,048 and 8,192 exact NIM tokens. The 207 retrieval questions carry 246
annotations; another 15 questions concern executed library behavior. All were
inspected before this study. This is development evidence, not heldout accuracy.

Each request can select from the same 3,513 blocks. Joining the 153 source files
that own those blocks produces 558,876 tokens. Older reports count 558,878 when
also joining two empty `__init__.py` files: their separators account for the
difference. The selectable source is unchanged. No efficiency ratio mixes those
renderings.

| Seeds | View policy | Checks at 512 | Checks at 2,048 | Checks at 8,192 |
|---|---|---:|---:|---:|
| Body BM25 | Full | 120 | 148 | 183 |
| Body BM25 | Compact | 130 | 162 | 191 |
| Body BM25 | On rejection | 121 | 151 | 183 |
| NeuralPack fields | Full | 162 | 205 | 229 |
| NeuralPack fields | Compact | 172 | 211 | 231 |
| NeuralPack fields | On rejection | 169 | 205 | 229 |
| Frozen CRISP scorer | Full | 182 | 225 | 242 |
| Frozen CRISP scorer | Compact | 191 | 233 | 241 |
| Frozen CRISP scorer | On rejection | 188 | 226 | 242 |

All denominators are 246 source annotations, **not answer accuracy**. At 2,048,
compact fields gains seven and loses one; compact CRISP gains eight without an
annotation loss. At 8,192, compact CRISP loses one. These CRISP ranks come from
the previously frozen scorer on shared NPK blocks, not its newer implementation.

The behavior diagnostic exposes the benchmark tradeoff. Requiring every nonblank,
non-docstring line of the previously listed primary implementations, full fields
covers 10/15 cases but compact fields covers only 9/15. Both compact policies lose
the `rich_overshoot` case. Body's rejection policy loses `rich_zero_unknown`.
Primary implementation exposure is not proof of sufficient dependencies or a
target answer. No new target calls were justified for promoting this policy.

At 2,048, compact fields retains only 791 docstring source-line occurrences across
the 222 selections, versus 14,767 with full blocks. These cumulative counts describe
discarded documentation, not available context size. Better implementation-needle
counts conceal substantial removal of other potential evidence.

![Matched-budget source retention](../experiments/results/cycle29-source-view-curves.png)

## Cost and independent checks

EMPIRICAL: initial whole-payload retokenization was too slow. Run v1 was explicitly
stopped after 292/5,994 selections; all 292 completed outputs match v2. It remains
recorded as incomplete. V2 uses the previously tested prepared counter, with no
change to source selection. Its view preparation took 574 ms on this warm host;
preparing reusable count regions took 2,304 ms. These are single measurements,
not a cold compilation distribution or an incremental-update claim.

The separate auditor checks all 5,994 final contexts with the upstream tokenizer,
all source fragments and omission intervals, every raw control, and the source
grades. It independently replays 859,367 packing decisions with the prepared
counter and directly recounts every 101st proposal: 8,508 upstream checks. The
replay therefore shares the established counter; it is not 859,367 independent
full-tokenizer calls. All final budgets and sampled counts agree.

A separate paired profile measures the counting change on two predetermined
questions, every seed/cap, full and compact policies, repeated twice. Exact-text
caches start empty per query; compiled regions stay loaded. Output bytes agree
in all 72 pairs.

| Context cap | Whole counting, median ms | Prepared counting, median ms | Ratio |
|---:|---:|---:|---:|
| 512 | 125.64 | 9.31 | 13.50× |
| 2,048 | 374.75 | 10.80 | 34.71× |
| 8,192 | 1,382.97 | 19.54 | 70.79× |

This speedup belongs to reuse of the **existing** counter. It excludes seed lookup,
artifact I/O, view compilation and target inference, and is not a new end-to-end
NeuralPack speed claim. The paired profile separately measures tokenizer loading
at 550/586 ms and prepared-region setup at 2,412 ms. The host is uncontrolled.
There are zero generative calls in this cycle; target accuracy and dollar savings
are unmeasured.

## Decision and next experiment

KEEP explicit source provenance, the compaction counterexamples, the fixed-budget
comparison, and reuse of prepared token counts in research. DISCARD automatic
docstring removal as a default or a semantic-preservation theorem. No product
format, runtime policy, or champion changes.

The next useful experiment should use new repository behavior questions and
definition-complete retrieval, including captured defaults, conditional bindings,
and colliding symbols. Compare strong seeds at identical caps, preserve complete
source controls, and hold target settings fixed. A higher source-needle score
alone is insufficient for promotion.

Evidence: `experiments/results/cycle29-source-view-audit.json`,
`cycle29-source-view-analysis.json`, `cycle29-source-view-profile.json`, and the
frozen plans/contexts under `experiments/runs/packs/cycle29-source-views-v2`.
Ten new regression tests pass. Final full tests pass 1,150 with two explicit
symlink skips; all 147 mutants are assertion-killed, including the three new
view tripwires and the original critical mutations. Both stages bind the same
355 Python source hashes. Full tests include tracked-text and all-object Git
credential scans; no credential was used or printed in this cycle.

Frozen plan SHA-256:
`8679a5081782cfe3934826694cc272c29c38136d3ca3f5bd28795d98b3caa754`.
Audit SHA-256:
`7b16666a4c9dd22db70cc8e937454a4b8b0ae106e7a65ee516db4dc260192c70`.

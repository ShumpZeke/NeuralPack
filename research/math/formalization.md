# A scoped formulation of context selection

Former universal guarantees, information-bottleneck equalities and invented
local cost are withdrawn. This defines a research problem; it does not assert
that the present selector solves it optimally.

## Representation and measurement

**PROVED UNDER ASSUMPTIONS — representation contract.** Let C be a finite
collection of source blocks. A selection consists of an index subset S and an
explicit ordering pi. A renderer copies those blocks unchanged and adds declared
source headers. Under that renderer, every evidence byte originates in a selected
block or a declared wrapper, by construction. This does not establish relevance.

The question Q and system instructions I remain separate. An explicit tokenizer
must count the exact rendered input when claiming a provider-token budget.
Current NeuralPack uses a documented character estimate over selected source.

**EMPIRICAL — answer measurement.** Fix source, question, target model, generation
settings and task validator before scoring. Record the entire validator result
for each completed answer. Keep transport and selection failures visible.
Replayed responses and multiple budgets on the same task are correlated, not
independent samples.

## Minimum sufficient context

**PROVED UNDER ASSUMPTIONS — finite exhaustive minimum.** Fix a finite set of
allowed selections/orderings, a nonnegative cost and a deterministic feasibility
predicate that can be evaluated exactly. If feasible selections exist, enumerating
every allowed selection and choosing the cheapest feasible one returns a minimum
in that space. A finite nonempty set of costs has a minimum, and exhaustive search
considers its member.

A single successful LLM response does not establish deterministic sufficiency
or a future success probability. Temperature zero alone does not make that
assumption rigorous. State oracle and granularity; minima at one granularity
need not be minima at a finer granularity.

**PROVED UNDER ASSUMPTIONS — restricted search.** Under the same fixed cost and
predicate, the cheapest feasible selection found in a restricted search has cost
at least the exhaustive minimum: its searched feasible set is a subset of the
full feasible set. This is an upper bound on minimum cost, not a minimality proof.
Larger searches are **Empirical MSC**. Ratios using different renderers or
granularities have no such bound.

## Objectives and hypotheses

**CONJECTURE — practical objective.** A useful selector should trade answer
evidence against input tokens, latency, memory, compilation cost and omission
risk. No universal scalar weighting is established. Unknown prices and
uncalibrated risks remain unknown.

**CONJECTURE — evidence interaction.** Some workloads may need several facts
together, making independent relevance scores inadequate. This assigns no mutual
information values to arbitrary code and does not prove every ranker fails.
See [theorems.md](theorems.md) for the precise graph and ranking statements.

# Message preservation and clause retrieval

**FALSIFIED — whitespace-normalized equality establishes semantic equality.**
The JSON strings `"a  b"` and `"a b"` differ as string values, yet replacing each
whitespace run with one space maps them to the same value. The permanent attack
extends the strings past the old deduplicator's length cutoff and reproduces
deletion under the default planner.

**PROVED UNDER ASSUMPTIONS — deleting repeated records need not preserve answers.**
Let the requested answer be the number of occurrences of a record in a sequence,
including equal records. A sequence containing that record four times has answer
four. Replacing later occurrences with a single-record representation without
recoverable multiplicity does not determine that answer. This is a counterexample
to unconditional deduplication, not a claim that all source-object interning is
unsafe. A storage representation retaining all references and multiplicities is
a different operation.

The removed implementation emitted one omission marker per repeated paragraph.
Those marker positions can retain multiplicity in the exact-repeat case. The
permanent repeated-event test requires verbatim preservation; it does not claim
that a target model was observed to miscount those markers. Distinct normalized
string values and deleted license requirements supply direct loss counterexamples.

**PROVED — empty dependency closure remains empty.** With closure defined as
the least fixed point of adding outgoing neighbors to a seed set, no outgoing
edge is visited from the empty set. Thus `Closure_D(∅) = ∅`. This result from the
authoritative audit remains unchanged. Traversal cannot replace seed retrieval.

**EMPIRICAL — the five preservation attacks are repaired.** All five default
outputs changed before repair and remain equal to their input messages after
repair. The invariant checks are necessary guards, not a semantic sufficiency
theorem for arbitrary selected context.

**CONJECTURE, not supported by this LOCAL comparison — auxiliary verbatim query
clauses improve evidence selection.** Eight new tasks and 28 known controls were
tested with fixed budget caps and the same source representation. Clause methods
usually increased ranking latency and often reduced labeled span coverage. One
model's incomplete paired answer evidence is also insufficient for promotion;
the second frozen run remains pending. This does not prove that all forms of
semantic query decomposition fail.

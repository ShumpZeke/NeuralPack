# Exact block reuse

**PROVED UNDER ASSUMPTIONS.** Let an indexed payload be a deterministic function
of a block signature `s = (kind, name, exact text)` and a fixed compiler
configuration. Let `o(s)` and `n(s)` count occurrences of that signature before
and after an edit. Retaining an occurrence must consume one old occurrence and
produce one new occurrence, without altering its indexed payload. Positional
metadata is updated independently.

The maximum number of reusable occurrences is

`R = sum_s min(o(s), n(s))`.

For each signature, neither its old nor its new multiplicity can be exceeded,
giving the upper bound. Pairing any `min(o(s), n(s))` old and new occurrences
within every signature attains that bound. Distinct signature groups do not
share occurrences, so their counts add.

The assumptions exclude configuration-dependent embeddings, cross-file graph
derivation and any index whose payload also depends on position or mutable
external state. A reuse implementation must separately preserve metadata,
duplicate multiplicity, transaction behavior and search ordering. The statement
does not prove correctness of the research adapter or predict wall-clock cost.

**EMPIRICAL.** Cycle 22 observed zero matching blocks after a leading blank line
in its C and RST files, despite nearly complete reuse after an append. Therefore
these examples falsify the universal claim that a small edit always preserves
most blocks under the current splitter. They do not establish a universal
property of all positional chunkers.

**CONJECTURE.** Content-anchored boundaries can improve insertion stability on
these workloads. This requires measurement; repeated content, size caps and
retrieval-quality tradeoffs can defeat naive designs.

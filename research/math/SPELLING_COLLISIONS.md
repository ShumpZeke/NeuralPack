# Normalized spelling is a candidate relation

**PROVED.** Define `N(s)` to remove underscores from an ASCII identifier and
lowercase its remaining characters. This function is not injective:
`N("foo_bar") = N("foobar") = "foobar"`, although the two inputs differ.

**PROVED UNDER ASSUMPTIONS.** In a language that permits distinct bindings for
these identifiers, equal normalized spellings do not imply equal bindings or
values. Python supplies a concrete counterexample: the assignments `foo_bar = 1`
and `foobar = 2` can coexist in the same scope. Their normalized spellings agree;
their assigned values differ. No probabilistic assumption is needed.

The implication for retrieval is limited: normalization may provide candidate
groups whose members require disambiguation through scope, language, version or
additional evidence. A single recorded spelling also does not prove that the
index contains every relevant declaration. This observation does not establish
an omission probability, a sufficient context, or a universal retrieval policy.

**EMPIRICAL.** Cycle 26's regression tests preserve two spellings in the same
normalized group and report the collision explicitly. Its public-source
experiment improves literal-name lookup while failing several behavior-passage
checks. The mathematical counterexample and measured retrieval outcomes are
separate evidence.

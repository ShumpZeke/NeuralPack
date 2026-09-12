# Defensible mathematical claims

Corrected in cycle 10 after unsupported claims remained in the purported repair.
The authoritative historical audit is [INDEPENDENT_MATH_AUDIT.md](INDEPENDENT_MATH_AUDIT.md).
Old performance tables and claimed complexity classifications are not proofs.

Claims are labelled PROVED, PROVED UNDER ASSUMPTIONS, CONJECTURE, EMPIRICAL or
FALSIFIED. Definitions delimit each proof.

## PROVED — empty-seed reachability

Let G=(V,E) be a directed graph, S a subset of its vertices, and D a nonnegative
integer. Define Closure_D(S) as vertices reachable by directed paths of at most
D edges starting in S, including seeds at distance zero.

Then `Closure_D(empty) = empty`.

**Proof.** Membership requires a path whose initial vertex belongs to S. The
empty set contains no initial vertex, so it has no reachable member. This also
holds for unbounded finite-path reachability.

## PROVED — reachability and monotonicity

Under that definition, u belongs to Closure_D(S) exactly when some seed has a
path of length at most D to u. Enlarging S or increasing D cannot remove a
reachable vertex.

**Proof.** The first statement is the definition. Previously allowed paths
remain allowed after adding starting vertices or permitting greater length.

These results concern reachability, not budgeted evidence assembly, which may
discard reachable blocks. Seeds may have no path to a needed fact. Conversely,
a seed can lead to a required non-seed node: direct seed recall is not an upper
bound on expanded recall.

## PROVED — bounded expansion can miss distant nodes

On the chain `v0 -> v1 -> ... -> vd` with no other edges and seeds `{v0}`,
vd is absent at depth D<d and present at D>=d.

**Proof.** Its only path has exactly d edges. Compare that length with the allowed
depth. Increasing depth can repair this nonempty-seed failure, even though it
never repairs empty seeds.

## PROVED UNDER ASSUMPTIONS — top-K omission

Fix a finite collection, a total ranking including its tie rule, and a selector
returning exactly its first K blocks. A required block at a later position is
not selected.

**Proof.** The selected positions are precisely the first K and contain no later
position.

Content-only scoring does not imply that token overlap determines the ranking.
The former proof assumed this for an arbitrary scoring function without
justification. Neither this conditional result nor omitted evidence proves a
target model must answer incorrectly.

## PROVED UNDER ASSUMPTIONS — exact versus empirical minima

For a finite selection space, fixed cost and exactly evaluated deterministic
feasibility predicate, exhaustive search returns a minimum when feasible
selections exist. Restricted search finds at best its cheapest visited feasible
selection, whose cost is at least that minimum.

**Proof.** The searched feasible set is a subset of the full feasible set. Its
minimum cannot be smaller. Exhaustive enumeration includes a minimizer.

A stochastic model's single answer does not meet the predicate assumption.
Compare identical granularity, order and renderer. Nonexhaustive larger searches
are **Empirical MSC**; see [formalization.md](formalization.md).

## FALSIFIED — previous product claims

- Empty-seed expansion recovering all required context contradicts the empty-seed
  result. Bounded traversal also cannot reach every path.
- Expanded recall being bounded by direct seed recall is refuted by a seed
  linked to a required non-seed vertex.
- Every content-only scorer ordering zero-overlap blocks below overlapping ones
  is refuted, for example, by a scorer equal to the negative count of shared
  terms: zero shared terms score zero, above a block with one shared term.
- Retrieval omission establishing zero answer accuracy confuses coverage with
  target behavior. No such probability claim is retained.
- The asserted established Pareto knee, perfect quality and negligible local
  cost were unsupported product claims. Their invented values are removed.
  No general complexity classification or approximation factor is asserted for
  the present arbitrary-model selection problem.

## EMPIRICAL — current evidence boundary

Use post-fix reports in [EVOLUTION_LOG.md](../../EVOLUTION_LOG.md), not old tables
labelled sealed. Corrected comparisons have not established a general graph or
hybrid advantage. Uncalibrated risk labels and a cosine floor are heuristics,
not failure probabilities or mathematical safety certificates.

## CONJECTURE — research questions

Stronger seeds, explicit source scope, better chunks and local iterative
acquisition may help specific workloads. Each must survive matched-budget tests
and counterexamples. A proof about search operations does not prove answer
quality.

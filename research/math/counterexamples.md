# Counterexamples and adversarial cases

Fabricated BM25 scores, universal failure rates, general claims about encoder
negation and perfect NeuralPack answers are removed. A constructed scenario is
not a measured model outcome.

## Empty seeds

**PROVED.** On `entry -> helper -> constant`, bounded reachability from the
empty set returns empty at every depth: no path has a starting node. Increasing
depth cannot fix this case.

## A missing fact recoverable through a seed

**PROVED.** On the same graph, starting from `{entry}` reaches `constant` at
depth two. If constant is the only required node, direct seed recall is zero
and expanded recall is one. Thus expanded recall is not bounded by direct seed
recall. Budgeted assembly can still omit the reachable constant.

## Conditional ranking omission

**PROVED UNDER ASSUMPTIONS.** If a required block ranks below the first K blocks
under the actual total order and the selector returns exactly those first K,
the block is absent by definition. This says nothing about the answer: a model
may know the fact, guess it or fail for another reason. Compute actual scores
and tie behavior for the tested ranker.

## Scope and negation

**CONJECTURE.** Similarly worded production and staging settings can confuse
retrieval or answering. Test exact encoders, lexical baselines, source metadata
and target answers. High similarity alone does not establish negation reversal.

## Recorded real-source failures

**EMPIRICAL.** Post-fix urllib3 LIVE trials contain cases where selected context
outperformed full source and cases with the opposite outcome. Executable
questions and raw answers are retained in cycle 9. This does not establish a
universal advantage. Prospective Click failures and controls are recorded in
cycle 10. See [EVOLUTION_LOG.md](../../EVOLUTION_LOG.md).

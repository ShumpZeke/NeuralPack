# Truncated query representations can erase distinctions

**PROVED UNDER ASSUMPTIONS.** Let `T(Q)` be the complete tokenizer input features
after a fixed truncation policy, including token IDs, masks and any other encoder
inputs. Let `E` be a fixed deterministic encoder in evaluation mode. If
`T(Q1) = T(Q2)`, then `E(T(Q1)) = E(T(Q2))`. This follows by applying the same
function to equal inputs. It assumes fixed weights and deterministic evaluation;
it makes no claim about arbitrary stochastic or stateful implementations.

**PROVED UNDER ASSUMPTIONS.** Suppose a retrieval function's only query-dependent
input is that encoded vector, with a fixed artifact, deterministic algorithm and
fixed tie breaking. Under the preceding equality it returns the same ranking for
`Q1` and `Q2`. Substituting equal vectors into that function proves the claim.
Such a ranker cannot distinguish those two questions through this representation.
It may still return evidence useful to both; indistinguishability does not imply
that every answer is wrong or that useful retrieval is impossible.

**EMPIRICAL.** Cycle 27 reproduced the actual cached MiniLM tokenizer features
at its 256-token limit for 40 queries. All 20 padded variants, despite having
different scenarios after the shared prefix, have identical input IDs, attention
masks and token-type IDs. The recorded feature arrays and SHA-256 groups are in
`cycle27-encoder-input-proof.json`. The SHA values index the stored arrays;
the mathematical statement depends on feature equality, not hash uniqueness.

This limitation applies to the dense query representation. It does not apply
unchanged to hybrid retrieval with a separate full-query lexical channel, a
multi-view encoder, or the target model receiving the original question.

**FALSIFIED.** The universal claim that submitting a full question string to a
bounded encoder ensures that the encoder receives the actual question is false.
The identical padded inputs are a concrete counterexample under this tokenizer.

**CONJECTURE.** Query segmentation or focused views may reduce this failure while
retaining constraints, but choosing a question sentence or operation can omit
important setup and negation. Cycle 27 does not establish a generally sufficient
segmentation policy or an answer-quality advantage. There is no probability,
minimum-context or global optimality claim here.

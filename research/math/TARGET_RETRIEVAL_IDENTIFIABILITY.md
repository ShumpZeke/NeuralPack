# What an answer score can identify

**PROVED UNDER ASSUMPTIONS — decomposition.** Fix a task distribution, source
representation, retrieval policy and target-model configuration. Let `E` mean
that the selected input contains evidence sufficient under the task's stated
semantics, and let `Y` mean that the target's answer passes the task criterion.
If `0 < P(E) < 1`, the law of total probability gives

```
P(Y) = P(Y | E) P(E) + P(Y | not E) (1 - P(E)).
```

Proof: `E` and its complement partition the sample space. Add the probabilities
of `Y and E` and `Y and not E`, then apply conditional probability's definition.
No independence assumption is used. Endpoint cases can be written in joint
probabilities without defining conditional probabilities on null events.

**PROVED UNDER ASSUMPTIONS — non-identifiability from aggregate answer success.**
If sufficiency is unobserved and the only observation is an answer pass rate
`r` with `0 < r < 1`, that rate does not uniquely determine retrieval sufficiency.
Construct two mechanisms:

| Mechanism | P(E) | Target succeeds given sufficient evidence | Succeeds otherwise |
| --- | ---: | ---: | ---: |
| A | 1 | r | irrelevant |
| B | r | 1 | 0 |

Both produce `P(Y)=r`. A retrieves sufficient evidence on every task and has an
imperfect target; B has an ideal target when retrieval succeeds. Thus the same
answer statistic can arise with different retrieval failures. This is a statement
about the specified observation, not a claim that raw tasks or source cannot
supply additional information. An independent sufficiency oracle would change
the assumptions.

**EMPIRICAL — distinction needed in this project.** Whole-code-span retention
and exact-JSON answer success are separate measured variables. The former is not
the event `E`: equivalent evidence might occur in documentation, and additional
dependencies may still be missing. Cycle 19's manual addition illustrates that
representation problem. Its missing transport outcomes further limit estimates;
they must not be substituted for observed target failures.

**CONJECTURE — diagnostic value of privileged source.** Comparing ordinary
retrieval with manually chosen definitions, and holding each input fixed across
target configurations, may locate failures worth repairing. Neither control
proves sufficiency. Their source spans, model settings, output allowances and
missing outcomes must remain explicit. Cycle 20 tests this conjecture on known
questions; it cannot independently validate a new retrieval method.

**CONJECTURE — a next representation challenger.** Deterministically extracted
declarations and relationships may be easier for a target to use than raw source.
This is untested. Derived facts would require source provenance and stated static
analysis assumptions, and must not be mislabeled as verbatim evidence. No new
representation or graph subsystem is promoted by this note.

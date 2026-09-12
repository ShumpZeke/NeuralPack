# Budget and message-boundary counterexamples

These statements concern the older prompt client. They do not establish answer
quality, target-tokenizer bounds, or retrieval superiority for the compiled runtime.

**FALSIFIED:** Summing the legacy token estimates of selected blocks is sufficient
to enforce the same estimate on their joined representation. Eight copies of the
seven-character string `retry=7` each estimate to one token under floor(chars/3.8).
The sum is eight. Joining them with seven two-character separators produces
70 characters, whose estimate is 18. The regression demonstrates the old selector
returning this output under a budget of eight.

**PROVED UNDER ASSUMPTIONS:** For this fixed estimator, if every acceptance step
computes the estimate from the total character length including all inserted
separators and accepts only at or below B, the accepted seed representation has
estimated cost at or below B. This follows by induction on accepted steps. The
estimator must remain fixed and no text may be appended without another check.
This does not bound an external model's actual tokenizer. The retriever separately
checks dependency expansion and an attached query, and declares full fallback if
the joined result exceeds the cap.

**FALSIFIED:** Non-empty optimized user text proves that source context survived.
A long current question can occupy that text after every source message is
removed. The old guard accepted this counterexample. Source-presence checks must
exclude the same original query from both representations.

**FALSIFIED:** Finding the query somewhere in the optimized conversation proves
that the current query survived. A copy in an earlier assistant message can pass
that test while the latest user request is replaced. Likewise, extracting only
the last paragraph discards earlier constraints before the comparison starts.
The regressions require the complete latest query in its current user slot,
preserving whitespace. Ambiguous single-message input is kept in full.

**EMPIRICAL:** The new regressions fail on the pre-repair client and pass after
the repairs; the XML evidence and mutation results are bound in the cycle record.
These checks establish specific invariants. They do not prove that the remaining
source contains every fact needed for an answer. The dependency-empty-seed negative
result in `INDEPENDENT_MATH_AUDIT.md` continues to apply.

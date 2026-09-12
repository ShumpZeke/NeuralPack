# Seed research after the optional-client repair

Reviewed 2026-09-07. These are research directions, not product claims.

**CONJECTURE:** Verbatim clause retrieval plus the original query can recover
multiple required source regions more reliably than one ranking of a long
question. A deterministic splitter must preserve quoted strings, dotted symbols,
version numbers and negative constraints. It must retain the original question
unchanged for the target model. Extra channels must share the final evidence cap.
This is not semantic query understanding or an LLM-generated decomposition.

**EMPIRICAL (external, not reproduced here):** Verbose-query reduction, weighting,
reformulation and segmentation have a substantial information-retrieval literature.
The [Gupta and Bendersky tutorial](https://www.microsoft.com/en-us/research/publication/information-retrieval-with-verbose-queries/)
motivates testing these simpler methods before another larger model. Its results
do not establish a benefit on NeuralPack's repository questions.

**EMPIRICAL (external, not reproduced here):**
[GRITHopper](https://aclanthology.org/2026.eacl-long.5.pdf) uses a trained 7B encoder
for iterative multi-hop dense retrieval, with offline passage encoding and one
forward pass per hop. Training uses generative objectives; that alone does not
make the embedding retrieval path generative. It is a possible future challenger,
not a reason to add a large default dependency. Inspect the actual inference path
before assuming stop/rerank behavior is also non-generative.

**EMPIRICAL (external preprint, not reproduced here):**
[Verification Without Sufficiency](https://arxiv.org/html/2608.00585v1) reports that
individually filtering passages can discard later-hop evidence and examines
sub-question-conditioned verification. Its gold-decomposition diagnostic is
privileged information. Its learned decomposer is generative. Neither is a
ready-made strict-mode solution. The claim that filtering cannot work in general
must not be imported as a theorem about all retrieval systems.

Candidate experiment: original BM25, weighted BM25, original plus verbatim clauses
using reciprocal-rank fusion, and a clause-coverage allocation challenger. Sweep
identical 512/2,048/8,192 estimated-token budgets; charge all selected passages and
separators. Keep graph expansion disabled. Reuse the frozen 28 cases as development
controls and add new source behaviors frozen before retrieval. Measure source
coverage locally, then actual answers only after source/provenance/cap checks pass.
No guaranteed sufficiency and no score-to-probability interpretation.

Attacks to run: quoted periods and semicolons, abbreviations, version numbers,
negative conditions, repeated clauses, an empty/meaningless clause, evidence
needed by two clauses, popular distractors matching one clause, and a relevant
term absent from every original clause. Compare complete evidence and answer
success; improvements in mean partial coverage alone do not justify promotion.

Additional observed implementation questions: the shared query-term helper lowercases
before attempting CamelCase splitting; the older selector stores k1/b without
passing them to BM25 and retains an unused escalation_floor. Existing experimental
camel expansion already has prior results, so reproducing that proposal is not a
new discovery or proof that changing the shared default improves retrieval.
Keep these separate from the frozen cycle-17 measurement snapshot.

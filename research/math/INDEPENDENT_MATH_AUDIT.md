# Independent Mathematical Audit

**Audit date:** 2026-09-05
**Subject:** `research/math/theorems.md` (Theorems 1–3, Corollary 1.1) and the derived claims
"exact Pareto knee" and "Minimum Sufficient Context".
**Method:** Each theorem was re-derived from its stated hypotheses. Counterexamples were
constructed and executed where the statement admitted them. Formal language was not accepted as
evidence of formal content.

**Labels:** PROVED · VALID UNDER EXPLICIT ASSUMPTIONS · CONJECTURE · EMPIRICAL OBSERVATION ·
FALSE / COUNTEREXAMPLE FOUND

---

## Summary

| # | Claim | Verdict |
|---|---|---|
| T1 | MSC is NP-**complete** | **VALID UNDER EXPLICIT ASSUMPTIONS** — NP-hardness holds; NP-membership never established |
| T2 | Independent Top-K "guarantees 0% accuracy" | **FALSE / COUNTEREXAMPLE FOUND** (three independent refutations) |
| T3 | Transitive closure gives 100% critical-context recall | **VALID BUT VACUOUS** as stated; **FALSE** as a claim about the implementation |
| T3b | "Approximation ratio bounded by the density of G" | **UNSUPPORTED** — no ratio defined, no proof attempted |
| — | "Exact Pareto knee" | **UNSUPPORTED** — no frontier was ever enumerated |
| — | MSC efficiency > 100% | **Measurement error** — granularity mismatch, demonstrated below |

One genuinely useful negative result emerges from the audit and is stated as **Proposition A**
(§5): graph expansion cannot repair a failed seed set. It is the strongest true statement in this
area and it constrains NeuralPack's own architecture, not just its competitors'.

---

## 1. Theorem 1 — NP-completeness of Minimum Sufficient Context

### Restated claim
Given context universe `C = {c_1..c_N}`, query `Q`, and verification oracle `V(S) ∈ {0,1}`,
deciding whether `∃ S ⊆ C, |S| ≤ K, V(S) = 1` is NP-complete.

### What the proof establishes
The reduction from Minimum Set Cover is **correct**. Map each set `F_i` to a block `c_i` of unit
token cost; define `V(S) = 1` iff the union of elements listed in `S` equals `U`. Then
`S` is a witness of size ≤ K iff `{F_i : c_i ∈ S}` is a set cover of size ≤ K. The construction is
polynomial. **NP-hardness holds.** ✔

### What the proof does not establish
**NP-membership is never argued**, and the statement as written does not support it. Membership in
NP requires that a certificate `S` be *verifiable in polynomial time*. The theorem quantifies over
an arbitrary oracle `V`. For arbitrary `V`, the problem lies in NP^V (NP relative to the oracle),
not NP. NP-completeness therefore requires an additional hypothesis that is absent:

> **(H1)** `V` is given explicitly as part of the input and is computable in time polynomial in
> `|C|` and `|Q|`.

Under (H1) the problem is NP-complete. Without it, only NP-hardness survives.

### The gap that matters in practice
Three further properties hold in the reduction but fail for the intended application, where `V` is
"an LLM answers `Q` correctly":

1. **Determinism.** The real `V` is stochastic: `V(S) ~ Bernoulli(p_S)`. A decision problem over a
   random predicate is not well-posed; the honest formulation is chance-constrained
   (`∃S : Pr[correct | S] ≥ 1 − δ`), which is a different problem and is not addressed.
2. **Monotonicity.** In the reduction, adding blocks never hurts. For an LLM this is false —
   additional context demonstrably degrades answers (distraction, lost-in-the-middle). So the
   reduction's oracle is a strict special case, and the sufficiency predicate is not monotone in
   general.
3. **Explicit representation.** The LLM is not a poly-time-evaluable predicate given in the input.

### Verdict
**VALID UNDER EXPLICIT ASSUMPTIONS.**

Corrected statement:

> **Theorem 1′.** Let `V` be a deterministic, monotone sufficiency predicate given explicitly and
> computable in polynomial time. Then deciding whether there exists `S ⊆ C` with token cost ≤ B and
> `V(S) = 1` is NP-complete. Without (H1) the problem is NP-hard; for stochastic `V` the decision
> problem is not well-posed and must be restated as a chance constraint.

The paper should say **"MSC is NP-hard, and NP-complete for the deterministic explicitly-given
oracle variant"** — not "MSC is NP-complete."

### A constructive consequence the project should claim but does not
If the sufficiency predicate is monotone and submodular, greedy coverage attains the standard
`(1 − 1/e)` / `ln n` guarantee, and Set Cover is hard to approximate better than `(1−o(1))·ln n`.
That is a real, citable positive result. **It does not apply to the implemented selector.**
`InformationGainSelector` greedily maximizes `BM25(c)/√tokens(c)` — a *modular* score with a hard
absolute cutoff — which is not a submodular coverage objective and carries no approximation
guarantee. Corollary 1.1 ("must rely on approximations, greedy heuristics, or structural
exploitation") is therefore true but the code does not cash it in.

---

## 2. Theorem 2 — "Failure of independent Top-K" — **FALSE AS WRITTEN**

### Restated claim
For a call chain `v_0 → … → v_d` with the critical constant in `v_d`, and any independent score
`f`: *"for any K < |V|, Top-K retrieval selects distractors, omits `v_d`, and **guarantees 0% task
accuracy**."*

The failure is in the universal quantifier and the word *guarantees*. The existential preamble
("there exist valid codebases where…") is fine; the conclusion drawn from it is not.

### Counterexample 1 — large K with ties
Let `|V| = 12`: chain nodes `v_0..v_3` plus 8 distractors. Take `K = 11 < |V|`. Top-11 omits exactly
one node. The proof requires `f(v_d, Q)` to be uniquely minimal, but in any realistic corpus
multiple irrelevant blocks also score 0 (no query term occurs in them). With `m > 1` nodes tied at
the minimum, Top-K must break ties, and under any tie-break rule that is not adversarially chosen
against `v_d` (stable-by-index, random, recency), `Pr[v_d retrieved] ≥ 1/m > 0`.
A claim of the form *"guarantees 0%"* is refuted by any instance with positive probability of
retrieval. **The theorem states no tie-breaking hypothesis, so this case is admitted by it.**

### Counterexample 2 — the proof contradicts its own construction
The proof sets `Q = "What is the return value of function v0?"` and
`v_d = "def vd(): return 42"`, then asserts `f(v_d, Q) = 0` "because `v_d` shares no lexical or
semantic overlap with `Q`". But the token **`return` occurs in both**. Under BM25 with any
non-degenerate IDF, `f(v_d, Q) > 0`. The proof's own example violates its own premise.

This is not a technicality — it is exactly what happens in practice. In my adversarial run
(`INDEPENDENT_AUDIT.md` §4.2, case A1), an 8-hop chain terminating in `return 8731` **was**
retrieved, precisely via the shared token `return`, with no graph traversal required.

### Counterexample 3 — recall ≠ accuracy
Even granting that `v_d` is never retrieved, "0% task accuracy" does not follow:
- If the answer space is finite and small (boolean, enumerated status codes), a model guesses
  correctly with probability ≥ `1/|A| > 0`.
- If the constant is a well-known default (`timeout = 30`, `port = 8080`), parametric knowledge
  yields correct answers with zero retrieved evidence.

The theorem conflates **critical-evidence recall** with **task accuracy**. These are distinct
metrics and the project's own reporting confuses them elsewhere.

### Counterexample 4 — queries naming the dependency
If `Q` mentions intermediate or terminal symbols ("what does `v0` return, via `vd`?"), then
`f(v_d, Q) > 0` by direct name match and `v_d` may enter Top-K for modest `K`.

### Verdict
**FALSE / COUNTEREXAMPLE FOUND.**

### Strongest provable replacement

> **Theorem 2′ (existence of retrieval failure for structure-blind scorers).**
> Let `f(c, Q)` depend only on block content and the query, not on graph structure. Then for every
> `K ≥ 1` there exists an instance `(G, Q, {c_i})` with `|V| > K` such that the block containing the
> answer-critical constant is ranked strictly below `K` distractor blocks under `f`, and hence is
> not retrieved by Top-K.
>
> *Proof sketch.* Construct `K` distractors that maximize lexical overlap with `Q` and a needle
> block sharing no token with `Q`; strict ranking follows. ∎

This is an **existence** result about **recall**, requires strict (untied) ranking, and says nothing
about accuracy being zero. It is also, honestly, a restatement of the well-known observation that
lexical retrieval misses semantically-required evidence — it is not novel, and should not be
presented as such.

### The uncomfortable corollary for NeuralPack
Theorem 2′ applies to NeuralPack's **own** pipeline. Its seed selection is structure-blind
(BM25-scored `InformationGainSelector`); the graph is only consulted *afterwards*, to expand from
seeds. Executed instance (`/tmp/isolate_graph.py`): needle with zero query overlap, reachable only
through a 2-hop import chain — **selector returned 0 of 43 blocks at every depth 0,1,2,3,5**, and
the needle was lost. NeuralPack fails its own impossibility theorem's setup.

---

## 3. Theorem 3 — 100% critical-context recall from transitive closure

### The proof is circular
Premise: *"If all causal computation paths for `Q` originate in `V_Q` and are statically expressible
in `G`…"*. Conclusion: *"…every required node lies in `Closure(V_Q)`, so missed-context rate is 0."*

This is valid but **vacuous**: the premise asserts that every critical node is reachable from the
seeds, and the conclusion restates that reachable nodes are in the reachable set. It carries no
information about whether the premise ever holds.

### Every assumption fails in the implementation

| Assumption | Status in code | Evidence |
|---|---|---|
| Correct seed set `V_Q` | Seeds come from a BM25 threshold; can be **empty** | `kept=0/43` at all depths |
| True transitive closure | `compute_transitive_closure` is a **bounded BFS** with `max_depth`; planner default `dependency_depth=1` | `graph_slicer.py:53-66`, `planner.py:29` |
| Depth ≥ longest critical path | 8-hop chain vs depth 1 → needle lost at budget 100 | `/tmp/probe_selector.py` |
| No budget truncation | Closure runs **after** budget selection and never re-checks | budget 100 → 113/135/156/192 tokens emitted |
| Static analysis soundness | `importlib.import_module(var)`, `getattr`, reflection, DI, string dispatch, config-driven wiring are all invisible | not modelled |

A bounded-depth BFS is not a transitive closure. Calling it one is the error that makes the theorem
look applicable to the code.

### Verdict
**VALID BUT VACUOUS** as a mathematical statement; **FALSE** as a claim about this implementation.
The empirical claim "100% critical-context recall" is refuted by executed counterexample.

### Corrected statement

> **Theorem 3′.** Let `D` be the traversal depth and `B` the token budget. If
> (a) every answer-critical node is reachable in the static graph `G` from some seed in `V_Q`,
> (b) `D ≥ max` path length from `V_Q` to any critical node, and
> (c) no budget truncation removes a node on such a path,
> then bounded-depth traversal retrieves all critical nodes.
>
> Each of (a), (b), (c) is violated by the current implementation under its default configuration.

### Theorem 3b — "approximation ratio bounded by the density of `G`"
No ratio is defined, no density measure is specified, and no derivation is attempted. This is a
sentence with the shape of a theorem and none of the content. **UNSUPPORTED** — delete or prove.

---

## 4. "Exact Pareto knee" — UNSUPPORTED

To claim an *exact* knee one must (i) enumerate the achievable (token-cost, quality) frontier over a
configuration family, (ii) show no lower-cost configuration attains equivalent quality, and (iii)
identify maximum curvature. None of this exists. The available evidence is a 6-row ablation table —
**two rows of which toggle dead flags** (`enable_dedup`, `enable_prefix_opt` are never read; see
`INDEPENDENT_AUDIT.md` §3.1), leaving four effective points, with quality measured against an
echoing mock provider.

Four points do not determine a frontier, and "exact" is unwarranted regardless of count. The
defensible phrasing is **"an empirical operating point"**, with no knee claimed.

---

## 5. Proposition A — the one result worth keeping

The audit produced a true, non-obvious, architecturally consequential statement:

> **Proposition A (seed-limited reachability).** Let `Seed(Q) ⊆ V` be produced by a structure-blind
> scorer and `Closure_D(·)` be bounded-depth graph expansion. Then for every depth `D`,
> `Closure_D(Seed(Q)) = ∅` whenever `Seed(Q) = ∅`, and more generally
> `Closure_D(Seed(Q))` contains a critical node `u*` only if some seed lies within distance `D` of
> `u*`. Graph expansion cannot repair a failed seed set.
>
> *Proof.* Immediate from the definition of reachability from a set; expansion is monotone in its
> seed argument and `Closure_D(∅) = ∅`. ∎

Trivial to prove, and it is the binding constraint on this architecture. It predicts the observed
failure exactly (`kept=0/43`, needle lost at all depths) and implies the correct fix: **recall
depends on seed recall, not traversal depth.** Any real improvement must attack seeding —
calibrated seed-set prediction, query expansion, symbol-table anchoring, or uncertainty-bounded
expansion that *widens* seeds when confidence is low. Increasing `dependency_depth` cannot help,
which is consistent with the ablation showing depth 0 and depth 1 producing identical results.

This is a negative result. Per the brief, that makes it more valuable than a false breakthrough.

---

## 6. MSC measurement — diagnosis and exhaustive verification

### The >100% efficiency is a granularity error
Reported: `overall_context_efficiency_pct` of **152.11 / 154.09 / 154.09** (MSC holdouts) and
**118.91%** on an individual live task. Efficiency = MSC tokens ÷ NeuralPack tokens. The numerator
is an *uncompressed block-level* selection; the denominator is *line-level compressed* output.
Different granularities ⇒ the ratio is not bounded by 1 and has no lower-bound meaning.

### Exhaustive verification at matched granularity
I brute-forced the true minimum over all block subsets on instances small enough to enumerate, using
a deterministic sufficiency predicate (subset must contain all required needles):

| Case | Exact MSC (tokens) | NeuralPack (tokens) | Ratio | Sufficient? |
|---|---:|---:|---:|:--:|
| C1 single needle, 6 distractors | 10 | 10 | **1.00×** | Yes |
| C2 two required needles, 5 distractors | 16 | 17 | **1.06×** | Yes |

Two conclusions:

1. **Ratio ≥ 1.00 in both cases, as a valid lower bound requires.** This confirms the >100%
   figures are a measurement artifact, not a genuine sub-minimal result. When numerator and
   denominator share granularity, the anomaly disappears.
2. **At block granularity on easy instances the retriever is near-optimal** (exactly optimal on C1).
   That is a real, if modest, positive finding — and it is the correct way to report MSC efficiency.

### Required terminology fix
Exact minimality is neither computed nor proven at scale. The quantity should be called
**Empirical MSC** (or Approximate MSC), defined explicitly as *the smallest block-level subset found
by exhaustive or greedy search under a stated sufficiency predicate*, and compared **only** against
block-level selections. Reproduction: `/tmp/msc_exact.py`.

---

## 7. Recommendations

1. Retitle Theorem 1 to **NP-hardness**; state (H1) explicitly for the completeness variant; add the
   stochastic/non-monotone caveat for the LLM setting.
2. Delete Theorem 2 and replace with **Theorem 2′**; drop "guarantees 0% accuracy" entirely; note
   that it constrains NeuralPack's own seeding stage.
3. Replace Theorem 3 with **Theorem 3′**, and stop describing bounded-depth BFS as transitive
   closure. Retract "100% critical-context recall".
4. Delete Theorem 3b unless a density-parameterized ratio is actually derived.
5. Retract "exact Pareto knee"; say "empirical operating point".
6. Adopt **Empirical MSC** with matched granularity; keep the exhaustive small-case harness as a
   permanent test.
7. Promote **Proposition A** to the front of the mathematical narrative and let it drive the
   research agenda — seed recall, not traversal depth, is the binding constraint.
8. If a submodular, monotone sufficiency surrogate can be defined, the `ln n` / `(1 − 1/e)` greedy
   guarantee becomes claimable — but only after the selector is rewritten as greedy coverage. The
   current `BM25/√cost` objective with an absolute `0.05` cutoff supports no guarantee.

"""Query-conditioned block selection with scale-aware stopping.

Post-audit rewrite. The previous implementation stopped its greedy loop on an
absolute constant::

    if best_candidate == -1 or best_efficiency <= 0.05:
        break

``efficiency`` is ``BM25(c) / sqrt(tokens(c))`` -- a scale-dependent quantity.
BM25 magnitudes shrink as a term spreads across a corpus and ``sqrt(cost)`` grows
with block size, so on large redundant contexts the best candidate routinely fell
under the constant and the loop returned an EMPTY selection on its first
iteration. Callers then shipped a context-free prompt and scored it as a ~99%
token reduction.

Two changes fix that class of bug:

1. Stopping is **relative to the observed score distribution**, never an absolute
   constant (see :class:`StoppingStrategy`).
2. The selector reports *why* it stopped. An empty selection is returned as an
   explicit :attr:`SelectionOutcome.seed_failed` signal rather than as a
   legitimate-looking empty result, so the planner can fall back instead of
   silently destroying the context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Dict, List, Sequence, Set, Tuple

from .analyzer import estimate_tokens, estimate_tokens_from_length
from .bm25 import BM25Scorer

# Selection strategies benchmarked in ``benchmarks/selector_bench.py``.
STOPPING_STRATEGIES = ("relative", "budget_fill", "elbow", "absolute_legacy")

DEFAULT_STRATEGY = "relative"


@dataclass
class SelectionOutcome:
    """Result of a selection pass, including the signals a caller needs to
    decide whether the selection can be trusted."""

    kept_indices: List[int]
    total_candidates: int
    selected_tokens: int
    budget: int
    strategy: str
    #: True when no block could be scored above the noise floor. The caller MUST
    #: treat this as a retrieval failure and fall back, never as a valid empty
    #: context.
    seed_failed: bool = False
    #: Highest raw relevance score observed (0.0 when nothing matched).
    top_score: float = 0.0
    #: Separation between the best and the next-best unselected candidate.
    #: Small margins indicate an ambiguous selection.
    margin: float = 0.0
    #: Fraction of query terms covered by the selected blocks.
    query_term_coverage: float = 0.0
    reason: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)

    def as_stats(self) -> Dict[str, Any]:
        return {
            "total_candidates": self.total_candidates,
            "selected_count": len(self.kept_indices),
            "selected_tokens": self.selected_tokens,
            "budget": self.budget,
            "strategy": self.strategy,
            "seed_failed": self.seed_failed,
            "top_score": round(self.top_score, 6),
            "margin": round(self.margin, 6),
            "query_term_coverage": round(self.query_term_coverage, 4),
            "reason": self.reason,
            **self.stats,
        }


from ..pack.select import STOPWORDS, _query_terms, _content_terms as content_terms


class InformationGainSelector:
    """Greedy selection maximizing relevance per token under a budget.

    ``strategy`` controls the stopping rule:

    ``relative``
        Keep candidates whose efficiency is at least ``rel_floor`` times the best
        observed efficiency. Scale-free: unaffected by the absolute magnitude of
        BM25 scores.
    ``budget_fill``
        Keep taking positively-scored candidates until the budget is exhausted.
        Maximum recall, highest token use.
    ``elbow``
        Stop at the largest relative drop in the sorted efficiency curve.
    ``absolute_legacy``
        The audited constant-threshold behaviour. Retained ONLY so the benchmark
        can quantify the regression; never use in production.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        strategy: str = DEFAULT_STRATEGY,
        rel_floor: float = 0.25,
        min_keep: int = 1,
        enable_escalation: bool = False,
        escalation_floor: float = 0.0,
    ):
        if strategy not in STOPPING_STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}; expected one of {STOPPING_STRATEGIES}")
        self.k1 = k1
        self.b = b
        self.strategy = strategy
        self.rel_floor = rel_floor
        self.min_keep = max(0, min_keep)
        #: Explicit opt-in to experimental local embedding fusion. The default
        #: does not even probe a model. Missing weights retain lexical retrieval.
        self.enable_escalation = enable_escalation
        self.escalation_floor = escalation_floor
        #: RRF damping constant. 60 is the standard value from the TREC
        #: reciprocal-rank-fusion literature.
        self.rrf_k = 60
        #: Minimum top cosine similarity for the embedding ranking to be trusted.
        #: Below this the dense signal is discarded so a nonsense query still
        #: produces a seed failure (and therefore a safe full-context fallback)
        #: rather than a confident-looking arbitrary selection.
        self.dense_floor = 0.35

    # ------------------------------------------------------------------
    def select(
        self,
        blocks: List[Dict[str, Any]],
        query: str,
        dependency_edges: Dict[int, Set[int]],
        token_budget: int = 8000,
    ) -> SelectionOutcome:
        if type(token_budget) is not int or token_budget <= 0:
            raise ValueError('token_budget must be a positive integer')
        n = len(blocks)
        if n == 0:
            return SelectionOutcome([], 0, 0, token_budget, self.strategy,
                                    seed_failed=True, reason="no candidate blocks")

        raw_docs = [b["text"] for b in blocks]
        scorer = BM25Scorer(raw_docs)
        base_scores = [scorer.score(query, i) for i in range(n)]

        # Anchor boost: blocks named in the query are near-certain seeds.
        q_lower = query.lower()
        max_base = max(base_scores) if base_scores else 0.0
        anchor_unit = max_base if max_base > 0 else 1.0
        for i, blk in enumerate(blocks):
            name_clean = blk.get("name", "").lower().replace("#", "").strip()
            if name_clean and name_clean in q_lower:
                base_scores[i] += anchor_unit * 2.0

        # Identifier-level fallback scoring: if BM25 found nothing, look for
        # query sub-tokens appearing literally in block text. This rescues the
        # snake_case / camelCase mismatch that produced empty selections.
        terms = _query_terms(query)
        if max(base_scores) <= 0.0 and terms:
            for i, blk in enumerate(blocks):
                low = blk["text"].lower()
                hits = sum(1 for t in terms if t in low)
                if hits:
                    base_scores[i] = hits / max(1, len(terms))

        # ---- Lexical/semantic fusion ----------------------------------
        # Experimental rank fusion. Old headline retention claims were
        # withdrawn after the independent audit and corrected compiled-product
        # evaluation; see EVOLUTION_LOG.md. A nonzero lexical score can still
        # rank the wrong source, but this fusion has no general quality proof.
        escalated = False
        if self.enable_escalation:
            from .embedding import get_backend

            dense = get_backend().score_blocks([b["text"] for b in blocks], query)
            # A bi-encoder always returns SOME ranking, even for a nonsense
            # query. Without a floor, fusion would silently destroy the
            # seed-failure signal that drives the safety fallback. The floor is
            # an uncalibrated experimental heuristic, not a probability or a
            # reliable detector of sufficient evidence on new workloads.
            if dense is not None and max(dense) < self.dense_floor:
                dense = None
            if dense is not None:
                lex_informative = max(base_scores) > 0.0
                lex_rank = {i: r for r, i in enumerate(
                    sorted(range(n), key=lambda i: -base_scores[i]))}
                dns_rank = {i: r for r, i in enumerate(
                    sorted(range(n), key=lambda i: -dense[i]))}
                k = self.rrf_k
                if lex_informative:
                    fused = [1.0 / (k + lex_rank[i]) + 1.0 / (k + dns_rank[i]) for i in range(n)]
                else:
                    # Lexical carries no signal (every score zero), so its ranking
                    # is arbitrary. Fusing it would dilute the only real signal
                    # available; defer entirely to the embedding ranking.
                    fused = [1.0 / (k + dns_rank[i]) for i in range(n)]
                # RRF values live in a narrow band (~1/k to ~2/k), which would
                # flatten the score distribution and defeat the relative
                # stopping rule -- every block would look equally good and
                # nothing would be pruned. Rescale to [0, 1] so the stopping
                # rule keeps its discrimination.
                lo, hi = min(fused), max(fused)
                span = hi - lo
                fused = [((f - lo) / span) if span > 0 else 1.0 for f in fused]

                # Preserve anchor dominance: a block named in the query stays on
                # top regardless of fusion.
                for i, blk in enumerate(blocks):
                    name_clean = blk.get("name", "").lower().replace("#", "").strip()
                    if name_clean and name_clean in q_lower:
                        fused[i] += 2.0
                base_scores = fused
                escalated = True

        top_score = max(base_scores) if base_scores else 0.0
        if top_score <= 0.0:
            # Nothing in the context resembles the query, lexically or
            # semantically. This is a SEED FAILURE, not an empty context: the
            # caller must fall back to the full context.
            return SelectionOutcome(
                [], n, 0, token_budget, self.strategy,
                seed_failed=True, top_score=0.0,
                reason="no block scored above zero for this query",
                stats={"escalated": escalated},
            )

        costs = [max(1, estimate_tokens(b["text"])) for b in blocks]
        selected: Set[int] = set()
        current_tokens = 0
        current_chars = 0
        efficiencies: List[float] = []

        while True:
            best_i, best_eff = -1, -1.0
            for i in range(n):
                if i in selected:
                    continue
                gain = base_scores[i]
                for s in selected:
                    if i in dependency_edges.get(s, set()) or s in dependency_edges.get(i, set()):
                        gain += anchor_unit * 1.5
                eff = gain / math.sqrt(costs[i])
                joined_chars = current_chars + len(raw_docs[i]) + (2 if selected else 0)
                fits = estimate_tokens_from_length(joined_chars) <= token_budget
                if gain > 0 and eff > best_eff and fits:
                    best_eff, best_i = eff, i

            if best_i == -1:
                break
            if not self._should_continue(best_eff, efficiencies, len(selected)):
                break

            efficiencies.append(best_eff)
            current_chars += len(raw_docs[best_i]) + (2 if selected else 0)
            selected.add(best_i)
            current_tokens = estimate_tokens_from_length(current_chars)
            if current_tokens >= token_budget:
                break

        # A minimum count cannot override the caller's budget. Return an explicit
        # failure so a caller can request more budget or retain the raw context.
        if not selected:
            return SelectionOutcome([], n, 0, token_budget, self.strategy,
                                    seed_failed=True, top_score=top_score,
                                    reason='no positive seed fits the budget or stopping policy',
                                    stats={'escalated': escalated})

        kept = sorted(selected)
        remaining = [base_scores[i] for i in range(n) if i not in selected]
        margin = (min(base_scores[i] for i in kept) - max(remaining)) if kept and remaining else 0.0

        kept_text = " ".join(blocks[i]["text"] for i in kept).lower()
        cov_terms = content_terms(query)
        # Coverage is measured only over terms that actually occur somewhere in
        # the candidate set. A term present nowhere cannot be evidence of a bad
        # selection -- it is simply absent from the corpus.
        all_text = " ".join(b["text"] for b in blocks).lower()
        present = [t for t in cov_terms if t in all_text]
        coverage = (sum(1 for t in present if t in kept_text) / len(present)) if present else 1.0

        return SelectionOutcome(
            kept_indices=kept,
            total_candidates=n,
            selected_tokens=current_tokens,
            budget=token_budget,
            strategy=self.strategy,
            seed_failed=False,
            top_score=top_score,
            margin=margin,
            query_term_coverage=coverage,
            reason=f"selected {len(kept)}/{n} blocks via {self.strategy}"
                   + (" (escalated to embeddings)" if escalated else ""),
            stats={"escalated": escalated},
        )

    # ------------------------------------------------------------------
    def _should_continue(self, best_eff: float, history: Sequence[float], n_selected: int) -> bool:
        if n_selected < self.min_keep:
            return True
        if best_eff <= 0.0:
            return False

        if self.strategy == "relative":
            return not history or best_eff >= self.rel_floor * max(history)
        if self.strategy == "budget_fill":
            return True
        if self.strategy == "elbow":
            if len(history) < 2:
                return True
            return best_eff >= 0.5 * history[-1]
        if self.strategy == "absolute_legacy":
            return best_eff > 0.05
        return True

    # ------------------------------------------------------------------
    def rank_blocks_with_interactions(
        self,
        blocks: List[Dict[str, Any]],
        query: str,
        dependency_edges: Dict[int, Set[int]],
        token_budget: int = 8000,
    ) -> Tuple[List[int], Dict[str, Any]]:
        """Backwards-compatible wrapper returning ``(indices, stats)``.

        Prefer :meth:`select`, which exposes the ``seed_failed`` signal.
        """
        outcome = self.select(blocks, query, dependency_edges, token_budget)
        return outcome.kept_indices, outcome.as_stats()

"""Hard safety invariants and evidence-backed risk assessment.

Introduced by the post-audit repair. The audited optimizer could convert a
context-bearing request into a bare question and score that as a ~99% token
reduction, because:

* the seed selector could return an empty set (absolute threshold miss),
* nothing checked that the emitted prompt still carried the evidence, and
* ``quality_risk`` was a hardcoded constant unrelated to what was removed.

This module supplies the two missing pieces: **invariants** that must hold on
every emitted prompt, and a **risk assessment derived from observable signals**
which is explicitly labelled uncalibrated rather than dressed up as a
probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence

from .analyzer import estimate_tokens

#: A prompt whose context body is at or below this many tokens is treated as
#: carrying no evidence at all.
EMPTY_CONTEXT_TOKENS = 8

#: Patterns whose presence means static analysis cannot see the real control
#: flow, so dependency expansion is unsound for that context.
DYNAMIC_INDIRECTION = re.compile(
    r"importlib\.import_module|__import__\s*\(|getattr\s*\(|globals\s*\(\s*\)\s*\[|"
    r"locals\s*\(\s*\)\s*\[|eval\s*\(|exec\s*\(|setattr\s*\(",
)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

@dataclass
class InvariantReport:
    """Outcome of checking an optimized prompt against the hard invariants."""

    ok: bool
    violations: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.ok


_QUERY_MARKER = re.compile(r"(?:^|\n\n)(?:QUESTION|Question|Query):[ \t]?(.*)\Z", re.DOTALL)


def _context_body(messages: Sequence[Dict[str, str]], query: Optional[str] = None) -> str:
    """Exclude the current question when testing whether source evidence remains.

    The same original query must be supplied for both sides of the invariant.
    Otherwise removing its marker could make a long question look like evidence.
    This is a presence check, not a proof that every required fact was retained.
    """
    user = [m.get('content', '') for m in messages if m.get('role') == 'user']
    if not user:
        return ''
    query = extract_query(messages) if query is None else query
    last = user[-1]
    marker = _QUERY_MARKER.search(last)
    if marker and marker.group(1) == query:
        remainder = last[:marker.start()]
    elif query and query in last:
        start = last.rfind(query)
        remainder = last[:start] + last[start+len(query):]
    else:
        remainder = last
    return '\n'.join([*user[:-1], remainder])


def extract_query(messages: Sequence[Dict[str, str]]) -> str:
    """Preserve the whole latest user message rather than guessing its last paragraph.

    A single combined legacy prompt may use the explicit blank-line QUESTION:
    delimiter outside backtick fences. Ambiguous input is retained in full. In
    multi-message input, the latest user message is the complete current query.
    """
    user = [m.get("content", "") for m in messages if m.get("role") == "user"]
    if not user:
        return ""
    last = user[-1]
    if len(user) == 1:
        match = _QUERY_MARKER.search(last)
        if match and last[:match.start()].count('```') % 2 == 0:
            return match.group(1)
    return last


def check_invariants(
    original: Sequence[Dict[str, str]],
    optimized: Sequence[Dict[str, str]],
) -> InvariantReport:
    """Verify an optimized prompt is safe to dispatch.

    Invariants:

    1. **Context preservation** -- if the original carried a context body, the
       optimized prompt must still carry one. Deleting all evidence and calling
       it a token saving is the audited reward-hacking failure.
    2. **Query survival** -- the current user question must survive verbatim.
    3. **System-instruction survival** -- every system message must survive.
    """
    violations: List[str] = []

    original_envelopes = [{k: v for k, v in m.items() if k != 'content'} for m in original]
    optimized_envelopes = [{k: v for k, v in m.items() if k != 'content'} for m in optimized]
    if original_envelopes != optimized_envelopes:
        violations.append('message roles, order, count, or metadata changed')

    # Only user source content is eligible for this legacy planner's selection.
    # Tool linkage, assistant history and instruction roles have no equivalent
    # transformation defined here, so require exact per-slot preservation.
    for before, after in zip(original, optimized):
        if before.get('role') != 'user' and before != after:
            violations.append('non-user message changed')
            break

    orig_query = extract_query(original)
    orig_body = _context_body(original, orig_query)
    opt_body = _context_body(optimized, orig_query)
    orig_tokens = estimate_tokens(orig_body)
    opt_tokens = estimate_tokens(opt_body)

    if orig_tokens > EMPTY_CONTEXT_TOKENS and opt_tokens <= EMPTY_CONTEXT_TOKENS:
        violations.append(
            f"context destroyed: {orig_tokens} context tokens reduced to {opt_tokens}"
        )

    if orig_query:
        current_user = [m.get('content', '') for m in optimized if m.get('role') == 'user']
        if not current_user or orig_query not in current_user[-1]:
            violations.append("current user query did not survive optimization")

    orig_system = [m.get("content", "") for m in original if m.get("role") == "system"]
    opt_system = [m.get("content", "") for m in optimized if m.get("role") == "system"]
    for sys_msg in orig_system:
        if sys_msg and sys_msg not in opt_system:
            violations.append("system instruction did not survive optimization")
            break

    return InvariantReport(ok=not violations, violations=violations)


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

@dataclass
class RiskAssessment:
    """An ordinal risk estimate built from observable retrieval signals.

    ``score`` orders candidate plans by how much evidence they discarded and how
    confidently they selected. It is **not** a probability of failure: nothing
    here has been calibrated against measured answer accuracy. ``calibrated`` is
    therefore ``False`` and ``band`` reads ``uncalibrated``-prefixed, so no
    downstream report can quote it as "1.5% risk" the way the audited build did.
    """

    score: float
    band: str
    calibrated: bool
    signals: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "risk_score_ordinal": round(self.score, 4),
            "risk_band": self.band,
            "risk_calibrated": self.calibrated,
            "risk_signals": self.signals,
        }


def assess_risk(
    *,
    strategy: str,
    original_tokens: int,
    optimized_tokens: int,
    retrieval_stats: Optional[Dict[str, Any]] = None,
    context_text: str = "",
    seed_failed: bool = False,
    context_unchanged: bool = False,
) -> RiskAssessment:
    """Derive an ordinal risk score from real signals.

    Signals used (each in ``[0, 1]``, higher = riskier):

    ``dropped_fraction``
        Share of candidate blocks discarded.
    ``token_reduction``
        Share of prompt tokens removed. Aggressive reduction is the main way
        evidence is lost.
    ``seed_confidence``
        Inverse of query-term coverage in the retained context.
    ``margin``
        Small separation between kept and dropped blocks means the selection was
        nearly arbitrary.
    ``dynamic_indirection``
        Static dependency analysis is unsound when the context uses
        ``getattr`` / ``importlib`` / ``eval``, so expansion may miss edges.
    """
    stats = retrieval_stats or {}
    signals: Dict[str, Any] = {"strategy": strategy}

    if seed_failed:
        return RiskAssessment(
            score=1.0, band="uncalibrated:maximum", calibrated=False,
            signals={"seed_failed": True, "strategy": strategy,
                     "note": "seed stage found no query-relevant block"},
        )

    # Token reduction is deliberately NOT a risk term. Removing exact duplicates
    # or irrelevant blocks is the product's purpose; penalising compression per
    # se makes raw passthrough always win, which is merely a different way of
    # being useless. Risk models the chance that REQUIRED evidence was dropped.
    signals["token_reduction_observed"] = (
        round(max(0.0, (original_tokens - optimized_tokens) / original_tokens), 4)
        if original_tokens > 0 else 0.0
    )

    made_selection = "query_term_coverage" in stats
    dynamic = bool(DYNAMIC_INDIRECTION.search(context_text or ""))
    signals["dynamic_indirection"] = dynamic

    if context_unchanged:
        signals['context_unchanged'] = True
        return RiskAssessment(score=0.0, band='uncalibrated:passthrough', calibrated=False, signals=signals)

    if not made_selection:
        # Missing retrieval measurements do not establish preservation. The
        # ordinal maximum prevents an unmeasured transform from beating raw
        # passthrough under the default threshold; this is not a probability.
        signals['missing_selection_signals'] = True
        return RiskAssessment(score=1.0, band='uncalibrated:unknown', calibrated=False, signals=signals)

    coverage = float(stats.get("query_term_coverage", 1.0) or 0.0)
    signals["query_term_coverage"] = round(coverage, 4)
    coverage_risk = 1.0 - max(0.0, min(1.0, coverage))

    raw_margin = float(stats.get("margin", 0.0) or 0.0)
    top = float(stats.get("top_score", 0.0) or 0.0)
    norm_margin = max(0.0, min(1.0, (raw_margin / top) if top > 0 else 0.0))
    ambiguity = 1.0 - norm_margin
    signals["selection_margin_normalized"] = round(norm_margin, 4)

    score = 0.70 * coverage_risk + 0.30 * ambiguity
    if dynamic:
        # Static expansion cannot see these edges, so the dependency closure may
        # be missing a required node.
        score = min(1.0, score + 0.15)

    score = max(0.0, min(1.0, score))
    if score < 0.20:
        band = "uncalibrated:low"
    elif score < 0.50:
        band = "uncalibrated:moderate"
    else:
        band = "uncalibrated:high"

    return RiskAssessment(score=score, band=band, calibrated=False, signals=signals)

"""Formal Execution Plan IR and Cost-Based Query Optimizer for Context Execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PlanCandidate:
    name: str
    strategies: List[str]
    estimated_input_tokens: int
    estimated_output_tokens: Optional[int]
    estimated_cost_usd: Optional[float]  # hypothetical input-only quote
    estimated_latency_ms: Optional[float]
    quality_risk: float  # ordinal retrieval signal; not a probability of safety
    confidence: float
    explanation: str
    #: False means ``quality_risk`` is an ORDINAL score derived from retrieval
    #: signals, not a calibrated probability. Never report it as a percentage
    #: chance of failure -- that was an audited misreporting.
    risk_calibrated: bool = False
    risk_band: str = "uncalibrated"
    risk_signals: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlanIR:
    request_id: str
    workload_type: str
    query_intent: str
    candidates: List[PlanCandidate]
    chosen_candidate: PlanCandidate
    selection_reason: str
    quality_threshold: float = 0.95
    fallback_to_raw: bool = False
    #: Distinguishes *why* raw context was dispatched:
    #: ``none``  -- an optimized plan was used;
    #: ``cost_based_passthrough`` -- raw won on cost/quality grounds;
    #: ``safety`` -- an optimized plan violated a hard invariant and was rejected;
    #: ``seed_failure_partial`` -- seed retrieval failed for some message.
    fallback_kind: str = "none"
    invariant_violations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def strategies(self) -> List[str]:
        return self.chosen_candidate.strategies

    @property
    def original_tokens(self) -> int:
        return self.metadata.get("original_tokens", self.chosen_candidate.estimated_input_tokens)

    @property
    def optimized_tokens(self) -> int:
        return self.metadata.get("optimized_tokens", self.chosen_candidate.estimated_input_tokens)

    @property
    def tokens_avoided(self) -> int:
        return self.metadata.get("tokens_avoided", 0)

    @property
    def estimated_savings(self) -> Optional[float]:
        return self.metadata.get("estimated_savings_usd")

    @property
    def explanation(self) -> List[str]:
        return self.metadata.get("explanation", [self.chosen_candidate.explanation])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_yaml_str(self) -> str:
        """Readable YAML representation of the Execution Plan IR."""
        lines = [
            "execution_plan_ir:",
            f"  request_id: {self.request_id}",
            f"  workload_type: {self.workload_type}",
            f"  query_intent: {repr(self.query_intent)}",
            f"  quality_threshold: {self.quality_threshold}",
            f"  selected_plan: {self.chosen_candidate.name}",
            f"  selection_reason: {repr(self.selection_reason)}",
            f"  fallback_to_raw: {self.fallback_to_raw}",
            "  candidates:",
        ]
        for c in self.candidates:
            lines.extend([
                f"    - name: {c.name}",
                f"      strategies: {c.strategies}",
                f"      estimated_tokens: {c.estimated_input_tokens}",
                f"      estimated_input_cost_usd: {c.estimated_cost_usd if c.estimated_cost_usd is not None else 'N/A'}",
                f"      estimated_latency_ms: {c.estimated_latency_ms if c.estimated_latency_ms is not None else 'N/A'}",
                f"      confidence: {c.confidence:.3f}",
                f"      quality_risk: {c.quality_risk:.3f}",
            ])
        return "\n".join(lines)


class CostBasedPlanOptimizer:
    """
    Select among candidates passing an uncalibrated retrieval-score threshold.
    Use comparable input quotes when present, otherwise estimated input tokens.
    """
    def __init__(self, default_min_quality: float = 0.95):
        self.default_min_quality = default_min_quality

    def select_best_plan(
        self,
        candidates: List[PlanCandidate],
        min_quality: Optional[float] = None,
    ) -> Tuple[PlanCandidate, str]:
        threshold = min_quality if min_quality is not None else self.default_min_quality
        if not candidates:
            raise ValueError("Candidate plans cannot be empty")

        # Filter candidates meeting quality threshold
        qualified = [c for c in candidates if c.confidence >= threshold]
        if not qualified:
            # Fallback to safest candidate (highest confidence / lowest risk)
            safest = max(candidates, key=lambda c: c.confidence)
            return safest, f"No candidate met confidence threshold {threshold:.3f}; falling back to safest candidate ({safest.name})"

        if all(c.estimated_cost_usd is not None for c in qualified):
            best = min(qualified, key=lambda c: (c.estimated_cost_usd, c.estimated_input_tokens))
            return best, f"Selected lowest hypothetical input quote ({best.name}) passing retrieval score {threshold:.3f}"
        best = min(qualified, key=lambda c: (c.estimated_input_tokens, c.quality_risk))
        return best, f"Pricing unavailable; selected fewest estimated input tokens ({best.name}) passing retrieval score {threshold:.3f}"

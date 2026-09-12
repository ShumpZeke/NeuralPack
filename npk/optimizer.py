"""Explainable selection from measured costs, never invented latency constants."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class Option:
    name: str
    request_ms: float
    setup_ms: float = 0.0
    storage_bytes: int = 0
    compatible: bool = True
    quality_passed: bool = True
    evidence: str = ""
    p95_ms: float | None = None

    def __post_init__(self):
        if any(not math.isfinite(value) or value < 0 for value in (self.request_ms, self.setup_ms)):
            raise ValueError("Costs must be finite nonnegative measurements")
        if isinstance(self.storage_bytes, bool) or not isinstance(self.storage_bytes, int) or self.storage_bytes < 0:
            raise ValueError("Storage must be a nonnegative integer")
        if self.p95_ms is not None and (not math.isfinite(self.p95_ms) or self.p95_ms < 0):
            raise ValueError("Invalid p95")


def choose(options: list[Option], *, expected_requests: int = 1,
           storage_budget_bytes: int | None = None, ttft_slo_ms: float | None = None) -> dict:
    if isinstance(expected_requests, bool) or not isinstance(expected_requests, int) or expected_requests < 1:
        raise ValueError("At least one request required")
    if storage_budget_bytes is not None and (isinstance(storage_budget_bytes, bool)
            or not isinstance(storage_budget_bytes, int) or storage_budget_bytes < 0):
        raise ValueError("Storage budget must be a nonnegative integer")
    if ttft_slo_ms is not None and (not math.isfinite(ttft_slo_ms) or ttft_slo_ms < 0):
        raise ValueError("Latency SLO must be finite and nonnegative")
    considered = []
    valid = []
    for option in options:
        reasons = []
        if not option.compatible:
            reasons.append("incompatible identity")
        if not option.quality_passed:
            reasons.append("quality gate failed or unestablished")
        if not option.evidence:
            reasons.append("no measurement provenance")
        if storage_budget_bytes is not None and option.storage_bytes > storage_budget_bytes:
            reasons.append("storage budget exceeded")
        if ttft_slo_ms is not None and (option.p95_ms is None or option.p95_ms > ttft_slo_ms):
            reasons.append("p95 latency SLO not demonstrated")
        total = option.setup_ms + expected_requests * option.request_ms
        considered.append({**asdict(option), "estimated_total_ms": total, "rejected": reasons})
        if not reasons:
            valid.append((total, option.storage_bytes, option.name))
    if not valid:
        return {"choice": None, "reason": "No compatible option passes the supplied gates", "options": considered}
    best = min(valid)
    return {"choice": best[2], "estimated_total_ms": best[0],
            "reason": "Minimum measured setup plus request cost among valid options",
            "expected_requests": expected_requests, "options": considered,
            "limitation": "Estimate assumes the measured workload, bandwidth and future hit rate remain applicable"}


def break_even_requests(cold_ms: float, warm_ms: float, setup_ms: float) -> int | None:
    if any(not math.isfinite(value) or value < 0 for value in (cold_ms, warm_ms, setup_ms)):
        raise ValueError("Costs must be finite and nonnegative")
    saving = cold_ms - warm_ms
    return math.floor(setup_ms / saving) + 1 if saving > 0 else None


def pareto_frontier(candidates: list[dict], minimize: tuple[str, ...], maximize: tuple[str, ...] = ()) -> list[dict]:
    """All supplied axes required; missing/NaN metrics cannot silently win."""
    def vector(candidate):
        result = [candidate[key] for key in minimize] + [-candidate[key] for key in maximize]
        if not result or not all(math.isfinite(value) for value in result):
            raise ValueError("Finite observations are required on every Pareto axis")
        return result
    vectors = [vector(candidate) for candidate in candidates]
    return [candidate for index, candidate in enumerate(candidates)
            if not any(all(left <= right for left, right in zip(other, vectors[index]))
                       and any(left < right for left, right in zip(other, vectors[index]))
                       for other_index, other in enumerate(vectors) if other_index != index)]

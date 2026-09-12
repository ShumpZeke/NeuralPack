"""Ratio helpers; execution mode and grading must come from actual evidence.

Retired provider-name inference and summary overrides could mislabel mock or
replay data. Actual reports now bind every observation to its frozen raw result.
"""
from typing import Optional

def retention_pct(optimized_accuracy: float, baseline_accuracy: float) -> Optional[float]:
    """Quality retention, or ``None`` when undefined.

    Retention is a ratio against the baseline. If the baseline scored zero there
    is nothing to retain and the ratio is undefined -- it is NOT 100%.
    """
    if baseline_accuracy is None or baseline_accuracy <= 0:
        return None
    return round(optimized_accuracy / baseline_accuracy * 100.0, 2)


def fmt_retention(value: Optional[float]) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def empirical_msc_efficiency(
    msc_tokens: int,
    selected_tokens: int,
    *,
    msc_granularity: str,
    selection_granularity: str,
) -> Optional[float]:
    """Ratio of Empirical MSC tokens to selected tokens, at MATCHED granularity.

    Returns ``None`` when the two measurements are not comparable. Comparing a
    block-level lower bound against line-level compressed output produced the
    impossible 118-154% "efficiency" figures in the audited reports.

    The result is named *Empirical* MSC because minimality is only proven where
    the true minimum was computed exhaustively; elsewhere it is a greedy upper
    bound on the true minimum.
    """
    if msc_granularity != selection_granularity:
        return None
    if selected_tokens <= 0:
        return None
    return round(msc_tokens / selected_tokens * 100.0, 2)

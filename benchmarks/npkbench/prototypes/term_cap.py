"""E043 control arm: the product without the query-term cap (``MAX_QUERY_TERMS``)."""
from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


def _uncapped(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
    original = sel.MAX_QUERY_TERMS
    sel.MAX_QUERY_TERMS = 10**9
    try:
        out: Dict[int, ArmResult] = {}
        with PackSelector(str(pack), enable_cache=False) as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out
    finally:
        sel.MAX_QUERY_TERMS = original


register(Arm("e043_uncapped", runner=_uncapped))

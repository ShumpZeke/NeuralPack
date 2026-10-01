"""E053 + E054 together: URL cleaning in the query and historical release notes last.

``e053_e054`` applies ``e053_urls``' query rewrite (``url_clean``) and
``e054_notes_last``' reordering and fill (``release_notes``) in one selector, so the
confirmation run can check the combination the product would ship if both changes
pass on their own.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Sequence

from ..arms import Arm, ArmResult, _span, register
from ..data import Task
from . import release_notes, url_clean


def make(name: str) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with url_clean._patched(), release_notes.NotesLastSelector(str(pack), enable_cache=False) as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e053_e054")

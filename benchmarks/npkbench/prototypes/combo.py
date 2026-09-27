"""Combinations of the E034/E035/E036/E039 prototypes, for joint confirmation.

The pre-declared HD01 criteria (NEXT_STEPS.md) require an arm that combines every
candidate that passes on its own before they are combined in the product. Each
component is the evaluated prototype, composed without changes:

* ``title_weight`` (E034): title terms repeated in the lexical OR;
* ``qtf_cap`` (E039): query term frequency, with ``title_weight`` on top;
* ``mate_rule`` (E035): test-mate file choice (``any`` or ``fused``);
* ``header_files`` (E036): module header of the top 1 or 2 implementation files.
"""
from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Dict, Optional, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task
from . import header, mate_file, query_tf, title_weight


def make(name: str, *, title: int = 1, qtf_cap: Optional[int] = None, mate_rule: Optional[str] = None,
         header_files: int = 0) -> Arm:
    cls = type(f"Combo_{name}", (header.HeaderSelector,), {"files": header_files}) if header_files else None

    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        first_line = task.query.strip().split("\n", 1)[0]
        out: Dict[int, ArmResult] = {}
        with contextlib.ExitStack() as stack:
            if qtf_cap is not None:
                stack.enter_context(query_tf._weighted(qtf_cap, first_line, title))
            elif title > 1:
                stack.enter_context(title_weight._title_weighted(first_line, title))
            if mate_rule is not None:
                stack.enter_context(mate_file._patched(mate_rule))
            selector = stack.enter_context((cls or PackSelector)(str(pack), enable_cache=False))
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


# Controls: each single-component combo must equal its standalone prototype arm.
make("combo_title3", title=3)
make("combo_title4", title=4)
make("combo_title3_mate_any", title=3, mate_rule="any")
make("combo_title3_mate_fused", title=3, mate_rule="fused")
make("combo_title3_header1", title=3, header_files=1)
make("combo_title3_mate_any_header1", title=3, mate_rule="any", header_files=1)
make("combo_title4_mate_any_header1", title=4, mate_rule="any", header_files=1)

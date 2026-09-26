"""M002 prototype: order candidates by relevance density (score / tokens**alpha).

Conversation evidence sits in short user turns (median 80 tokens) while long
assistant turns (p90 632) consume small budgets. Ordering the fused top-60
by ``score / tokens**alpha`` before greedy fill prefers compact evidence.
Cycle 37's knapsack objective failed on code by favouring many tiny blocks;
alpha < 1 limits that bias. Measured on memory and code workloads.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, register
from ..data import Task


def make(name: str, alpha: float) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        order = sorted(range(len(ranked)),
                       key=lambda i: (-ranked[i].score / max(1, len(ranked[i].text) // 4) ** alpha, i))
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for i in order:
                ev = ranked[i]
                extra = len(ev.text) + (2 if n else 0)
                if max(1, (used + extra) // 4) > budget:
                    continue
                used, n = used + extra, n + 1
                lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
                spans.append((ev.path, lo, hi))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, elapsed,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make("m002_density_a0", 0.0)    # control
make("m002_density_a025", 0.25)
make("m002_density_a05", 0.5)

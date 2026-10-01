"""M001 prototype: source-diverse packing.

Multi-session memory questions ("how many X did I ...") need evidence spread
over several sessions, but rank-order filling can spend the budget on many
turns of one on-topic session. Here each candidate's fused score is divided
by ``(1 + penalty * n)``, where ``n`` counts blocks already selected from the
same file, and selection proceeds greedily on the adjusted scores.

Code fixes with several hunks in one file want the opposite, so this must be
measured on both workloads before any promotion.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, register
from ..data import Task


def diverse_fill(ranked, budget: int, penalty: float):
    remaining = list(range(len(ranked)))
    per_file: Dict[str, int] = {}
    spans, used, n = [], 0, 0
    while remaining:
        best = max(remaining, key=lambda i: (ranked[i].score / (1 + penalty * per_file.get(ranked[i].path, 0)), -i))
        remaining.remove(best)
        ev = ranked[best]
        extra = len(ev.text) + (2 if n else 0)
        if max(1, (used + extra) // 4) > budget:
            continue
        used, n = used + extra, n + 1
        per_file[ev.path] = per_file.get(ev.path, 0) + 1
        lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
        spans.append((ev.path, lo, hi))
    return spans, (max(1, used // 4) if n else 0), n


def make(name: str, penalty: float) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]):
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        ranked = ranked[:200]
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, tokens, n = diverse_fill(ranked, budget, penalty)
            out[budget] = ArmResult(spans, tokens, elapsed, "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make("m001_div0", 0.0)     # control: plain greedy on fused scores
make("m001_div05", 0.5)
make("m001_div1", 1.0)
make("m001_div3", 3.0)

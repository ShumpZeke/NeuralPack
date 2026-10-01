"""E008 prototype: role portfolio allocation of the context budget.

Observation: baseline selections give tests ~21% and documentation ~23% of
tokens, but by lexical accident. Documentation serves neither the fix nor
the tests target on NPK-Bench, and test blocks are chosen by generic rank.
A path prior that demotes tests (E006) wins the fix target only by losing
the tests target.

Hypothesis: allocating explicit budget shares per evidence role, each filled
greedily in the product's fused rank order, with any unused share flowing
back to the remaining candidates, improves BOTH targets: implementation gets
room without test crowding, and the test share goes to the best-ranked test
blocks instead of whatever ranks happened to fit.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, register
from ..data import Task

TEST = re.compile(r"(^|/)(tests?|testing|__tests__|specs?)(/|$)|(^|/)test_[^/]*$|_tests?\.[A-Za-z0-9]+$"
                  r"|(^|/)tests?\.[A-Za-z0-9]+$"
                  r"|(^|/)conftest\.py$|\.(test|spec)\.[jt]sx?$")
DOC = re.compile(r"(^|/)(docs?|documentation|doc_src)(/|$)|\.(rst|md|txt|adoc)$")


def role(path: str) -> str:
    if TEST.search(path):
        return "test"
    if DOC.search(path):
        return "doc"
    return "impl"


def portfolio_fill(ranked, budget: int, shares: Dict[str, float], *,
                   first_exempt: bool = False, classify=None) -> Tuple[List[Tuple[str, int, int]], int, int]:
    """Greedy fill within per-role shares, then a spill-over pass in rank order.

    ``first_exempt``: a role's first block may exceed that role's share when it
    fits the total budget (shares then bound only additional blocks), so a
    large top-ranked block is never lost to a small share.
    """
    chosen: List[int] = []
    used_chars, n = 0, 0
    spent = {r: 0 for r in shares}
    limit = {r: shares[r] * budget for r in shares}

    def fits(extra_chars: int) -> bool:
        return max(1, (used_chars + extra_chars) // 4) <= budget

    for phase in ("share", "spill"):
        for i, ev in enumerate(ranked):
            if i in chosen:
                continue
            extra = len(ev.text) + (2 if n else 0)
            if not fits(extra):
                continue
            r = (classify or role)(ev.path)
            if phase == "share" and spent.get(r, 0) + extra / 4 > limit.get(r, 0):
                if not (first_exempt and spent.get(r, 0) == 0 and limit.get(r, 0) > 0):
                    continue
            chosen.append(i)
            used_chars += extra
            n += 1
            spent[r] = spent.get(r, 0) + extra / 4
    chosen.sort()  # emit in rank order
    spans = []
    for i in chosen:
        lo, hi = map(int, ranked[i].span.rsplit(":", 1)[1].split("-"))
        spans.append((ranked[i].path, lo, hi))
    return spans, (max(1, used_chars // 4) if n else 0), n


def make(name: str, impl: float, test: float, doc: float, first_exempt: bool = False,
         **selector_options) -> Arm:
    shares = {"impl": impl, "test": test, "doc": doc}

    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False, **selector_options) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, tokens, n = portfolio_fill(ranked, budget, shares, first_exempt=first_exempt)
            out[budget] = ArmResult(spans, tokens, elapsed, "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


# Control: shares that never bind reproduce plain greedy fill.
make("e008_control", 1.0, 1.0, 1.0)
make("e008_i70_t30_d0", 0.7, 0.3, 0.0)
make("e008_i60_t30_d10", 0.6, 0.3, 0.1)
make("e008_i75_t25_d0", 0.75, 0.25, 0.0)
make("e008_i50_t40_d10", 0.5, 0.4, 0.1)
make("e008_i80_t20_d0", 0.8, 0.2, 0.0)

# E008b: soft shares (first block of a role exempt) and docs-share hedges.
make("e008b_soft_i70_t30_d0", 0.7, 0.3, 0.0, first_exempt=True)
make("e008b_soft_i60_t30_d10", 0.6, 0.3, 0.1, first_exempt=True)
make("e008b_soft_i55_t25_d20", 0.55, 0.25, 0.2, first_exempt=True)
make("e008b_soft_i75_t25_d0", 0.75, 0.25, 0.0, first_exempt=True)
make("e008b_soft_i60_t40_d0", 0.6, 0.4, 0.0, first_exempt=True)


# E008c: pure test reservation. Documentation and implementation are one
# "non-test" role (no documentation demotion); only the test share is held.
def _two_roles(path: str) -> str:
    return "test" if role(path) == "test" else "impl"


def make_reserve(name: str, test_share: float) -> Arm:
    shares = {"impl": 1.0 - test_share, "test": test_share}

    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, tokens, n = portfolio_fill(ranked, budget, shares, first_exempt=True, classify=_two_roles)
            out[budget] = ArmResult(spans, tokens, elapsed, "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make_reserve("e008c_test20", 0.2)
make_reserve("e008c_test30", 0.3)
make_reserve("e008c_test40", 0.4)

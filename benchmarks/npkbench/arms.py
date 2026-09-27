"""Retrieval arms. Each arm maps (pack, task, budgets) to selected source spans.

Arms receive only the issue text as a query. Gold locations are available to
oracle arms, which exist solely to bound headroom and are labelled ``oracle_``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .data import Task

Ranked = Tuple[str, int, int, int]


@dataclass
class ArmResult:
    spans: List[Tuple[str, int, int]]
    tokens: int
    latency_ms: float
    status: str
    n_blocks: int
    extra: Dict[str, Any] = field(default_factory=dict)


def _span(evidence) -> Tuple[str, int, int]:
    lo, hi = evidence.span.rsplit(":", 1)[1].split("-")
    return evidence.path, int(lo), int(hi)


@dataclass
class Arm:
    name: str
    compile_options: Dict[str, Any] = field(default_factory=dict)
    selector_options: Dict[str, Any] = field(default_factory=dict)
    # Optional override: fn(pack, task, budgets) -> {budget: ArmResult}
    runner: Optional[Callable[..., Dict[int, ArmResult]]] = None
    # Optional override: fn(pack, task) -> ranked spans for tokens-to-find.
    ranker: Optional[Callable[..., List[Ranked]]] = None

    def run(self, pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        if self.runner is not None:
            return self.runner(pack, task, budgets)
        from npk.pack import PackSelector

        out: Dict[int, ArmResult] = {}
        with PackSelector(str(pack), enable_cache=False, **self.selector_options) as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                latency = (time.perf_counter() - started) * 1000
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence],
                    tokens=selection.total_tokens, latency_ms=latency,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    def ranking(self, pack: Path, task: Task) -> Optional[List[Ranked]]:
        if self.ranker is not None:
            return self.ranker(pack, task)
        if self.runner is not None:
            return None
        from npk.pack import PackSelector

        options = dict(self.selector_options)
        options["candidate_limit"] = 1000
        with PackSelector(str(pack), enable_cache=False, **options) as selector:
            selection = selector.select(task.query, budget_tokens=10**9, allow_escalation=False)
        return [(*_span(e), max(1, len(e.text) // 4)) for e in selection.evidence]


def _oracle_blocks(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
    """Smallest set of whole blocks covering every hunk: a block-granularity floor."""
    from npk.pack.format import load_blocks, open_pack

    with open_pack(pack) as con:
        ids = [r[0] for r in con.execute(
            "SELECT b.id FROM blocks b JOIN files f ON f.id=b.file_id WHERE f.path IN (%s)"
            % ",".join("?" * len(task.files)), task.files)]
        blocks = load_blocks(con, ids)
    chosen = []
    for hunk in task.hunks:
        for block in blocks:
            if hunk.found_by([(block.path, block.start_line, block.end_line)]):
                if block not in chosen:
                    chosen.append(block)
                break
    tokens = max(1, (sum(len(b.text) for b in chosen) + 2 * max(0, len(chosen) - 1)) // 4) if chosen else 0
    result = ArmResult([(b.path, b.start_line, b.end_line) for b in chosen], tokens, 0.0,
                       "selected" if chosen else "fallback_required", len(chosen))
    return {budget: result for budget in budgets}


ARMS: Dict[str, Arm] = {
    "npk_default": Arm("npk_default"),
    "npk_no_relations": Arm("npk_no_relations", selector_options={"enable_relations": False}),
    # The product before E002 (no definition channel); ``npk_default`` always
    # means current product defaults, so historical comparisons use this.
    "npk_nodefs": Arm("npk_nodefs", selector_options={"enable_definitions": False, "enable_trim": False}),
    "npk_notrim": Arm("npk_notrim", selector_options={"enable_trim": False}),
    # Test mate: npk_default is budget-gated (on from 2048 tokens, E016c). Runs made
    # on exp/e016b-test-mate used npk_default for mate-on; runs between the opt-in
    # merge and E016c's promotion used npk_default for mate-off.
    "npk_mate": Arm("npk_mate", selector_options={"enable_test_mate": True}),
    "npk_nomate": Arm("npk_nomate", selector_options={"enable_test_mate": False}),
    # The product before E031: retrieval reads issue-form scaffolding too. Every
    # product arm in runs made before E031's promotion (2026-09-27) is raw-query.
    "npk_rawquery": Arm("npk_rawquery", selector_options={"enable_query_cleaning": False}),
    "npk_members": Arm("npk_members", compile_options={"python_members": True}),
    "oracle_blocks": Arm("oracle_blocks", runner=_oracle_blocks),
}


def register(arm: Arm) -> Arm:
    ARMS[arm.name] = arm
    return arm


def get(name: str) -> Arm:
    if name not in ARMS:
        # Experimental arms live in experiments/<name>/arm.py modules that
        # call register(); import lazily so the product never depends on them.
        import importlib
        module, _, attr = name.partition(":")
        if attr:
            return getattr(importlib.import_module(module), attr)
        raise KeyError(f"unknown arm {name!r}; known: {sorted(ARMS)}")
    return ARMS[name]

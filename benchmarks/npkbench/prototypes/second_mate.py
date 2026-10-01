"""E044 prototype: a second test mate at large budgets.

Regression-test recall is the product's lowest target (held-out R002: 0.42 at 16K
against 0.64 for fix sites), and the test mate (E016c) places exactly one test
block, for the top implementation file. At large budgets there is room for more:
``e044_second_mate`` also places the mirroring test block of the second-ranked
implementation *file*, right after that file's top block, from ``min_budget``
tokens. Everything else is the product's (E031/E039 query handling, gated mate).
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


class SecondMateSelector(PackSelector):
    min_budget = 8192

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._budget = 0

    def _select_once(self, con, manifest, query, budget, limit):
        self._budget = budget
        return super()._select_once(con, manifest, query, budget, limit)

    def _place_test_mate(self, con, manifest, query, ordered_ids: List[int], fused, channels_of, deep=None):
        out = super()._place_test_mate(con, manifest, query, ordered_ids, fused, channels_of, deep)
        if self._budget < self.min_budget or not out:
            return out
        marks = ",".join("?" * len(out))
        paths = dict(con.execute(
            f"SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id IN ({marks})",
            out).fetchall())
        seen: List[str] = []
        second = None
        for block_id in out:
            path = paths.get(block_id, "")
            if sel.TEST_PATH.search(path) or sel.DOC_PATH.search(path) or path in seen:
                continue
            seen.append(path)
            if len(seen) == 2:
                second = block_id
                break
        if second is None:
            return out
        position = out.index(second)
        mates = {b for b in out if "test_mate" in channels_of.get(b, [])}
        exclude = set(out[:position + 1]) | mates
        mate = sel._test_mate(con, query, paths[second], exclude, self._test_paths_cache, deep)
        if mate is None:
            return out
        out = [b for b in out if b != mate]
        out.insert(out.index(second) + 1, mate)
        fused.setdefault(mate, 0.0)
        channels_of.setdefault(mate, []).append("test_mate")
        return out


def make(name: str, min_budget: int) -> Arm:
    cls = type(f"SecondMate{min_budget}", (SecondMateSelector,), {"min_budget": min_budget})

    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with cls(str(pack), enable_cache=False) as selector:
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


make("e044_second_mate_8k", 8192)
make("e044_second_mate_4k", 4096)
make("e044_control", 10**9)   # never places a second mate: must equal npk_default

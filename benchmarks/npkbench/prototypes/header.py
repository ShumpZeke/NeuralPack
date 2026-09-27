"""E036 prototype: the top implementation file's module header (imports).

Of the fix hunks missed at 4K in a file the selection already covers, about a
quarter are import edits in the file's first module-level block (dev-fast: 9 of
153 fix hunks and 10 of 202 test hunks at 4K; median header 90-120 tokens).
The header also tells a reader which names are in scope when writing the
change. ``e036_header`` places the module header (the ``module`` block at line
1) of the top-ranked implementation file right after that file's top block,
when it is at most an eighth of the budget. ``e036_header2`` does the same for
the two top-ranked implementation files. Everything else is the product's
(test mate gated at 2K as in the product).
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


class HeaderSelector(PackSelector):
    files = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, enable_test_mate=True, **kwargs)
        self._budget = 0

    def _select_once(self, con, manifest, query, budget, limit):
        self._budget = budget
        return super()._select_once(con, manifest, query, budget, limit)

    def _place_test_mate(self, con, manifest, query, ordered_ids, fused, channels_of, deep=None):
        if self._budget >= sel.TEST_MATE_MIN_BUDGET:
            ordered_ids = super()._place_test_mate(con, manifest, query, ordered_ids, fused,
                                                   channels_of, deep)
        return self._place_headers(con, ordered_ids, fused, channels_of)

    def _place_headers(self, con, ordered_ids: List[int], fused, channels_of) -> List[int]:
        if not ordered_ids:
            return ordered_ids
        marks = ",".join("?" * len(ordered_ids))
        paths = dict(con.execute(
            f"SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id IN ({marks})",
            ordered_ids).fetchall())
        done: List[str] = []
        out = list(ordered_ids)
        for block_id in ordered_ids:
            if len(done) >= self.files:
                break
            path = paths.get(block_id, "")
            if sel.TEST_PATH.search(path) or sel.DOC_PATH.search(path) or path in done:
                continue
            done.append(path)
            header = con.execute(
                "SELECT b.id, b.tokens FROM blocks b JOIN files f ON f.id=b.file_id "
                "WHERE f.path=? AND b.kind='module' AND b.start_line=1", (path,)).fetchone()
            if (header is None or header[0] == block_id or header[1] > self._budget // 8
                    or header[0] in out[:out.index(block_id)]):
                continue
            out = [b for b in out if b != header[0]]
            out.insert(out.index(block_id) + 1, header[0])
            fused.setdefault(header[0], 0.0)
            channels_of.setdefault(header[0], []).append("header")
        return out


def make(name: str, files: int) -> Arm:
    cls = type(f"Header{files}", (HeaderSelector,), {"files": files})

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


make("e036_control", 0)   # no headers: must equal npk_default
make("e036_header", 1)
make("e036_header2", 2)

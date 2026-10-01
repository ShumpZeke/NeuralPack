"""E060 prototype: the ends of the test mate's file.

Regression tests are appended at the end of a test file and their imports edited at the top, so
the gold test hunk of an issue often sits in the last or the first block of the file the test mate
already points at (D4: 33% and 17% of the cases where the mate's file is right and its block is
wrong). A ranking over query terms cannot see that. From ``min_budget`` tokens up,
``MateEndsSelector`` places the last block of the mate's file (``tail``) and, if asked, its first
block (``head``) right after the mate; everything else is the product's.
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


class MateEndsSelector(PackSelector):
    min_budget = 4096
    tail = True
    head = False
    #: E060b: only when the mate's path mirrors the implementation file this strongly
    #: (``_mate_score``: module name 2 + package name 1 + 0.25 per other shared part).
    min_mate_score = 0.0

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
        mate = next((b for b in out if "test_mate" in channels_of.get(b, [])), None)
        if mate is None:
            return out
        row = con.execute("SELECT f.path FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id=?", (mate,)).fetchone()
        if row is None:
            return out
        if self.min_mate_score:
            marks = ",".join("?" * len(out))
            paths = dict(con.execute(
                f"SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id IN ({marks})", out).fetchall())
            impl = next((b for b in out if not sel.TEST_PATH.search(paths.get(b, ""))
                         and not sel.DOC_PATH.search(paths.get(b, ""))), None)
            if impl is None or sel._mate_score(paths[impl], row[0]) < self.min_mate_score:
                return out
        ids = [r[0] for r in con.execute(
            "SELECT b.id FROM blocks b JOIN files f ON f.id=b.file_id WHERE f.path=? ORDER BY b.ordinal", (row[0],))]
        wanted: List[tuple] = []
        if self.tail and ids:
            wanted.append((ids[-1], "mate_tail"))
        if self.head and ids:
            wanted.append((ids[0], "mate_head"))
        position = out.index(mate)
        add = [(b, channel) for b, channel in wanted if b != mate and b not in out[:position]]
        if not add:
            return out
        moved = {b for b, _ in add}
        out = [b for b in out if b not in moved]
        position = out.index(mate)
        for offset, (b, channel) in enumerate(add, start=1):
            out.insert(position + offset, b)
            fused.setdefault(b, 0.0)
            channels_of.setdefault(b, []).append(channel)
        return out


def make(name: str, min_budget: int, tail: bool = True, head: bool = False, min_score: float = 0.0) -> Arm:
    cls = type(f"MateEnds{name}", (MateEndsSelector,),
               {"min_budget": min_budget, "tail": tail, "head": head, "min_mate_score": min_score})

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


make("e060_control", 10**9)  # never adds a block: must equal npk_default
make("e060_tail_2k", 2048)
make("e060_tail_4k", 4096)
make("e060_tail_8k", 8192)
make("e060_headtail_4k", 4096, tail=True, head=True)
# E060b: the same, only behind a mate that mirrors both the module and its package (score >= 3).
make("e060b_tail_s3_2k", 2048, min_score=3.0)
make("e060b_tail_s3_4k", 4096, min_score=3.0)
make("e060b_headtail_s3_4k", 4096, tail=True, head=True, min_score=3.0)
make("e060b_control", 10**9, min_score=3.0)  # must equal npk_default

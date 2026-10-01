"""E040 prototype: code names in the issue title vote more in the definition channel.

E034 showed that the title (first line) is the best summary of an issue's
topic for lexical ranking. The definition channel (E002) gives every code name
the query mentions the same vote, ``1/log2(1+n)`` for ``n`` definitions, so a
name from a traceback frame or a reproduction script counts as much as the
name in the title ("QuerySet.defer() doesn't clear deferred field"). Here a name
that also occurs in the title votes ``weight`` times. Arms combine it with E034's
title weighting (x3) in the lexical channel, since that is the likely product.
"""
from __future__ import annotations

import contextlib
import importlib
import math
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task
from . import title_weight

sel = importlib.import_module("npk.pack.select")


def _make_channel(title: str, weight: float):
    def channel(con: sqlite3.Connection, query: str, limit: int, lexical: Sequence[int]) -> List[int]:
        names = sel._query_entities(query)
        if not names:
            return []
        in_title = set(sel._query_entities(title))
        marks = ",".join("?" * len(names))
        try:
            rows = con.execute(
                "SELECT s.name, s.block_id, f.path, b.ordinal FROM symbols s "
                "JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id "
                f"WHERE s.is_def=1 AND s.name IN ({marks})", tuple(names)).fetchall()
        except sqlite3.OperationalError:
            return []
        by_name: Dict[str, Set[int]] = {}
        position: Dict[int, Tuple[str, int]] = {}
        for row in rows:
            by_name.setdefault(row[0], set()).add(row[1])
            position[row[1]] = (row[2], row[3])
        score: Dict[int, float] = {}
        for name, blocks in by_name.items():
            if len(blocks) > sel.MAX_DEFINITION_AMBIGUITY:
                continue
            vote = 1.0 / math.log2(1 + len(blocks)) * (weight if name in in_title else 1.0)
            for block_id in blocks:
                score[block_id] = score.get(block_id, 0.0) + vote
        lexical_rank = {block_id: rank for rank, block_id in enumerate(lexical)}
        unranked = len(lexical_rank)
        ordered = sorted(score, key=lambda b: (-score[b], lexical_rank.get(b, unranked), position[b]))
        return ordered[:limit]
    return channel


@contextlib.contextmanager
def _patched(title: str, weight: float):
    original = sel._definition_channel
    sel._definition_channel = _make_channel(title, weight)
    try:
        yield
    finally:
        sel._definition_channel = original


def make(name: str, def_weight: float, lexical_title: int) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        first_line = task.query.strip().split("\n", 1)[0]
        out: Dict[int, ArmResult] = {}
        with contextlib.ExitStack() as stack:
            if lexical_title > 1:
                stack.enter_context(title_weight._title_weighted(first_line, lexical_title))
            stack.enter_context(_patched(first_line, def_weight))
            selector = stack.enter_context(PackSelector(str(pack), enable_cache=False))
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


make("e040_defs_control", 1.0, 1)          # must equal npk_default
make("e040_title3_defs1", 1.0, 3)          # must equal e034_title_x3
make("e040_title3_defs2", 2.0, 3)
make("e040_title3_defs4", 4.0, 3)

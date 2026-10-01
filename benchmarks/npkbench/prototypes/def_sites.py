"""E051 prototype: count definition ambiguity per site, not per block.

A Python class longer than ``MAX_BLOCK_TOKENS`` is cut into line windows that
all carry the class name, and each window counts as a separate definition of
it. A class of more than ``MAX_DEFINITION_AMBIGUITY`` windows is then ignored
by the definition channel altogether, and a smaller one splits its vote. On
dev-fast, 9 of 102 issues name such a class (``QuerySet`` 12-15 windows,
``Poly`` 23, ``DataArray`` 33, ``Mul`` 16, ``Integral`` 13).

Here a definition *site* is one (file, name) pair; the ambiguity cap and the
``1/log2(1 + n)`` weight count sites, so a class defined once votes with full
weight however many windows it spans. ``e051_sites`` gives every window of a
site the site's vote (the channel then orders them by lexical rank, as it
orders ties today); ``e051_sites_top2`` gives it to the two lexically best
windows of each site only, so one large class cannot fill the channel.
Names defined once per file in several files (the common case) are unchanged.
"""
from __future__ import annotations

import contextlib
import importlib
import math
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


def _make_channel(per_site: Optional[int]):
    def definition_channel(con: sqlite3.Connection, query: str, limit: int,
                           lexical: Sequence[int]) -> List[int]:
        names = sel._query_entities(query)
        if not names:
            return []
        marks = ",".join("?" * len(names))
        try:
            rows = con.execute(
                "SELECT s.name, s.block_id, f.path, b.ordinal FROM symbols s "
                "JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id "
                f"WHERE s.is_def=1 AND s.name IN ({marks})", tuple(names)).fetchall()
        except sqlite3.OperationalError:
            return []
        lexical_rank = {block_id: rank for rank, block_id in enumerate(lexical)}
        unranked = len(lexical_rank)
        sites: Dict[str, Dict[str, Set[int]]] = {}
        position: Dict[int, Tuple[str, int]] = {}
        for name, block_id, path, ordinal in rows:
            sites.setdefault(name, {}).setdefault(path, set()).add(block_id)
            position[block_id] = (path, ordinal)
        score: Dict[int, float] = {}
        for by_path in sites.values():
            if len(by_path) > sel.MAX_DEFINITION_AMBIGUITY:
                continue
            weight = 1.0 / math.log2(1 + len(by_path))
            for blocks in by_path.values():
                chosen = sorted(blocks, key=lambda b: (lexical_rank.get(b, unranked), position[b]))
                for block_id in (chosen if per_site is None else chosen[:per_site]):
                    score[block_id] = score.get(block_id, 0.0) + weight
        ordered = sorted(score, key=lambda b: (-score[b], lexical_rank.get(b, unranked), position[b]))
        return ordered[:limit]
    return definition_channel


@contextlib.contextmanager
def _patched(per_site: Optional[int]):
    original = sel._definition_channel
    sel._definition_channel = _make_channel(per_site)
    try:
        yield
    finally:
        sel._definition_channel = original


def make(name: str, per_site: Optional[int]) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with _patched(per_site), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e051_sites", None)
make("e051_sites_top2", 2)

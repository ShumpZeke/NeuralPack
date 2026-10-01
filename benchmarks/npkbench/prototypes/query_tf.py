"""E039 prototype: query term frequency in the lexical channel.

The lexical channel deduplicates query terms (CURRENT_ARCHITECTURE section 3), so
a word the reporter repeats throughout an issue ("legend", "draggable") counts
no more than one mentioned once in a traceback. E034 showed that emphasizing
the title's terms helps; term frequency is the other classic emphasis signal
(BM25's query-side tf). Each term is repeated ``min(cap, 1 + floor(log2(tf)))``
times in the FTS5 OR, where ``tf`` counts the term's occurrences among the
analyzed query terms (bm25 sums repeated phrases). Everything else is the
product's.

* ``e039_qtf_cap2`` / ``e039_qtf_cap3``: frequency weighting alone.
* ``e039_qtf_cap3_title3``: with E034's title weighting (x3) on top.
"""
from __future__ import annotations

import collections
import contextlib
import importlib
import math
import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector
from npk.pack.search import analyzed_terms

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


@contextlib.contextmanager
def _weighted(cap: int, title: str, title_weight: int):
    original = sel._lexical_channel

    def channel(con, query, limit):
        if len(sel._whole_lexical_terms(query)) == 1:
            return original(con, query, limit)
        try:
            terms = sel._lexical_terms(con, query)
            if not terms:
                return []
            counts = collections.Counter(analyzed_terms(query))
            title_terms = set(sel._lexical_terms(con, title)) if title_weight > 1 else set()
            phrases = []
            for term in terms:
                reps = min(cap, 1 + int(math.log2(max(1, counts.get(term, 1)))))
                if term in title_terms:
                    reps += title_weight - 1
                phrases.extend([f'"{term}"'] * reps)
            rows = con.execute(
                "SELECT lexical.rowid AS block_id FROM lexical JOIN blocks b ON b.id=lexical.rowid "
                "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
                "ORDER BY bm25(lexical,1.0,1.0,1.0),f.path COLLATE BINARY,b.ordinal LIMIT ?",
                (" OR ".join(phrases), limit)).fetchall()
            return [row["block_id"] for row in rows]
        except Exception:
            return original(con, query, limit)

    sel._lexical_channel = channel
    try:
        yield
    finally:
        sel._lexical_channel = original


def make(name: str, cap: int, title_weight: int = 1) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        title = task.query.strip().split("\n", 1)[0]
        out: Dict[int, ArmResult] = {}
        with _weighted(cap, title, title_weight), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e039_qtf_cap2", 2)
make("e039_qtf_cap3", 3)
make("e039_qtf_cap3_title3", 3, title_weight=3)

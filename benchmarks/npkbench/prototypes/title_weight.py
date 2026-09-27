"""E034 prototype: weight the issue title's terms in the lexical channel.

An issue's first line is its author's summary ("Setting the value of a progress
element to 0 removes the attribute"), while the body mixes reproduction code,
environment details and template text. The lexical channel deduplicates query
terms, so a title word counts no more than any body word. FTS5's bm25() sums
repeated OR-phrases, so repeating each title term ``weight - 1`` extra times in
the MATCH expression weights it without other changes. Definition and relation
channels, fill and trimming are the product's.
"""
from __future__ import annotations

import contextlib
import importlib
import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


@contextlib.contextmanager
def _title_weighted(title: str, weight: int):
    original = sel._lexical_channel

    def channel(con, query, limit):
        if len(sel._whole_lexical_terms(query)) == 1:
            return original(con, query, limit)   # the product's one-symbol lookup path
        try:
            terms = sel._lexical_terms(con, query)
            if not terms:
                return []
            title_terms = [t for t in sel._lexical_terms(con, title) if t in set(terms)]
            phrases = [f'"{t}"' for t in terms] + [f'"{t}"' for t in title_terms for _ in range(weight - 1)]
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


def make(name: str, weight: int) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        title = task.query.strip().split("\n", 1)[0]
        out: Dict[int, ArmResult] = {}
        with _title_weighted(title, weight), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e034_title_x1", 1)   # control: must reproduce the product's multi-word ranking
make("e034_title_x2", 2)
make("e034_title_x3", 3)

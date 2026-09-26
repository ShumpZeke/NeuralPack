"""E016 prototype: add the test block that belongs to the top implementation.

Portfolio reservations (E008c) only moved recall from the fix target to the
tests target: they reserved budget for whatever tests ranked high lexically.
Here the test evidence is chosen structurally: the test file that mirrors the
top-ranked implementation file by path convention (``pkg/mod.py`` ->
``pkg/tests/test_mod.py``, ``tests/<pkg>/tests.py``), and within it the block
that best matches the query. One such block is inserted right after the top
implementation block; everything else keeps the product's order.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from npk.pack import PackSelector
from npk.pack.format import load_blocks, open_pack
from npk.pack.select import _lexical_terms

from ..arms import Arm, ArmResult, register
from ..data import Task
from .portfolio import role

GENERIC = {"tests", "test", "testing", "src", "lib", "py", "__init__", "unit", "units", "t"}


def _parts(path: str) -> List[str]:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", path)
    return [p for p in re.split(r"[/_.-]+", stem.lower()) if p]


def mate_score(impl: str, test: str) -> float:
    """How strongly a test path mirrors an implementation path (0 = unrelated)."""
    ip, tp = _parts(impl), _parts(test)
    if not ip or not tp:
        return 0.0
    module = ip[-1]
    parent = ip[-2] if len(ip) > 1 else ""
    score = 0.0
    if module in tp and module not in GENERIC:
        score += 2.0
    if parent and parent in tp and parent not in GENERIC:
        score += 1.0
    shared = (set(ip) & set(tp)) - GENERIC - {module, parent}
    return score + 0.25 * len(shared)


def best_mate_block(con, query: str, impl_path: str, exclude: set) -> Optional[int]:
    files = [r[0] for r in con.execute("SELECT path FROM files") if role(r[0]) == "test"]
    scored = sorted(((mate_score(impl_path, f), f) for f in files), reverse=True)
    if not scored or scored[0][0] < 1.0:
        return None
    mate_files = [f for s, f in scored[:3] if s == scored[0][0]]
    terms = _lexical_terms(con, query)
    if not terms:
        return None
    match = " OR ".join(f'"{t}"' for t in terms)
    marks = ",".join("?" * len(mate_files))
    rows = con.execute(
        "SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid JOIN files f ON f.id=b.file_id "
        f"WHERE lexical MATCH ? AND f.path IN ({marks}) ORDER BY bm25(lexical,1.0,1.0,1.0), f.path, b.ordinal LIMIT 5",
        (match, *mate_files)).fetchall()
    for (block_id,) in rows:
        if block_id not in exclude:
            return block_id
    return None


def make(name: str, *, position: int = 1, max_tokens: int = 10**9) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        order = [(e.path, e.span, e.text) for e in ranked]
        top_impl = next((e for e in ranked if role(e.path) == "impl"), None)
        if top_impl is not None:
            with open_pack(pack) as con:
                mate = best_mate_block(con, task.query, top_impl.path, {e.block_id for e in ranked[:position + 1]})
                if mate is not None:
                    blk = load_blocks(con, [mate])[0]
                    if blk.tokens <= max_tokens:
                        entry = (blk.path, blk.span, blk.text)
                        order = [x for x in order if x[1] != blk.span]
                        at = next(i for i, e in enumerate(ranked) if e.block_id == top_impl.block_id) + position
                        order.insert(min(at, len(order)), entry)
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for path, span, text in order:
                extra = len(text) + (2 if n else 0)
                if max(1, (used + extra) // 4) > budget:
                    continue
                used, n = used + extra, n + 1
                lo, hi = map(int, span.rsplit(":", 1)[1].split("-"))
                spans.append((path, lo, hi))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, elapsed,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make("e016_testmate_p1", position=1)
make("e016_testmate_p3", position=3)
make("e016_testmate_p1_small", position=1, max_tokens=400)

"""E041 prototype: title weighting in top-block trimming's member ranking.

When the best-ranked block alone exceeds the budget, top-block trimming (E005c)
ranks its member spans by a file-local BM25 over the query's unique terms. E034
showed that the title's terms deserve more weight than the body's in lexical
ranking; the same should hold when choosing which methods of an oversized
class to emit. Here a title term's member score counts ``weight`` times. Arms
run on top of E034's lexical title weighting (x4, the HD01 candidate).
"""
from __future__ import annotations

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
from . import title_weight

sel = importlib.import_module("npk.pack.select")


def _make_rank_members(title: str, weight: float):
    def rank(con, block, members, query):
        terms = sel._lexical_terms(con, query)
        in_title = set(sel._lexical_terms(con, title))
        rows = [r[0] for r in con.execute("SELECT text FROM blocks WHERE file_id=?", (block.file_id,))]
        vocab = [set(analyzed_terms(text)) for text in rows]
        total = len(vocab)
        idf = {t: max(0.0, math.log((total - sum(t in v for v in vocab) + 0.5)
                                    / (sum(t in v for v in vocab) + 0.5))) + 0.01 for t in terms}
        lines = block.text.split("\n")
        ranked = []
        for index, (start, end, kind, name) in enumerate(members):
            text = "\n".join(lines[start - block.start_line:end - block.start_line + 1])
            counts: Dict[str, int] = {}
            for term in analyzed_terms(text):
                counts[term] = counts.get(term, 0) + 1
            n = sum(counts.values()) or 1
            score = sum((weight if t in in_title else 1.0)
                        * idf[t] * counts[t] * 2.2 / (counts[t] + 1.2 * (0.25 + 0.75 * n / 200))
                        for t in terms if t in counts)
            ranked.append((-score, index, start, end, kind, name, text))
        ranked.sort()
        return [(start, end, kind, name, text) for _s, _i, start, end, kind, name, text in ranked]
    return rank


@contextlib.contextmanager
def _patched(title: str, weight: float):
    original = sel._rank_members
    sel._rank_members = _make_rank_members(title, weight)
    try:
        yield
    finally:
        sel._rank_members = original


def make(name: str, member_weight: float, lexical_title: int = 4) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        first_line = task.query.strip().split("\n", 1)[0]
        out: Dict[int, ArmResult] = {}
        with contextlib.ExitStack() as stack:
            if lexical_title > 1:
                stack.enter_context(title_weight._title_weighted(first_line, lexical_title))
            stack.enter_context(_patched(first_line, member_weight))
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


make("e041_members1_title4", 1.0)   # control: must equal e034_title_x4
make("e041_members4_title4", 4.0)

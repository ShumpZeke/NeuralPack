"""E017 prototype: multi-resolution context (map + full text).

Every other experiment changed which whole blocks fill the budget. An agent
that can read more (or a model asked to point at a location) benefits from
knowing where relevant code is. Here a fraction of the budget holds a map:
one line per ranked candidate beyond the full-text selection, expanded into
member spans for Python classes (``path:start-end kind qualified.name``).

Scored twice: ``hunk_recall`` counts full text only; the ``~loc`` rows count a
hunk as located when it lies in full text or inside a listed map span.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from npk.pack import PackSelector
from npk.pack.format import load_blocks, open_pack
from npk.pack.select import TRIM_MIN_TOKENS, _member_spans

from ..arms import Arm, ArmResult, register
from ..data import Task


def map_entries(con, ranked, skip: set, budget_tokens: int) -> Tuple[List[Tuple[str, int, int]], int]:
    spans: List[Tuple[str, int, int]] = []
    used = 0
    blocks = {b.id: b for b in load_blocks(con, [e.block_id for e in ranked])}
    for ev in ranked:
        blk = blocks.get(ev.block_id)
        if blk is None or blk.span in skip:
            continue
        members = []
        if blk.path.endswith(".py") and blk.tokens >= TRIM_MIN_TOKENS:
            members = _member_spans(con, blk)
        entries = ([(s, e, k, n) for s, e, k, n in members] if len(members) > 1
                   else [(blk.start_line, blk.end_line, blk.kind, blk.name or "")])
        for start, end, kind, name in entries:
            line = f"{blk.path}:{start}-{end} {kind} {name}".rstrip()
            cost = len(line) // 4 + 1
            if used + cost > budget_tokens:
                return spans, used
            used += cost
            spans.append((blk.path, start, end))
    return spans, used


def make(name: str, fraction: float) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        out = {}
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
            for budget in budgets:
                map_budget = int(budget * fraction)
                text_budget = budget - map_budget
                chosen = (selector.select(task.query, budget_tokens=text_budget).evidence
                          if text_budget > 0 else [])
                text_spans = []
                for e in chosen:
                    lo, hi = map(int, e.span.rsplit(":", 1)[1].split("-"))
                    text_spans.append((e.path, lo, hi))
                with open_pack(pack) as con:
                    mspans, mused = map_entries(con, ranked, {e.span for e in chosen}, map_budget)
                tokens = sum(max(1, len(e.text) // 4) for e in chosen) + mused
                out[budget] = ArmResult(text_spans, tokens, (time.perf_counter() - started) * 1000,
                                        "selected" if chosen or mspans else "fallback_required",
                                        len(chosen), extra={"map_spans": [list(x) for x in mspans],
                                                            "map_entries": len(mspans)})
        return out

    return register(Arm(name, runner=runner))


make("e017_map0", 0.0)     # control: product selection; ~loc equals full text
make("e017_map10", 0.10)
make("e017_map25", 0.25)
make("e017_map50", 0.50)
make("e017_map100", 1.0)   # bound: map only

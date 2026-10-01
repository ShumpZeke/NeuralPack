"""E030 prototype: top-block trimming for every language (line windows).

Top-block trimming (E005c) is Python-only: members come from the Python AST.
Outside Python an oversized top-ranked block is skipped, and on the
multilingual dev split the blocks that cover missed fix sites are large
(median 1,086 tokens for C/C++, 735 for JS/TS). Here a non-Python top block
that does not fit is cut into fixed windows of ``window`` lines, ranked with
the same file-local BM25 as Python members, and admitted in rank order while
they fit. Python blocks keep their AST members, so Python selections are
unchanged.
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector
from npk.pack.select import Evidence

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


class WindowTrimSelector(PackSelector):
    window = 20

    def _admit_members(self, con, blk, query, budget, evidence: List[Evidence], used_chars, score,
                       channels, notes):
        if blk.path.endswith((".py", ".pyi")) or blk.tokens < sel.TRIM_MIN_TOKENS:
            return super()._admit_members(con, blk, query, budget, evidence, used_chars, score,
                                          channels, notes)
        lines = blk.text.split("\n")
        members = [(blk.start_line + i, min(blk.start_line + i + self.window - 1, blk.end_line),
                    "window", blk.name or "") for i in range(0, len(lines), self.window)]
        if len(members) <= 1:
            return used_chars
        added = 0
        for start, end, kind, name, text in sel._rank_members(con, blk, members, query):
            if not text.strip() or not self._fits(evidence, text, budget, used_chars=used_chars):
                continue
            used_chars += len(text) + (2 if evidence else 0)
            evidence.append(Evidence(
                block_id=blk.id, path=blk.path, span=f"{blk.path}:{start}-{end}",
                kind=kind, name=name, tokens=max(1, len(text) // 4), text=text,
                score=score, channels=list(channels) + ["trimmed"]))
            added += 1
        if added:
            notes.append(f"top-ranked block {blk.span} exceeds the budget; emitted {added} of its "
                         f"{len(members)} line windows")
        return used_chars


def make(name: str, window: int) -> Arm:
    cls = type(f"WindowTrim{window}", (WindowTrimSelector,), {"window": window})

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


make("e030_window20", 20)
make("e030_window40", 40)

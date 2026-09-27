"""E050 prototype: fit-or-trim for every ranked block, not only the top one.

Top-block trimming (E005c) admits the best member spans of the top-ranked
block when it alone exceeds the budget; any lower-ranked block that no longer
fits is skipped whole, and the fill moves on to smaller, lower-ranked blocks.
On dev-fast (E039 default) the fill often skips gold blocks ranked above its
last admitted block: at 2K, 28 such blocks hold 32 fix hunks the selection
misses (21% of dev-fast's 153) and 33 blocks hold 43 missed test hunks; at 4K,
22 fix and 28 test hunks; at 8K, 17 and 17. Most are large Python classes.

Here the first ``blocks`` lower-ranked Python classes that do not fit (in rank
order) admit their best member spans (file-local BM25, as for the top block)
that still fit, at most ``k`` each, and the fill goes on. The top block is
trimmed as in the product. Skipping is common (about 17 trimmable classes per
2K selection on dev-fast) and gold is spread among them (the first skipped
class holds 7 of the 26 gold ones at 2K, the first three 11), so both caps
matter. ``e050_control`` trims only the top block through this re-implemented
fill and must equal ``npk_default`` (60/60 dev-fast selections checked).
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


class TrimRankedSelector(PackSelector):
    trim_lower = True
    k: Optional[int] = None
    blocks: Optional[int] = None

    def _select_once(self, con, manifest, query, budget, limit):
        captured: Dict[str, object] = {}
        original = sel.load_blocks

        def spy(connection, ids):
            out = original(connection, ids)
            captured["ids"] = list(ids)
            captured["blocks"] = {b.id: b for b in out}
            return out

        sel.load_blocks = spy
        try:
            base = super()._select_once(con, manifest, query, budget, limit)
        finally:
            sel.load_blocks = original
        if "ids" not in captured or not base.evidence:
            return base
        ids: List[int] = captured["ids"]            # type: ignore[assignment]
        blocks = captured["blocks"]                 # type: ignore[assignment]
        score = {e.block_id: (e.score, e.channels) for e in base.evidence}
        evidence: List[sel.Evidence] = []
        used_chars = 0
        top = ids[0]
        trimmed = 0
        for block_id in ids:
            blk = blocks.get(block_id)
            if blk is None:
                continue
            if not self._fits(evidence, blk.text, budget, used_chars=used_chars):
                if self.enable_trim and block_id == top:
                    used_chars = self._admit_up_to(con, blk, query, budget, evidence, used_chars, None)
                elif (self.enable_trim and self.trim_lower
                        and (self.blocks is None or trimmed < self.blocks)
                        and blk.path.endswith((".py", ".pyi")) and blk.tokens >= sel.TRIM_MIN_TOKENS):
                    trimmed += 1
                    used_chars = self._admit_up_to(con, blk, query, budget, evidence, used_chars, self.k)
                continue
            used_chars += len(blk.text) + (2 if evidence else 0)
            s, channels = score.get(block_id, (0.0, []))
            evidence.append(sel.Evidence(
                block_id=blk.id, path=blk.path, span=blk.span, kind=blk.kind,
                name=blk.name, tokens=blk.tokens, text=blk.text, score=s, channels=list(channels)))
        base.evidence = evidence
        base.total_tokens = self._count(evidence)
        return base

    def _admit_up_to(self, con, blk, query, budget, evidence, used_chars, k):
        """``_admit_members`` with at most *k* admitted members (None: no cap)."""
        if not blk.path.endswith((".py", ".pyi")) or blk.tokens < sel.TRIM_MIN_TOKENS:
            return used_chars
        members = sel._member_spans(con, blk)
        if len(members) <= 1:
            return used_chars
        added = 0
        for start, end, kind, name, text in sel._rank_members(con, blk, members, query):
            if k is not None and added >= k:
                break
            if not text.strip() or not self._fits(evidence, text, budget, used_chars=used_chars):
                continue
            used_chars += len(text) + (2 if evidence else 0)
            evidence.append(sel.Evidence(
                block_id=blk.id, path=blk.path, span=f"{blk.path}:{start}-{end}",
                kind=kind, name=name, tokens=max(1, len(text) // 4), text=text,
                score=0.0, channels=["trimmed"]))
            added += 1
        return used_chars


def make(name: str, *, trim_lower: bool, k: Optional[int] = None, blocks: Optional[int] = None) -> Arm:
    cls = type(f"TrimRanked_{name}", (TrimRankedSelector,),
               {"trim_lower": trim_lower, "k": k, "blocks": blocks})

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


make("e050_control", trim_lower=False)   # the product's fill, re-implemented: must equal npk_default
make("e050_first1_k2", trim_lower=True, blocks=1, k=2)
make("e050_first3_k1", trim_lower=True, blocks=3, k=1)
make("e050_all_k1", trim_lower=True, k=1)

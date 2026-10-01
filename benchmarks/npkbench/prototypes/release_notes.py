"""E054 prototype: historical release notes go to the end of the ranking.

Changelogs, release notes and release blog posts describe past changes in the
issue's own vocabulary, often with the same code examples, so they rank high:
at 2K they take 9.2% of the selected lines on poly-dev-b (prettier's release
posts, svelte's CHANGELOG.md), 2.4-3.0% on gym-dev and ood-multi-dev and 0.5% on
dev. They are almost never where a fix goes: of 5,193 fix hunks on those four
splits (with dev), 74 are release-note entries and the default finds 2 of them at 2K (a
new entry goes at the top of the current notes, not into the historical block
that matched). The docs target already excludes release notes as not topical.

``e054_notes_last`` moves every block of a release-note file (``CHANGELOG``,
``CHANGES``, ``HISTORY``, ``NEWS``, ``RELEASE-NOTES``, ``whatsnew``, ``blog/`` and
``releases/`` paths) behind all other candidates, keeping both groups' order;
the fill (with top-block trimming for the new top) is the product's, re-run on
the new order. ``e054_control`` re-runs the fill without reordering and must
equal ``npk_default``.
"""
from __future__ import annotations

import importlib
import re
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")

_RELEASE_WORDS = re.compile(
    r"(^|/)(changelog|changes|history|news|release[-_ ]?notes?|whatsnew|blog|releases?)([-_./]|$)", re.IGNORECASE)
#: Prose files only: a code module named history.js or releases/ stays where it ranks.
_PROSE = re.compile(r"\.(md|mdx|rst|txt|adoc|html)$|(^|/)[A-Z][A-Z_-]*$", re.IGNORECASE)


class _ReleaseNotes:
    @staticmethod
    def search(path: str) -> bool:
        return bool(_RELEASE_WORDS.search(path)) and bool(_PROSE.search(path))


RELEASE_NOTES = _ReleaseNotes()


class NotesLastSelector(PackSelector):
    reorder = True

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
        if self.reorder:
            notes = [b for b in ids if b in blocks and RELEASE_NOTES.search(blocks[b].path)]
            if not notes:
                return base
            ids = [b for b in ids if b not in set(notes)] + notes
        score = {e.block_id: (e.score, e.channels) for e in base.evidence}
        evidence: List[sel.Evidence] = []
        used_chars = 0
        top = ids[0]
        for block_id in ids:
            blk = blocks.get(block_id)
            if blk is None:
                continue
            if not self._fits(evidence, blk.text, budget, used_chars=used_chars):
                if block_id == top and self.enable_trim:
                    used_chars = self._admit_top(con, blk, query, budget, evidence, used_chars)
                continue
            used_chars += len(blk.text) + (2 if evidence else 0)
            s, channels = score.get(block_id, (0.0, []))
            evidence.append(sel.Evidence(
                block_id=blk.id, path=blk.path, span=blk.span, kind=blk.kind,
                name=blk.name, tokens=blk.tokens, text=blk.text, score=s, channels=list(channels)))
        base.evidence = evidence
        base.total_tokens = self._count(evidence)
        return base

    def _admit_top(self, con, blk, query, budget, evidence, used_chars):
        """The product's top-block trimming (``_admit_members``), without its note."""
        if not blk.path.endswith((".py", ".pyi")) or blk.tokens < sel.TRIM_MIN_TOKENS:
            return used_chars
        members = sel._member_spans(con, blk)
        if len(members) <= 1:
            return used_chars
        for start, end, kind, name, text in sel._rank_members(con, blk, members, query):
            if not text.strip() or not self._fits(evidence, text, budget, used_chars=used_chars):
                continue
            used_chars += len(text) + (2 if evidence else 0)
            evidence.append(sel.Evidence(
                block_id=blk.id, path=blk.path, span=f"{blk.path}:{start}-{end}",
                kind=kind, name=name, tokens=max(1, len(text) // 4), text=text,
                score=0.0, channels=["trimmed"]))
        return used_chars


def make(name: str, reorder: bool) -> Arm:
    cls = type(f"NotesLast_{name}", (NotesLastSelector,), {"reorder": reorder})

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


make("e054_control", reorder=False)   # the product's fill re-run: must equal npk_default
make("e054_notes_last", reorder=True)

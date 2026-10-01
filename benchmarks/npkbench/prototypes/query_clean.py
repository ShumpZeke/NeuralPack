"""E031 prototype: remove issue-template structure from the query.

GitHub issue forms add structure that is not the user's content: section
headings ("Steps to reproduce", "Expected Behavior", "Environment"), checklist
items ("- [x] I searched existing issues") and HTML-comment instructions
("<!-- Please describe... -->"). Those words are rare in code (high IDF) but
common in CONTRIBUTING.md, README.md and changelogs, which then outrank code
(on the multilingual dev split, CONTRIBUTING.md and README.md fill 35 of the
2K selections for JS issues). 137/186 multilingual and 30/103 Python dev
issues carry template headings.

``e031_clean`` drops HTML comments, checklist lines and short heading lines
(markdown ``#`` headings or bold-only lines of at most six words); the first
line (the issue title) is always kept. ``e031_comments`` drops only HTML
comments and checklist lines.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
CHECKLIST = re.compile(r"^\s*[-*+]\s*\[[ xX]\]")
HEADING = re.compile(r"^\s*(?:#{1,6}\s+(?P<h>.+?)\s*#*|\*\*(?P<b>[^*]+)\*\*\s*:?)\s*$")


def clean_query(query: str, *, headings: bool = True) -> str:
    text = COMMENT.sub(" ", query)
    lines = text.split("\n")
    kept = lines[:1]
    for line in lines[1:]:
        if CHECKLIST.match(line):
            continue
        if headings:
            m = HEADING.match(line)
            if m and len((m.group("h") or m.group("b") or "").split()) <= 6:
                continue
        kept.append(line)
    cleaned = "\n".join(kept)
    return cleaned if cleaned.strip() else query


def make(name: str, headings: bool) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        query = clean_query(task.query, headings=headings)
        out: Dict[int, ArmResult] = {}
        with PackSelector(str(pack), enable_cache=False) as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e031_clean", headings=True)
make("e031_comments", headings=False)

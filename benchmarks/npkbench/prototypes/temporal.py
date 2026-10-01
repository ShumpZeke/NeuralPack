"""M005 prototype: temporal grounding for dated conversation memory.

Questions such as "What gardening-related activity did I do two weeks ago?" or
"How many museums did I visit in the month of February?" point at a time
window relative to when they are asked. Lexical retrieval cannot do date
arithmetic, so evidence from the right week competes with every other session
that shares the topic words. Here relative time expressions are resolved
against the question date (``Task.created_at``; a product would take it as
``as_of``) into a window. Lexical candidates whose session date lies in the
window form one extra RRF channel. Questions without a resolvable expression
are unchanged.

Reporting lag: people talk about events after they happen ("I visited two
galleries in February", said on March 3). A window therefore runs from the
start of the referenced period (with slack) to the question date.

Session dates come from the materialized path ``sessions/YYYY-MM-DD_...``.
"""
from __future__ import annotations

import calendar
import contextlib
import datetime as dt
import importlib
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

select_module = importlib.import_module("npk.pack.select")

NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "couple": 2,
           "few": 3}
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
SLACK = {"day": 1, "week": 3, "month": 10, "year": 45}
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
Window = Tuple[dt.date, dt.date]


def question_date(created_at: str) -> Optional[dt.date]:
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", created_at or "")
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _count(word: str) -> Optional[int]:
    return int(word) if word.isdigit() else NUMBERS.get(word)


def windows(query: str, ref: dt.date) -> List[Window]:
    """Date windows named by relative time expressions in *query* (may be empty).

    A point expression ("two weeks ago", "last Tuesday") gives a window around
    that date; a period ("in February", "past month", "since ... ago") gives
    ``(period start - slack, question date)``.
    """
    q = query.lower()
    starts: List[dt.date] = []
    number = (r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|couple of|couple|few)")
    points: List[Window] = []
    for since, num, unit in re.findall(r"\b(since\b[^.?!]{0,60}?\b)?" + number
                                       + r"\s+(?:of\s+)?(day|week|month|year)s?\s+ago\b", q):
        n = _count(num.split()[0])
        if n:
            center = ref - dt.timedelta(days=n * UNIT_DAYS[unit])
            slack = dt.timedelta(days=SLACK[unit] * (1 + n // 3))
            if since:  # "since ... three weeks ago" names a period that runs to now
                starts.append(center - slack)
            else:      # a point in time: the event and its report are close together
                points.append((center - slack, center + slack))
    for num, unit in re.findall(r"\b(?:past|last|previous)\s+" + number + r"\s+(day|week|month|year)s?\b", q):
        n = _count(num.split()[0])
        if n:
            starts.append(ref - dt.timedelta(days=n * UNIT_DAYS[unit] + SLACK[unit]))
    for unit in re.findall(r"\b(?:past|last|previous)\s+(day|week|month|year)\b", q):
        starts.append(ref - dt.timedelta(days=UNIT_DAYS[unit] + SLACK[unit]))
    if re.search(r"\byesterday\b", q):
        points.append((ref - dt.timedelta(days=2), ref))
    for day in re.findall(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", q):
        target = ref - dt.timedelta(days=(ref.weekday() - WEEKDAYS[day]) % 7 or 7)
        points.append((target - dt.timedelta(days=1), target + dt.timedelta(days=1)))
    if re.search(r"\b(?:this|the)\s+year\b|\bsince the (?:start|beginning) of the year\b", q):
        starts.append(dt.date(ref.year, 1, 1))
    for month in re.findall(r"\b(?:in|during|of)\s+(?:the\s+month\s+of\s+)?(" + "|".join(MONTHS) + r")\b", q):
        m = MONTHS[month]
        starts.append(dt.date(ref.year if m <= ref.month else ref.year - 1, m, 1))
    return points + [(start, ref) for start in starts]


def session_date(path: str) -> Optional[dt.date]:
    m = re.search(r"(?:^|/)(\d{4})-(\d{2})-(\d{2})_", path)
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


@contextlib.contextmanager
def _window_channel(spans: List[Window], depth: int):
    original = (select_module._embedding_channel, select_module._symbol_channel)
    lexical = select_module._lexical_channel

    def channel(con, query, limit, manifest):
        if not spans:
            return [], None
        ranked = lexical(con, query, depth)
        if not ranked:
            return [], None
        marks = ",".join("?" * len(ranked))
        paths = dict(con.execute(f"SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id "
                                 f"WHERE b.id IN ({marks})", ranked).fetchall())
        keep = []
        for block_id in ranked:
            day = session_date(paths.get(block_id, ""))
            if day is not None and any(lo <= day <= hi for lo, hi in spans):
                keep.append(block_id)
        return keep[:limit], None

    select_module._embedding_channel = channel
    select_module._symbol_channel = lambda con, query, limit: []
    try:
        yield
    finally:
        select_module._embedding_channel, select_module._symbol_channel = original


def make(name: str, depth: int = 1000) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        ref = question_date(task.created_at)
        spans = windows(task.query, ref) if ref else []
        out: Dict[int, ArmResult] = {}
        with _window_channel(spans, depth), PackSelector(str(pack), enable_cache=False, retrieval="hybrid") as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence), extra={"windows": [[a.isoformat(), b.isoformat()] for a, b in spans]})
        return out

    return register(Arm(name, runner=runner))


make("m005_time_window")

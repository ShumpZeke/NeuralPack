"""E055 prototype: the functions named by an issue's traceback frames as a ranked channel.

A traceback names the exact functions the failure passed through, innermost last. On
the Python screening splits the frame's own function is often where the fix goes, and
the default misses many of those sites: on ``gym-dev`` 47 of 326 issues carry a
traceback, 32 have a fix hunk inside a frame's function (57 hunks; the innermost frame
is the fix site in 19), and the default covers 20 of the 57 at 1K and 32 at 2K; on
``dev`` 61 of 300 issues carry one, 38 have such a hunk (45 hunks; innermost frame 18),
and the default covers 29 at 1K and 27 at 2K. The lexical and definition channels see
the frame's words, but a function name such as ``__getitem__`` or ``visit_call_expr``
is defined in many places and its file path is only a few more words.

Frames are read in the formats Python users paste: CPython (``File "p", line N, in f``),
IPython 8 (``File p:N, in f(``), IPython 7 (``p in f(``) and pytest (``p:N: in f``). A
frame's path is resolved to a pack file by its longest path suffix (after
``site-packages/`` when present); its function to the block(s) of that file defining
the name (the frame's line picks among same-named definitions; a ``Class.method``
qualifier picks the class's blocks), and a ``<module>``/``<lambda>``/comprehension
frame to the block containing its line. Frames outside the repository (the user's
script, other libraries) resolve to nothing. Blocks are ranked innermost frame first
and fused with the other channels by RRF like any channel.

Arms: ``e055_frames`` (every resolved frame), ``e055_frames3`` (the three innermost
resolved frames), ``e055_frames_2k`` (E055b: every resolved frame, from 2K only) and
``e055_control`` (the same selector with an empty channel; must equal ``npk_default``).
The prototype uses the selector's hybrid slot: on a pack without
embeddings, hybrid retrieval differs from lexical only by fusing ``_symbol_channel``,
which is replaced here by the traceback channel.
"""
from __future__ import annotations

import contextlib
import importlib
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")

_PY = r"\.pyx?"
FRAME_PATTERNS = (
    re.compile(r'File "(?P<path>[^"\n]+?' + _PY + r')", line (?P<line>\d+)(?:, in (?P<func>[\w<>.]+))?'),
    re.compile(r'File (?P<path>[^\s"]+?' + _PY + r'):(?P<line>\d+)(?:, in (?P<func>[\w<>.]+))?'),
    re.compile(r'^[ \t]*(?P<path>(?:~|/|[A-Za-z]:\\)\S*?' + _PY + r') in (?P<func>[\w<>.]+)\(', re.M),
    re.compile(r'^[ \t]*(?P<path>[^\s:"]+?' + _PY + r'):(?P<line>\d+): in (?P<func>[\w<>.]+)', re.M),
)
#: A frame whose function name has more definitions than this in its file, and no
#: line to choose among them, is skipped.
MAX_SAME_NAME = 3


def frames(text: str) -> List[Tuple[str, Optional[int], Optional[str]]]:
    """(path, line, function) for every frame, in text order (innermost last)."""
    found = {}
    for pattern in FRAME_PATTERNS:
        for m in pattern.finditer(text):
            line = m.groupdict().get("line")
            found.setdefault(m.start(), (m.group("path"), int(line) if line else None, m.group("func")))
    return [found[k] for k in sorted(found)]


def _tail(path: str) -> str:
    path = path.replace("\\", "/")
    for marker in ("/site-packages/", "/dist-packages/"):
        if marker in path:
            return path.rsplit(marker, 1)[1]
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def resolve_path(path: str, by_name: Dict[str, List[str]]) -> Optional[str]:
    """The pack file a frame path names: the longest path-boundary suffix match."""
    tail = _tail(path)
    best = None
    for candidate in by_name.get(tail.rsplit("/", 1)[-1], ()):
        if candidate == tail:
            ok = True
        elif "/" in candidate and tail.endswith("/" + candidate):
            ok = True                       # an absolute checkout path
        elif "/" in tail and candidate.endswith("/" + tail):
            ok = True                       # an installed path under src/ or similar
        else:
            ok = False
        if ok and (best is None or len(candidate) > len(best)):
            best = candidate
    return best


def _frame_blocks(con, file_path: str, line: Optional[int], func: Optional[str]) -> List[int]:
    if func and not func.startswith("<"):
        qualifier, _, name = func.rpartition(".")
        rows = con.execute(
            "SELECT b.id, b.start_line, b.end_line, b.name FROM symbols s JOIN blocks b ON b.id=s.block_id "
            "JOIN files f ON f.id=b.file_id WHERE s.is_def=1 AND s.name=? AND f.path=? "
            "ORDER BY b.start_line", (name, file_path)).fetchall()
        if qualifier:
            owner = qualifier.rsplit(".", 1)[-1]
            rows = [r for r in rows if r[3] == owner] or rows
        if line is not None:
            rows = [r for r in rows if r[1] <= line <= r[2]] or rows
        if len(rows) > MAX_SAME_NAME:
            return []
        return [r[0] for r in rows]
    if line is None:
        return []
    rows = con.execute(
        "SELECT b.id FROM blocks b JOIN files f ON f.id=b.file_id WHERE f.path=? AND b.start_line<=? "
        "AND b.end_line>=? ORDER BY b.start_line", (file_path, line, line)).fetchall()
    return [r[0] for r in rows]


def traceback_channel(con, query: str, limit: int, max_frames: Optional[int] = None) -> List[int]:
    parsed = frames(query)
    if not parsed:
        return []
    by_name: Dict[str, List[str]] = {}
    for (path,) in con.execute("SELECT path FROM files"):
        if path.endswith((".py", ".pyx", ".pyi")):
            by_name.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    ranked: List[int] = []
    used_frames = 0
    for path, line, func in reversed(parsed):
        file_path = resolve_path(path, by_name)
        if file_path is None:
            continue
        blocks = [b for b in _frame_blocks(con, file_path, line, func) if b not in ranked]
        if not blocks:
            continue
        ranked.extend(blocks)
        used_frames += 1
        if (max_frames is not None and used_frames >= max_frames) or len(ranked) >= limit:
            break
    return ranked[:limit]


@contextlib.contextmanager
def _channel(max_frames: Optional[int], enabled: bool):
    original = sel._symbol_channel

    def channel(con, query, limit):
        return traceback_channel(con, query, limit, max_frames) if enabled else []

    sel._symbol_channel = channel
    try:
        yield
    finally:
        sel._symbol_channel = original


def make(name: str, max_frames: Optional[int] = None, enabled: bool = True, min_budget: int = 0) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        for budget in budgets:
            with _channel(max_frames, enabled and budget >= min_budget), \
                    PackSelector(str(pack), retrieval="hybrid", enable_cache=False) as selector:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e055_control", enabled=False)       # hybrid slot left empty: must equal npk_default
make("e055_frames")
make("e055_frames3", max_frames=3)
# E055b (declared after the dev screen): the channel only from 2K, as the test mate is gated;
# 1K selections are the default's by construction.
make("e055_frames_2k", min_budget=2048)

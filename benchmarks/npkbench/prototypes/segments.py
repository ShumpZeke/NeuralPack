"""E022 prototype: segment-aware lexical retrieval (prose vs. code in the issue).

80 of 103 dev-fast issues contain code (fences, Trac ``{{{ }}}`` blocks,
tracebacks, indented or ``>>>`` lines); the median issue is 36% code by words.
One OR query sums BM25 over every term, so a long reproduction script's rare
user-code identifiers (``Book``, ``Author``, local variables) can outvote the
prose that describes the bug, and vice versa. Here each segment gets its own
lexical channel and RRF gives each an equal vote. The definition and relation
channels, greedy fill and trimming are the product's.

Channels are injected through the selector's hybrid-mode hooks, so exactly the
listed lexical channels are fused (``_symbol_channel`` is disabled).
"""
from __future__ import annotations

import contextlib
import importlib
import re
import time
from pathlib import Path
from typing import Dict, Sequence, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

select_module = importlib.import_module("npk.pack.select")

FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
TRAC = re.compile(r"\{\{\{.*?(?:\}\}\}|\Z)", re.S)
TRACEBACK = re.compile(r"Traceback \(most recent call last\):.*?(?=\n\S|\Z)", re.S)
CODE_LINE = re.compile(r"^(    |\t|>>> |\.\.\. |\$ )")


def split_query(query: str) -> Tuple[str, str]:
    """(prose, code) parts of an issue text; code keeps its original order."""
    code = []

    def grab(match):
        code.append(match.group(0))
        return "\n"

    rest = TRACEBACK.sub(grab, TRAC.sub(grab, FENCE.sub(grab, query)))
    prose = []
    for line in rest.split("\n"):
        (code if CODE_LINE.match(line) else prose).append(line)
    return "\n".join(prose), "\n".join(code)


@contextlib.contextmanager
def _channels(primary: str, extra: str):
    """Lexical channel over *primary*; one extra lexical channel over *extra*."""
    original = (select_module._lexical_channel, select_module._embedding_channel,
                select_module._symbol_channel)
    lexical = original[0]
    select_module._lexical_channel = lambda con, query, limit: lexical(con, primary, limit) if primary.strip() else []
    select_module._embedding_channel = (lambda con, query, limit, manifest:
                                        (lexical(con, extra, limit) if extra.strip() else [], None))
    select_module._symbol_channel = lambda con, query, limit: []
    try:
        yield
    finally:
        (select_module._lexical_channel, select_module._embedding_channel,
         select_module._symbol_channel) = original


def make(name: str, mode: str) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        prose, code = split_query(task.query)
        primary, extra = {"split": (prose, code), "full_plus_code": (task.query, code),
                          "full_plus_prose": (task.query, prose)}[mode]
        out: Dict[int, ArmResult] = {}
        with _channels(primary, extra), PackSelector(str(pack), enable_cache=False, retrieval="hybrid") as selector:
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


make("e022_split", "split")
make("e022_full_plus_code", "full_plus_code")
make("e022_full_plus_prose", "full_plus_prose")

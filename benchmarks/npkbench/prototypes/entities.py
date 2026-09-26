"""E023 prototype: cleaner entity extraction for the definition channel (E002).

Failure analysis (django-11964, dev): the issue's reproduction code imports
``from django.utils.translation import gettext_lazy`` and subclasses
``TestCase``. Every dotted part becomes an entity, so ``translation`` (a
function in trans_real.py), ``django`` (a property of OGRGeomType) and
``TestCase`` get strong definition votes, while the gold ``enums.py`` blocks
that define the named ``TextChoices``/``IntegerChoices`` sink below them.

Two principled changes, tested separately and together:

* ``tail``: module paths of import statements are dropped, and from any other
  dotted reference only its final component and its capitalized components are
  kept. Lowercase non-final parts are module paths or variables
  (``django.utils.``, ``self.``, ``obj.``), not the entity referenced.
* ``codehalf``: names mentioned only inside the issue's code segments (fences,
  Trac blocks, tracebacks, indented lines; see E022) vote with half weight;
  names in the prose that describes the problem keep full weight.
"""
from __future__ import annotations

import contextlib
import importlib
import math
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Set, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task
from .segments import split_query

sel = importlib.import_module("npk.pack.select")


IMPORT_PATH = re.compile(r"(?m)^(\s*(?:>>>\s*)?)(from\s+[\w.]+\s+import\b|import\s+[\w.]+(?:\s*,\s*[\w.]+)*)")


def tail_entities(query: str) -> List[str]:
    # Module paths in import statements name modules, not the entity at issue.
    query = IMPORT_PATH.sub(lambda m: m.group(1) + " ", query)
    names: List[str] = []
    for match in sel._DOTTED_NAME.finditer(query):
        parts = match.group(0).split(".")
        if all(len(part) <= 2 for part in parts):
            continue
        keep = [p for i, p in enumerate(parts) if i == len(parts) - 1 or p[:1].isupper()]
        names.extend(p for p in keep if len(p) >= 3 and p.lower() not in sel.FUNCTION_WORDS)
    names.extend(m.group(1) for m in sel._CALLED_NAME.finditer(query) if len(m.group(1)) >= 3)
    for match in sel._BACKTICKED.finditer(query):
        names.extend(w for w in sel._IDENT_WORD.findall(match.group(1)) if len(w) >= 3)
    names.extend(w for w in sel._IDENT_WORD.findall(query) if sel._code_like(w))
    return list(dict.fromkeys(names))


def definition_channel(con: sqlite3.Connection, query: str, limit: int, lexical: Sequence[int], *,
                       extract: Callable[[str], List[str]], code_weight: float) -> List[int]:
    """The product's channel with a pluggable extractor and per-name weights."""
    names = extract(query)
    if not names:
        return []
    prose_names: Set[str] = set(extract(split_query(query)[0])) if code_weight != 1.0 else set(names)
    marks = ",".join("?" * len(names))
    try:
        rows = con.execute(
            "SELECT s.name, s.block_id, f.path, b.ordinal FROM symbols s "
            "JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id "
            f"WHERE s.is_def=1 AND s.name IN ({marks})", tuple(names)).fetchall()
    except sqlite3.OperationalError:
        return []
    by_name: Dict[str, Set[int]] = {}
    position: Dict[int, Tuple[str, int]] = {}
    for row in rows:
        by_name.setdefault(row[0], set()).add(row[1])
        position[row[1]] = (row[2], row[3])
    score: Dict[int, float] = {}
    for name, blocks in by_name.items():
        if len(blocks) > sel.MAX_DEFINITION_AMBIGUITY:
            continue
        weight = (1.0 if name in prose_names else code_weight) / math.log2(1 + len(blocks))
        for block_id in blocks:
            score[block_id] = score.get(block_id, 0.0) + weight
    lexical_rank = {block_id: rank for rank, block_id in enumerate(lexical)}
    unranked = len(lexical_rank)
    ordered = sorted(score, key=lambda b: (-score[b], lexical_rank.get(b, unranked), position[b]))
    return ordered[:limit]


@contextlib.contextmanager
def _patched(extract: Callable[[str], List[str]], code_weight: float):
    original = sel._definition_channel
    sel._definition_channel = (lambda con, query, limit, lexical:
                               definition_channel(con, query, limit, lexical,
                                                  extract=extract, code_weight=code_weight))
    try:
        yield
    finally:
        sel._definition_channel = original


def make(name: str, *, tail: bool, code_weight: float) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        extract = tail_entities if tail else sel._query_entities
        out: Dict[int, ArmResult] = {}
        with _patched(extract, code_weight), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e023_control", tail=False, code_weight=1.0)   # reimplementation must equal npk_default
make("e023_tail", tail=True, code_weight=1.0)
make("e023_codehalf", tail=False, code_weight=0.5)
make("e023_tail_codehalf", tail=True, code_weight=0.5)

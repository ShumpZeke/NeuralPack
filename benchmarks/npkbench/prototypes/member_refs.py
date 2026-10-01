"""E049 prototype: qualified member references resolve brace-language methods.

The brace splitter names a method block by its type (``PojoUtils.realize``),
and that qualified name is the method's only definition symbol: Java methods
have no ``def``/``function`` keyword for ``DEF_RE`` to find. The definition
channel looks up the query's entities, which split dotted references into
their parts (``PojoUtils``, ``realize`` is dropped as prose-like), so a Java or
JS/TS method named in an issue never resolves; the class name resolves to its
context fragments instead (E048). Issues name members as ``Type#member``
(Javadoc/JSDoc; 10 of 199 poly-dev issues, none on the Python dev split),
``Type::member`` (C++/PHP/Rust) or ``Type.member``.

``e049_members`` adds ``Type.member`` (the last two parts) to the entities for
each such reference, plus ``Type`` and ``member`` for ``#``/``::`` forms, so the
channel votes for the method blocks themselves. Python packs name no blocks
this way (their methods are ``def`` definitions), so Python selections should
not move. ``e049_members_e047`` also applies E047's strict test conventions.
"""
from __future__ import annotations

import contextlib
import importlib
import re
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task
from . import test_conventions

sel = importlib.import_module("npk.pack.select")

_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
MEMBER_REF = re.compile(rf"(?<![\w.$#:/-])((?:{_IDENT}(?:\.|::))*{_IDENT})(?:#|::)({_IDENT})(?![\w$])")


def _type_name(word: str) -> bool:
    """Owners are types: capitalized and at least three characters (not ``std``, ``html``)."""
    return len(word) >= 3 and word[0].isupper()


def member_entities(query: str) -> List[str]:
    extra: List[str] = []
    for match in sel._DOTTED_NAME.finditer(query):
        parts = match.group(0).split(".")
        if _type_name(parts[-2]) and len(parts[-1]) >= 3:
            extra.append(f"{parts[-2]}.{parts[-1]}")
    for match in MEMBER_REF.finditer(query):
        owner, member = re.split(r"\.|::", match.group(1))[-1], match.group(2)
        if _type_name(owner) and len(member) >= 3:
            extra.extend((owner, member, f"{owner}.{member}"))
    return extra


def _make_entities(original):
    def query_entities(query: str) -> List[str]:
        return list(dict.fromkeys(original(query) + member_entities(query)))
    return query_entities


@contextlib.contextmanager
def _patched():
    original = sel._query_entities
    sel._query_entities = _make_entities(original)
    try:
        yield
    finally:
        sel._query_entities = original


def make(name: str, *, tests: bool = False) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with contextlib.ExitStack() as stack:
            stack.enter_context(_patched())
            if tests:
                stack.enter_context(test_conventions._patched(True, True, True))
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


make("e049_members")
make("e049_members_e047", tests=True)

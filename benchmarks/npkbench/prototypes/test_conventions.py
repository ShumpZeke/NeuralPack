"""E047 prototype: test-file conventions beyond Python.

The test mate (E016c) and the choice of the top implementation file rely on
``TEST_PATH``, which knows Python's conventions only (``tests/``, ``test_*.py``,
``*_test.py``, ``conftest.py``). On SWE-PolyBench's ``poly-dev``, colocated
JS/TS tests (``Button.test.js``, ``__tests__/``) count as implementation files,
so no mate is placed for them and they can be taken as the top implementation
file; and Java's ``FooTest.java`` never mirrors ``Foo.java`` (``footest`` is one
path part), so the mate ties among every test of the package, or among any
tests that share four generic parts (``java``, ``org``, ``apache``, ...).
Offline, on P001's 2K selections, the mate file is a gold test file for 24 of
173 tests-target issues with the current rules and for 51 with these
conventions (Java 16 -> 26, JavaScript 6 -> 12, TypeScript 2 -> 13).

* ``e047_paths``: ``TEST_PATH`` also recognizes the conventions of the other
  languages the compiler reads: Jest ``__tests__/`` and ``*.test.*`` /
  ``*.spec.*`` JS/TS files; JUnit/PHPUnit/NUnit ``FooTest``, ``FooTests``,
  ``FooIT``, ``FooTestCase`` and ``TestFoo`` classes; Go ``*_test.go``;
  C/C++ ``*_test.c(c|pp)`` and ``*_unittest.c(c|pp)``; RSpec ``*_spec.rb``.
  None of these can match a ``.py`` path, so Python selections should not move.
* ``e047_affix``: also, a test file's name without its CamelCase test affix is
  one of its path parts (``ServiceConfigTest`` -> ``serviceconfig``), so it
  mirrors ``ServiceConfig.java`` like ``test_mod.py`` mirrors ``mod.py``.
* ``e047_strict``: also, a mate must share the module or package name; shared
  generic parts alone (score >= 1 from four 0.25 parts) no longer qualify.

Below 2K the mate is off, but ``TEST_PATH`` changes can still move nothing
there: it is read only by the mate, so 1K is unchanged by construction.
"""
from __future__ import annotations

import contextlib
import importlib
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")

EXTRA_TEST_PATTERNS = (
    r"(^|/)__tests__/",
    r"\.(test|spec)\.[cm]?[jt]sx?$",
    r"(^|/)[^/]*(Test|Tests|TestCase)\.(java|kt|scala|groovy|php|cs)$",
    r"(^|/)[^/]*[a-z0-9]IT\.(java|kt|scala|groovy)$",
    r"(^|/)Test[A-Z0-9][^/]*\.(java|kt|scala|groovy|php|cs)$",
    r"_test\.(go|c|cc|cpp)$",
    r"_unittest\.(c|cc|cpp)$",
    r"_spec\.rb$",
)
POLYGLOT_TEST_PATH = re.compile("|".join((sel.TEST_PATH.pattern,) + EXTRA_TEST_PATTERNS))
TEST_AFFIX = re.compile(r"^(?:Test(?=[A-Z0-9])(?P<prefixed>.+)|(?P<suffixed>.+?[a-z0-9])(?:Tests?|IT|TestCase|Spec))$")


def test_path_parts(path: str) -> List[str]:
    """Path parts of a test file, plus its name without a CamelCase test affix."""
    parts = sel._path_parts(path)
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", path.rsplit("/", 1)[-1])
    match = TEST_AFFIX.match(stem)
    if match:
        parts = parts + [(match.group("prefixed") or match.group("suffixed")).lower()]
    return parts


def _make_test_paths(affix: bool):
    def test_paths(con: sqlite3.Connection) -> List[Tuple[str, frozenset]]:
        parts = test_path_parts if affix else sel._path_parts
        return [(row[0], frozenset(parts(row[0]))) for row in con.execute("SELECT path FROM files")
                if sel.TEST_PATH.search(row[0])]
    return test_paths


def _make_strict_score(original):
    def mate_score(impl: str, test: str, test_parts: Optional[frozenset] = None,
                   impl_parts: Optional[List[str]] = None) -> float:
        ip = impl_parts if impl_parts is not None else sel._path_parts(impl)
        tp = test_parts if test_parts is not None else frozenset(sel._path_parts(test))
        if not ip or not tp:
            return 0.0
        module, parent = ip[-1], (ip[-2] if len(ip) > 1 else "")
        named = ((module in tp and module not in sel._GENERIC_PATH_PARTS)
                 or (parent and parent in tp and parent not in sel._GENERIC_PATH_PARTS))
        return original(impl, test, test_parts, impl_parts) if named else 0.0
    return mate_score


@contextlib.contextmanager
def _patched(paths: bool, affix: bool, strict: bool):
    saved = (sel.TEST_PATH, sel._test_paths, sel._mate_score)
    if paths:
        sel.TEST_PATH = POLYGLOT_TEST_PATH
    if affix:
        sel._test_paths = _make_test_paths(True)
    if strict:
        sel._mate_score = _make_strict_score(saved[2])
    try:
        yield
    finally:
        sel.TEST_PATH, sel._test_paths, sel._mate_score = saved


def make(name: str, *, paths: bool = False, affix: bool = False, strict: bool = False) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with _patched(paths, affix, strict), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e047_control")   # patches nothing: must equal npk_default
make("e047_paths", paths=True)
make("e047_affix", paths=True, affix=True)
make("e047_strict", paths=True, affix=True, strict=True)

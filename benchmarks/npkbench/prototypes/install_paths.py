"""E057 prototype: install and home-directory path prefixes removed from the retrieval query.

Python issues paste tracebacks and warnings whose paths start with the reporter's
environment: ``/Users/me/miniconda3/envs/py38/lib/python3.8/site-packages/pandas/core/frame.py``.
Only the part after ``site-packages/`` names the project's code; the prefix adds the same
words to every such issue (``site``, ``packages``, ``lib``, ``python3``, ``local``, ``usr``,
``home``, ``venv``, ``envs``, ``miniconda3`` and the user's name), repeated per frame and so
counted up to three times by E039's repetition weighting, and several of them are code
words (``site`` in ``AdminSite``, ``local``, ``lib``). They occur in 61 of 300 ``dev`` and 57
of 326 ``gym-dev`` queries, a median 10-11% of their analyzed terms (p90 26-34%).

``e057_paths`` rewrites every line but the title after E031/E052 cleaning, as E053 does for
URLs: a path prefix ending in ``site-packages/`` or ``dist-packages/`` is removed (the
package-relative path stays), then a Python installation prefix (``.../lib/python3.8/``),
then a home-directory prefix (``/Users/<name>/``, ``/home/<name>/``, ``C:\\Users\\<name>\\``).
The caller's query is reported unchanged.
"""
from __future__ import annotations

import contextlib
import importlib
import re
import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")

_SEGMENT = r"[^\s\"'`<>()\[\]{}|,;]"
PACKAGES = re.compile(rf"(?:[A-Za-z]:)?(?:{_SEGMENT}*?[\\/])?(?:site|dist)-packages[\\/]")
PYTHON_LIB = re.compile(rf"(?:[A-Za-z]:)?{_SEGMENT}*?[\\/]lib(?:64)?[\\/]python\d+(?:\.\d+)*[\\/]", re.IGNORECASE)
HOME = re.compile(r"(?:/Users|/home|[A-Za-z]:\\Users)[\\/][^\s\"'`<>()\[\]{}|,;\\/]+[\\/]", re.IGNORECASE)


def clean_paths(line: str) -> str:
    return HOME.sub("", PYTHON_LIB.sub("", PACKAGES.sub("", line)))


def _make_cleaner(original):
    def strip_issue_template(query: str) -> str:
        cleaned = original(query)
        lines = cleaned.split("\n")
        rewritten = "\n".join(lines[:1] + [clean_paths(line) for line in lines[1:]])
        return rewritten if rewritten.strip() else query
    return strip_issue_template


@contextlib.contextmanager
def _patched():
    original = sel._strip_issue_template
    sel._strip_issue_template = _make_cleaner(original)
    try:
        yield
    finally:
        sel._strip_issue_template = original


def make(name: str) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with _patched(), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e057_paths")

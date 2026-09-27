"""E052 prototype: strip environment/version dumps from the retrieval query.

Issue templates ask for ``pd.show_versions()``, ``xr.show_versions()``,
``sklearn.show_versions()``, ``pydantic.version.version_info()`` or
``dvc doctor`` output: dozens of ``package: version`` lines. Their package names
match the project's version-printing module (``pandas/util/_print_versions.py``,
``pydantic/version.py``) and its test better than any code the issue is about.
On gym-dev (default), 23 of 326 issues carry such a dump and 18 selections at 2K
include a version-printing file (pandas 8, pydantic 8); on dev, 7 and 3.

``e052_env`` extends issue-form cleaning (E031): a block of consecutive
``key: value`` lines (blank lines and bare ``Header:`` lines may sit inside it)
is removed when at least ``MIN_ENV_LINES`` of its values are version numbers
or ``None`` and such values make up at least half of its key-value lines.
Configuration snippets (``warn_return_any = True``) rarely have version numbers
in half their lines, so they stay; booleans do not count. The caller's query is still reported unchanged.
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

sel = importlib.import_module("npk.pack.select")

MIN_ENV_LINES = 3
_KV = re.compile(r"^\s*[A-Za-z_][\w .()/#\-]{0,40}?\s*(?:(?<!:):(?!:)|==?)\s*"
                 r"(?P<value>[^\s;{].{0,100}?)\s*,?\s*$")
_CODE_END = re.compile(r"[;{}]\s*$")
_ENV_VALUE = re.compile(r"\d+\.\d+|^(None|not installed)$", re.IGNORECASE)
_NEUTRAL = re.compile(r"^\s*$|^\s*[A-Za-z][\w .()\-]{0,40}:\s*$|^\s*(INSTALLED VERSIONS|[-=]{3,})\s*$",
                      re.IGNORECASE)


def strip_environment(text: str) -> str:
    lines = text.split("\n")
    out: List[str] = []
    block: List[str] = []
    env = kv = 0

    def flush() -> None:
        nonlocal block, env, kv
        if not (env >= MIN_ENV_LINES and 2 * env >= kv):
            out.extend(block)
        block, env, kv = [], 0, 0

    out.extend(lines[:1])   # the title is always kept (E031)
    for line in lines[1:]:
        match = _KV.match(line) if not _CODE_END.search(line) else None
        if match:
            kv += 1
            env += bool(_ENV_VALUE.search(match.group("value")))
            block.append(line)
        elif _NEUTRAL.match(line) and block:
            block.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


def _make_cleaner(original):
    def strip_issue_template(query: str) -> str:
        cleaned = strip_environment(original(query))
        return cleaned if cleaned.strip() else query
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


make("e052_env")

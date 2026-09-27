"""E053 prototype: keep only the informative parts of URLs in the retrieval query.

SWE-bench Lite removed issues with links, so the dev split has none, but on
the other benchmarks URLs are common (gym-dev 151 of 326 issues, poly-dev 122
of 199, ood-multi-dev 94 of 186). Their scheme, host and GitHub scaffolding add
the same few words to every such query (``https``, ``github``, ``com``,
``blob``, the organisation and project names, image-host words), which match
READMEs, docs and CI files; with E039's repetition weighting a query with
several links counts them up to three times.

``e053_urls`` rewrites each URL before retrieval, as E031/E052 clean the query:
image links (``![...](...)``, ``<img ...>``) and GitHub attachment URLs are
dropped; a GitHub ``blob``/``tree``/``raw`` link keeps only the repository path
it points to (``dask/dataframe/core.py``); other GitHub links (issues, pull
requests, commits) are dropped; any other URL keeps its path and fragment words
without the scheme and host. The caller's query is reported unchanged.
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

IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.IGNORECASE)
URL = re.compile(r"https?://[^\s)>\]\"'`<]+", re.IGNORECASE)
ATTACHMENT_HOSTS = ("user-images.githubusercontent.com", "private-user-images.githubusercontent.com")


def rewrite_url(match: "re.Match[str]") -> str:
    url = match.group(0)
    host, _, rest = url.split("://", 1)[1].partition("/")
    host = host.lower()
    if host in ATTACHMENT_HOSTS or rest.startswith("user-attachments/"):
        return " "
    if host in ("github.com", "www.github.com"):
        parts = rest.split("/")
        if len(parts) > 4 and parts[2] in ("blob", "tree", "raw"):
            return " " + "/".join(parts[4:]).split("#", 1)[0] + " "
        return " "
    return " " + rest.replace("/", " ").replace("#", " ") + " "


def clean_urls(text: str) -> str:
    return URL.sub(rewrite_url, IMAGE.sub(" ", text))


def _make_cleaner(original):
    def strip_issue_template(query: str) -> str:
        cleaned = original(query)
        lines = cleaned.split("\n")
        rewritten = "\n".join(lines[:1] + [clean_urls(line) for line in lines[1:]])
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


make("e053_urls")

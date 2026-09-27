"""E037 prototype: morphological query expansion in the lexical channel.

The analyzer keeps whole words and identifier parts but never stems, so an
issue about "choices", "migrations" or "serialization" does not match code
that says ``choice``, ``migration`` or ``serializer``. Here each query term is
expanded, at query time, with index terms (the pack's FTS5 vocabulary) that
share its form:

* ``e037_snowball``: the same Snowball English stem (up to three variants per
  term, most frequent first); aggressive (``serializer`` ~ ``serial``).
* ``e037_plural``: singular/plural forms only (``choices`` ~ ``choice``,
  ``policies`` ~ ``policy``).

Variants join the flat OR of the lexical MATCH, so a block that contains a
variant gains that variant's BM25 term. Definition, relation and test-mate
lookups, fill and trimming are the product's. Prototype only: the product has
no dependencies, so a kept variant would need an in-repository rule set.
"""
from __future__ import annotations

import contextlib
import importlib
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import snowballstemmer

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")
_STEM = snowballstemmer.stemmer("english")
_VOCAB: Dict[Tuple[str, str], Dict[str, List[str]]] = {}


def plural_base(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _groups(con: sqlite3.Connection, mode: str) -> Dict[str, List[str]]:
    path = next(row[2] for row in con.execute("PRAGMA database_list") if row[1] == "main")
    key = (path, mode)
    if key not in _VOCAB:
        side = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            side.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, lexical, 'row')")
            rows = side.execute("SELECT term, doc FROM temp.v").fetchall()
        finally:
            side.close()
        groups: Dict[str, List[Tuple[int, str]]] = {}
        for term, doc in rows:
            if len(term) < 4 or not term.isalpha():
                continue
            k = _STEM.stemWord(term) if mode == "snowball" else plural_base(term)
            groups.setdefault(k, []).append((-doc, term))
        _VOCAB.clear()   # one pack at a time per worker
        _VOCAB[key] = {k: [t for _d, t in sorted(v)] for k, v in groups.items() if len(v) > 1}
    return _VOCAB[key]


def _expand(con, terms: Sequence[str], mode: str) -> List[str]:
    groups = _groups(con, mode)
    out = list(terms)
    have = set(terms)
    for term in terms:
        if len(term) < 4 or not term.isalpha():
            continue
        k = _STEM.stemWord(term) if mode == "snowball" else plural_base(term)
        for variant in [v for v in groups.get(k, []) if v != term][:3]:
            if variant not in have:
                out.append(variant)
                have.add(variant)
    return out


@contextlib.contextmanager
def _patched(mode: str):
    original = sel._rank_lexical_terms

    def rank(con, terms, limit):
        return original(con, _expand(con, terms, mode), limit) if terms else []

    sel._rank_lexical_terms = rank
    try:
        yield
    finally:
        sel._rank_lexical_terms = original


def make(name: str, mode: str) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with _patched(mode), PackSelector(str(pack), enable_cache=False) as selector:
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


make("e037_snowball", "snowball")
make("e037_plural", "plural")

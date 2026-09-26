"""E025-E027 prototype: the selector's untuned constants, swept once.

None of these was ever tuned on an external benchmark:

* E025 BM25 field weights (text, name, path) of the lexical channel, fixed at
  (1, 1, 1). Names (definitions, headings) and paths may deserve more weight.
* E026 candidate depth per channel (``candidate_limit``, 60).
* E027 the reciprocal-rank-fusion constant (``RRF_K``, 60): smaller values let
  each channel's top ranks dominate, larger values flatten the fusion.

A sweep invites chance wins; any setting that looks better must be confirmed
on held-out before it could replace a default.
"""
from __future__ import annotations

import contextlib
import importlib
import time
from pathlib import Path
from typing import Dict, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

select_module = importlib.import_module("npk.pack.select")


def _ranker(weights):
    text_w, name_w, path_w = weights

    def rank(con, terms, limit):
        if not terms:
            return []
        match = " OR ".join(f'"{term}"' for term in terms)
        rows = con.execute(
            "SELECT lexical.rowid AS block_id FROM lexical JOIN blocks b ON b.id=lexical.rowid "
            "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
            f"ORDER BY bm25(lexical,{text_w},{name_w},{path_w}),"
            "f.path COLLATE BINARY,b.ordinal LIMIT ?",
            (match, limit)).fetchall()
        return [row["block_id"] for row in rows]
    return rank


@contextlib.contextmanager
def _patched(weights=None, rrf_k=None):
    original = (select_module._rank_lexical_terms, select_module.RRF_K)
    if weights is not None:
        select_module._rank_lexical_terms = _ranker(weights)
    if rrf_k is not None:
        select_module.RRF_K = rrf_k
    try:
        yield
    finally:
        select_module._rank_lexical_terms, select_module.RRF_K = original


def make(name: str, *, weights=None, rrf_k=None, candidate_limit=None) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        options = {"enable_cache": False}
        if candidate_limit is not None:
            options["candidate_limit"] = candidate_limit
        out: Dict[int, ArmResult] = {}
        with _patched(weights, rrf_k), PackSelector(str(pack), **options) as selector:
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


make("e025_control", weights=(1.0, 1.0, 1.0))   # must equal npk_default
make("e025_name2", weights=(1.0, 2.0, 1.0))
make("e025_path2", weights=(1.0, 1.0, 2.0))
make("e025_namepath2", weights=(1.0, 2.0, 2.0))
make("e025_namepath_half", weights=(1.0, 0.5, 0.5))
make("e026_limit30", candidate_limit=30)
make("e026_limit120", candidate_limit=120)
make("e026_limit240", candidate_limit=240)
make("e027_rrf20", rrf_k=20)
make("e027_rrf120", rrf_k=120)

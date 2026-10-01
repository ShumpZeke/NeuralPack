"""E012b prototype: dense similarity as one more channel inside the product's fusion.

E012 fused the dense order with the product's whole pool order at equal
weight, which halves the influence of every product channel: tests recall rose
(+5 to +7.5 points) but fix recall fell 9-12 points at 1-2K tokens. Here the
dense order enters the product's own RRF as one channel among lexical,
definition and relation (each capped at the selector's candidate limit), and
the product's greedy fill and top-block trimming are unchanged.

The pool is the product's top-``pool`` blocks for the query; only those are
embedded (content-addressed vector cache shared with E012). The product's
hybrid-mode hooks carry the channel: ``_embedding_channel`` returns the dense
order and ``_symbol_channel`` is disabled, so exactly one channel is added.
"""
from __future__ import annotations

import contextlib
import importlib
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task
from .dense import MODELS, vectors

# ``npk.pack.select`` is also a function re-exported by the package.
select_module = importlib.import_module("npk.pack.select")


@contextlib.contextmanager
def _dense_hooks(dense_ids: List[int]):
    original = (select_module._embedding_channel, select_module._symbol_channel)
    select_module._embedding_channel = lambda con, query, limit, manifest: (list(dense_ids[:limit]), None)
    select_module._symbol_channel = lambda con, query, limit: []
    try:
        yield
    finally:
        select_module._embedding_channel, select_module._symbol_channel = original


def make(name: str, model: str, *, pool: int = 100) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False, candidate_limit=pool) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence[:pool]
        query_vec = vectors(model, [MODELS[model][3] + task.query])[0]
        sims = vectors(model, [e.text for e in ranked]) @ query_vec if ranked else []
        dense_ids = [ranked[i].block_id for i in sorted(range(len(ranked)), key=lambda i: (-sims[i], i))]
        prep_ms = (time.perf_counter() - started) * 1000
        out: Dict[int, ArmResult] = {}
        with _dense_hooks(dense_ids), PackSelector(str(pack), enable_cache=False, retrieval="hybrid") as selector:
            for budget in budgets:
                t0 = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=prep_ms + (time.perf_counter() - t0) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e012b_bge_channel", "bge_small")
make("e012b_minilm_channel", "minilm")

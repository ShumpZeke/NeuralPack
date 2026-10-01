"""E009 prototype: expand from named definitions to the definitions they call.

Earlier graph expansion (Cycles 1-3, `deps`) failed: it expanded from weak
lexical seeds and resolved references by bare name repo-wide. The definition
channel (E002) now yields precise seeds: blocks defining identifiers the
issue names. Bugs often live one call away from the named API (the issue
names ``QuerySet.only()``; the fix is in the SQL helper it calls).

Hypothesis: a third channel listing definitions called from the top named
definitions -- restricted to unambiguous names that also share vocabulary
with the query -- ranks gold blocks that neither lexical nor definition
channels reach.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Sequence, Set

from npk.pack.format import load_blocks, open_pack
from npk.pack.search import analyzed_terms
from npk.pack.select import (FUNCTION_WORDS, MAX_DEFINITION_AMBIGUITY, RRF_K, _definition_channel,
                             _lexical_channel, _lexical_terms, _relation_channel)

from ..arms import Arm, ArmResult, register
from ..data import Task
from .entity_query import fill

CALLED = re.compile(r"(?<![\w])([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")


def callee_channel(con, query: str, seeds: Sequence[int], limit: int, *, seed_count: int,
                   require_overlap: bool) -> List[int]:
    if not seeds:
        return []
    qterms = set(_lexical_terms(con, query))
    names: Dict[str, int] = {}
    for rank, block in enumerate(load_blocks(con, list(seeds[:seed_count]))):
        for name in CALLED.findall(block.text):
            if name.lower() in FUNCTION_WORDS or name in ("self", "super", "print", "len", "isinstance"):
                continue
            names.setdefault(name, rank)
    if not names:
        return []
    marks = ",".join("?" * len(names))
    rows = con.execute(
        f"SELECT s.name, s.block_id FROM symbols s WHERE s.is_def=1 AND s.name IN ({marks})",
        tuple(names)).fetchall()
    by_name: Dict[str, Set[int]] = {}
    for name, block_id in rows:
        by_name.setdefault(name, set()).add(block_id)
    candidates: Dict[int, float] = {}
    seed_set = set(seeds)
    for name, blocks in by_name.items():
        if len(blocks) > MAX_DEFINITION_AMBIGUITY:
            continue
        if require_overlap and not (set(analyzed_terms(name)) & qterms):
            continue
        for block_id in blocks - seed_set:
            candidates[block_id] = max(candidates.get(block_id, 0.0),
                                       1.0 / (1 + names[name]) / len(blocks))
    return sorted(candidates, key=lambda b: (-candidates[b], b))[:limit]


def select_ranked(con, query: str, *, limit: int = 60, seed_count: int = 3,
                  require_overlap: bool = True, callee_k: int = RRF_K) -> List[int]:
    lex = _lexical_channel(con, query, limit)
    ranks = {}
    if lex:
        ranks["lexical"] = lex
    rel = _relation_channel(con, query, limit)
    if rel:
        ranks["relation"] = rel
    defs = _definition_channel(con, query, limit, lex)
    if defs:
        ranks["definition"] = defs
        calls = callee_channel(con, query, defs, limit, seed_count=seed_count,
                               require_overlap=require_overlap)
        if calls:
            ranks["callee"] = calls
    fused: Dict[int, float] = {}
    for channel, ordered in ranks.items():
        k = callee_k if channel == "callee" else RRF_K
        for rank, block_id in enumerate(ordered):
            fused[block_id] = fused.get(block_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused, key=lambda b: -fused[b])


def make(name: str, **options) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out = {}
        with open_pack(pack) as con:
            started = time.perf_counter()
            ordered = select_ranked(con, task.query, **options)
            elapsed = (time.perf_counter() - started) * 1000
            for budget in budgets:
                spans, tokens, n = fill(con, ordered, budget)
                out[budget] = ArmResult(spans, tokens, elapsed, "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make("e009_callee_s3", seed_count=3)
make("e009_callee_s3_any", seed_count=3, require_overlap=False)
make("e009_callee_s1", seed_count=1)
make("e009_callee_s5_k120", seed_count=5, callee_k=120)

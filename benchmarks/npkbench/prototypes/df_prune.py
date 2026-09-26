"""E010 prototype: drop very common terms from long queries (latency, maybe quality).

A long issue query OR-s 30-100 terms; common ones (``field``, ``model``,
``error`` in Django) make most blocks match (58% on one Django snapshot), and
FTS5 must score every match. Their BM25 IDF is near zero, so dropping terms
whose document frequency exceeds a fraction of all blocks should barely change
the ranking while shrinking the match set.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack.format import open_pack
from npk.pack.select import RRF_K, _definition_channel, _lexical_terms, _relation_channel

from ..arms import Arm, ArmResult, register
from ..data import Task
from .entity_query import fill


def pruned_terms(pack: Path, query: str, max_df: float, min_terms: int = 4) -> List[str]:
    con = sqlite3.connect(Path(pack).absolute().as_uri() + "?mode=ro", uri=True)
    try:
        terms = _lexical_terms(con, query)
        total = con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        con.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, lexical, 'row')")
        marks = ",".join("?" * len(terms)) or "''"
        df = dict(con.execute(f"SELECT term, doc FROM temp.v WHERE term IN ({marks})", terms))
    finally:
        con.close()
    kept = [t for t in terms if df.get(t, 0) <= max_df * total]
    if len(kept) < min_terms:  # keep the rarest terms for short or generic queries
        kept = sorted(terms, key=lambda t: df.get(t, 0))[:min_terms]
    return kept


def make(name: str, max_df: float) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out = {}
        terms = pruned_terms(pack, task.query, max_df)
        with open_pack(pack) as con:
            started = time.perf_counter()
            match = " OR ".join(f'"{t}"' for t in terms)
            lex = [r[0] for r in con.execute(
                "SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid "
                "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
                "ORDER BY bm25(lexical,1.0,1.0,1.0), f.path COLLATE BINARY, b.ordinal LIMIT 60",
                (match,))] if terms else []
            lexical_ms = (time.perf_counter() - started) * 1000
            ranks = {}
            if lex:
                ranks["lexical"] = lex
            rel = _relation_channel(con, task.query, 60)
            if rel:
                ranks["relation"] = rel
            defs = _definition_channel(con, task.query, 60, lex)
            if defs:
                ranks["definition"] = defs
            fused: Dict[int, float] = {}
            for ordered in ranks.values():
                for rank, block_id in enumerate(ordered):
                    fused[block_id] = fused.get(block_id, 0.0) + 1.0 / (RRF_K + rank)
            ordered_ids = sorted(fused, key=lambda b: -fused[b])
            for budget in budgets:
                spans, tokens, n = fill(con, ordered_ids, budget)
                out[budget] = ArmResult(spans, tokens, lexical_ms, "selected" if n else "fallback_required", n,
                                        extra={"terms": len(terms)})
        return out

    return register(Arm(name, runner=runner))


make("e010_df_all", 1.01)   # control: no pruning, same code path
make("e010_df20", 0.20)
make("e010_df10", 0.10)
make("e010_df05", 0.05)

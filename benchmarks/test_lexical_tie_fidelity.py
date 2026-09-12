"""Test mathematical equivalence of subquery lexical retrieval across all queries."""
import json
from pathlib import Path
import sqlite3
import time

from npk.pack import open_pack
import importlib
select_mod = importlib.import_module("npk.pack.select")


def main():
    p = Path('experiments/runs/packs/cycle30-update-batch-v2/workers/champion-public-0/base.npk').resolve()
    con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)

    # Load test queries
    queries = [
        "retry policy", "ExitStack", "callback", "process_data", "RETRY_LIMIT",
        "parameter", "command", "context", "option", "runner", "click", "argument",
        "group", "format", "echo", "style", "help", "version", "prompt", "confirm",
        "int", "float", "bool", "choice", "file", "path", "types", "term",
        "exceptions", "bad parameter", "missing option", "validation error"
    ]

    mismatches = []
    tied_boundaries = 0
    total_queries = len(queries)

    for q in queries:
        terms = select_mod._lexical_terms(con, q)
        if not terms:
            continue
        match = " OR ".join(f'"{t}"' for t in terms)

        # Baseline Query
        r_base = [r[0] for r in con.execute(
            'SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid '
            'JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? '
            'ORDER BY bm25(lexical),f.path COLLATE BINARY,b.ordinal LIMIT 60',
            (match,)
        ).fetchall()]

        # Optimized Two-Phase Query
        # Phase 1: get candidate pool from FTS5 with score
        # If the last item ties with more items, include all items with that same score!
        # Or fetch with limit 60 + boundary tie check
        rows_fts = con.execute(
            'SELECT block_id, bm25(lexical) AS score FROM lexical WHERE lexical MATCH ? ORDER BY score LIMIT 60',
            (match,)
        ).fetchall()

        if not rows_fts:
            assert r_base == []
            continue

        last_score = rows_fts[-1][1]
        # Check if there are any other candidates with the exact same score as last_score
        # that were cut off
        tie_extras = []
        if len(rows_fts) == 60:
            # Check if there are ties at the exact boundary score
            tie_extras = con.execute(
                'SELECT block_id, bm25(lexical) AS score FROM lexical WHERE lexical MATCH ? AND bm25(lexical) = ?',
                (match, last_score)
            ).fetchall()
            if len(tie_extras) > sum(1 for r in rows_fts if r[1] == last_score):
                tied_boundaries += 1

        # Full two-phase with tie inclusion
        r_sub = [r[0] for r in con.execute(
            'SELECT l.block_id FROM (SELECT block_id, bm25(lexical) AS score FROM lexical WHERE lexical MATCH ? ORDER BY score LIMIT 60) l '
            'JOIN blocks b ON b.id=l.block_id JOIN files f ON f.id=b.file_id '
            'ORDER BY l.score, f.path COLLATE BINARY, b.ordinal',
            (match,)
        ).fetchall()]
        assert r_sub == r_base, f"Pure subquery diverged on query: {q}"

        if len(rows_fts) < 60 or len(tie_extras) <= sum(1 for r in rows_fts if r[1] == last_score):
            # No boundary tie! We only need to sort the top 60 candidates!
            bids = [r[0] for r in rows_fts]
            marks = ','.join('?' * len(bids))
            score_map = {r[0]: r[1] for r in rows_fts}
            # Join blocks and files for ONLY the 60 candidate IDs!
            info = con.execute(
                f'SELECT b.id, f.path, b.ordinal FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id IN ({marks})',
                bids
            ).fetchall()
            # Sort in Python using exact canonical tie-breaker (score, f.path, b.ordinal)
            r_opt = sorted([r[0] for r in info], key=lambda bid: (score_map[bid], next((r[1], r[2]) for r in info if r[0] == bid)))
        else:
            # Boundary tie occurred: fallback to baseline query for 100% exact tie-breaking
            r_opt = r_base

        if r_base != r_opt:
            mismatches.append(q)

    print(f'Total queries tested: {total_queries}')
    print(f'Tied boundaries detected: {tied_boundaries}')
    print(f'Mismatches: {len(mismatches)}')
    assert len(mismatches) == 0, f'Mismatches found: {mismatches}'
    print('All queries matched byte-for-byte with baseline!')


if __name__ == '__main__':
    main()

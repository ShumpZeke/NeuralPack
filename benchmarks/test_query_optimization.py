"""Compare lexical channel query plans and tie-breaking performance."""
from pathlib import Path
import sqlite3
import time


def main():
    p = Path('experiments/runs/packs/cycle30-update-batch-v2/workers/champion-public-0/base.npk').resolve()
    con = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)
    match = '"context" OR "retry" OR "option" OR "command"'

    # Query A: current query with joins before limit
    t0 = time.perf_counter()
    for _ in range(50):
        r_a = con.execute(
            'SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid '
            'JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? '
            'ORDER BY bm25(lexical),f.path COLLATE BINARY,b.ordinal LIMIT 60',
            (match,)
        ).fetchall()
    t_a = (time.perf_counter() - t0) * 1000 / 50

    # Query B: subquery join only on top candidates
    t1 = time.perf_counter()
    for _ in range(50):
        r_b = con.execute(
            'SELECT l.block_id FROM (SELECT block_id, bm25(lexical) AS score FROM lexical WHERE lexical MATCH ? ORDER BY score LIMIT 60) l '
            'JOIN blocks b ON b.id=l.block_id JOIN files f ON f.id=b.file_id '
            'ORDER BY l.score, f.path COLLATE BINARY, b.ordinal',
            (match,)
        ).fetchall()
    t_b = (time.perf_counter() - t1) * 1000 / 50

    print(f'Query A (full join before limit) ms: {t_a:.3f}')
    print(f'Query B (subquery join after limit) ms: {t_b:.3f}')
    print(f'Speedup: {t_a/t_b:.2f}x')
    print('Total matches returned:', len(r_a))
    print('Results identical:', r_a == r_b)
    if r_a != r_b:
        print('Diff index:', [i for i, (a, b) in enumerate(zip(r_a, r_b)) if a != b])


if __name__ == '__main__':
    main()

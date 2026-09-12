"""Stage-level latency breakdown of PackSelector._select_once."""
from pathlib import Path
import sqlite3
import time

from npk.pack import PackSelector
from npk.pack.format import read_manifest, open_pack, load_blocks
import importlib
select_mod = importlib.import_module("npk.pack.select")


def main():
    p = Path('experiments/runs/packs/cycle30-update-batch-v2/workers/champion-public-0/base.npk').resolve()
    queries = ['retry policy', 'ExitStack', 'callback', 'process_data', 'RETRY_LIMIT',
               'parameter', 'command', 'context', 'option', 'runner']

    stage_times = {}
    def time_stage(name, fn):
        t0 = time.perf_counter()
        res = fn()
        stage_times[name] = stage_times.get(name, 0) + (time.perf_counter() - t0) * 1000
        return res

    with open_pack(p) as con:
        m = read_manifest(con)
        sel = PackSelector(p)
        for _ in range(20):
            for q in queries:
                terms = time_stage('1_lexical_terms', lambda: select_mod._lexical_terms(con, q))
                match = ' OR '.join(f'"{t}"' for t in terms)
                bids = time_stage('2_lexical_channel_query', lambda: [r['block_id'] for r in con.execute(
                    'SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid '
                    'JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? '
                    'ORDER BY bm25(lexical),f.path COLLATE BINARY,b.ordinal LIMIT 60', (match,)).fetchall()])
                blks = time_stage('3_load_blocks', lambda: load_blocks(con, bids))
                sel_obj = time_stage('4_select_once_total', lambda: sel._select_once(con, m, q, 512, 60))

    total = stage_times['4_select_once_total']
    for name, ms in sorted(stage_times.items()):
        print(f'{name:25s}: {ms:.2f} ms ({ms/total*100:.1f}%)')


if __name__ == '__main__':
    main()

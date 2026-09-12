"""Compare body-only vs prepended metadata vs multi-column FTS5 retrieval."""
from pathlib import Path
import re
import sqlite3
import time

from npk.pack.format import open_pack, load_blocks
import importlib
select_mod = importlib.import_module("npk.pack.select")


def expand_terms(text):
    if not text:
        return ""
    expanded = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    return re.sub(r'[^\w]+|_', ' ', expanded)


def main():
    p = Path('experiments/runs/packs/cycle30-update-batch-v2/workers/champion-public-0/base.npk').resolve()
    with open_pack(p) as con:
        blocks = load_blocks(con)

    # Build in-memory tables for each arm
    db = sqlite3.connect(':memory:')
    # Arm 0: Current body-only
    db.execute("CREATE VIRTUAL TABLE fts_body USING fts5(block_id UNINDEXED, content, tokenize='unicode61 remove_diacritics 2')")
    # Arm 1: Prepended metadata in content
    db.execute("CREATE VIRTUAL TABLE fts_prepended USING fts5(block_id UNINDEXED, content, tokenize='unicode61 remove_diacritics 2')")
    # Arm 2: Multi-column fielded table
    db.execute("CREATE VIRTUAL TABLE fts_columns USING fts5(block_id UNINDEXED, name, path, body, tokenize='unicode61 remove_diacritics 2')")

    db.executemany(
        "INSERT INTO fts_body(block_id, content) VALUES(?,?)",
        [(b.id, b.text) for b in blocks]
    )
    db.executemany(
        "INSERT INTO fts_prepended(block_id, content) VALUES(?,?)",
        [(b.id, f"{expand_terms(b.path)} {expand_terms(b.name)}\n{b.text}") for b in blocks]
    )
    db.executemany(
        "INSERT INTO fts_columns(block_id, name, path, body) VALUES(?,?,?,?)",
        [(b.id, expand_terms(b.name), expand_terms(b.path), b.text) for b in blocks]
    )
    db.commit()

    queries = [
        "retry policy", "ExitStack", "callback in decorators", "process_data in worker",
        "RETRY_LIMIT in settings", "Parameter class in core", "command option in decorators",
        "context in test_context", "shell completion in shell_completion.py", "testing runner in test_testing"
    ]

    print(f'Testing {len(queries)} realistic code queries across 2,213 blocks...')
    for q in queries:
        terms = select_mod._content_terms(q)
        if not terms:
            continue
        match = ' OR '.join(f'"{t}"' for t in terms)

        r_body = [r[0] for r in db.execute('SELECT block_id FROM fts_body WHERE fts_body MATCH ? ORDER BY bm25(fts_body) LIMIT 10', (match,)).fetchall()]
        r_prep = [r[0] for r in db.execute('SELECT block_id FROM fts_prepended WHERE fts_prepended MATCH ? ORDER BY bm25(fts_prepended) LIMIT 10', (match,)).fetchall()]
        r_cols = [r[0] for r in db.execute('SELECT block_id FROM fts_columns WHERE fts_columns MATCH ? ORDER BY bm25(fts_columns, 0, 1.0, 1.0, 1.0) LIMIT 10', (match,)).fetchall()]

        print(f'\nQuery: {q!r}')
        print(f'  Body-only top 3:     {r_body[:3]}')
        print(f'  Prepended top 3:     {r_prep[:3]}')
        print(f'  Multi-column top 3:  {r_cols[:3]}')

        # Check target block for path-specific query 'shell completion in shell_completion.py'
        if 'shell_completion' in q:
            blks_body = [b.path for b in blocks if b.id in r_body[:3]]
            blks_prep = [b.path for b in blocks if b.id in r_prep[:3]]
            print(f'  -> Body paths:      {blks_body}')
            print(f'  -> Prepended paths: {blks_prep}')

        if 'settings' in q:
            blks_body = [b.path for b in blocks if b.id in r_body[:3]]
            blks_prep = [b.path for b in blocks if b.id in r_prep[:3]]
            print(f'  -> Body paths:      {blks_body}')
            print(f'  -> Prepended paths: {blks_prep}')


if __name__ == '__main__':
    main()

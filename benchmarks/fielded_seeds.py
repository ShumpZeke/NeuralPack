"""Ordinary weighted FTS5 metadata baseline; experiment, not a new IR theorem."""
import re
import sqlite3
from npk.context.info_gain import content_terms


def terms(text):
    expanded=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',text or '')
    return re.sub(r'[^\w]+|_', ' ',expanded)


def build(path,blocks):
    con=sqlite3.connect(path)
    con.execute("CREATE VIRTUAL TABLE fielded USING fts5(block_id UNINDEXED,name,path,body,tokenize='unicode61 remove_diacritics 2')")
    con.executemany('INSERT INTO fielded(block_id,name,path,body) VALUES(?,?,?,?)',
                    [(b.id,terms(b.name),terms(b.path),b.text) for b in blocks])
    con.commit();return con


def rank(con,query,*,name_weight=1.0,path_weight=1.0,limit=60):
    tokens=content_terms(query)
    if not tokens:return []
    match=' OR '.join('"'+t+'"' for t in tokens)
    # rowid inherits canonical source order because build receives that order.
    rows=con.execute('SELECT block_id,bm25(fielded,0,?,?,1) score FROM fielded WHERE fielded MATCH ? ORDER BY score,rowid LIMIT ?',
                     (name_weight,path_weight,match,limit)).fetchall()
    return [r[0] for r in rows]

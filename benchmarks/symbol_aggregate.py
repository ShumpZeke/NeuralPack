"""Challenger: aggregate symbol matches before joining source metadata."""
from npk.pack.select import _identifier_candidates


def rank(con,query,limit):
    names=_identifier_candidates(query)
    if not names:return []
    marks=','.join('?' for _ in names)
    rows=con.execute(
        f'WITH matches AS (SELECT block_id,SUM(is_def) AS d,COUNT(*) AS c FROM symbols '
        f'WHERE name IN ({marks}) GROUP BY block_id) '
        'SELECT m.block_id FROM matches m JOIN blocks b ON b.id=m.block_id '
        'JOIN files f ON f.id=b.file_id '
        'ORDER BY m.d DESC,m.c DESC,f.path COLLATE BINARY,b.ordinal LIMIT ?',(*names,limit)).fetchall()
    return [row['block_id'] for row in rows]

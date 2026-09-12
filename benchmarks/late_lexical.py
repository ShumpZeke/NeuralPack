"""Candidate: FTS rank streaming followed by canonical metadata ordering.

Consume the entire boundary-score tie group. A top-k rowid truncation would
change equal-score selections after incremental updates. No default is changed.
"""
import sqlite3
from npk.context.info_gain import content_terms


def rank(con,query,limit):
    terms=content_terms(query)
    if not terms:return []
    if type(limit) is not int or limit<=0:raise ValueError('positive candidate limit required')
    match=' OR '.join('"'+term+'"' for term in terms)
    rows=[];cutoff=None;done=False
    try:
        cursor=con.execute(
            "SELECT rowid AS block_id,bm25(lexical,1.0,1.0,1.0) AS score FROM lexical "
            "WHERE lexical MATCH ? ORDER BY score", (match,)
        )
        try:
            while not done:
                batch=cursor.fetchmany(64)
                if not batch:break
                ids=[r[0] for r in batch]
                metadata={r[0]:(r[1],r[2]) for r in con.execute(
                    'SELECT b.id,f.path,b.ordinal FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id IN ('+
                    ','.join('?' for _ in ids)+')',ids)}
                for block_id,score in batch:
                    if cutoff is not None and score>cutoff:
                        done=True;break
                    if block_id not in metadata:continue
                    path,ordinal=metadata[block_id];rows.append((score,path,ordinal,block_id))
                    if len(rows)==limit:cutoff=score
        finally:cursor.close()
    except sqlite3.OperationalError:return []
    rows.sort(key=lambda r:(r[0],r[1],r[2]))
    return [r[3] for r in rows[:limit]]

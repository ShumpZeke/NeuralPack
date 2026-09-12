"""Deterministic document/passage challengers; no product-default changes.

Document-first retrieval is established IR practice. These fixed policies test
whether it helps this workload; their scores are not calibrated probabilities.
"""
import sqlite3
from benchmarks.fielded_seeds import terms
from benchmarks.seed_candidates import fuse
from npk.context.info_gain import content_terms


METHODS = ('flat_fields', 'document_gate1', 'document_gate4', 'document_gate16',
           'document_soft', 'document_balanced4', 'document_escape4', 'passage_parent4')


def build(path, blocks, source):
    con=sqlite3.connect(path)
    try:
        con.executescript('''
        BEGIN;
        CREATE VIRTUAL TABLE documents USING fts5(path UNINDEXED,title,symbols,body,tokenize='unicode61 remove_diacritics 2');
        CREATE VIRTUAL TABLE passages USING fts5(block_id UNINDEXED,name,path,body,tokenize='unicode61 remove_diacritics 2');
        CREATE TABLE locations(block_id INTEGER PRIMARY KEY,path TEXT NOT NULL,ordinal INTEGER NOT NULL);
        CREATE INDEX locations_path ON locations(path);
        ''')
        groups={}
        for b in blocks:groups.setdefault(b.path,[]).append(b)
        for name, group in sorted(groups.items()):
            body=(source/name).read_text(encoding='utf-8')
            symbols=' '.join(terms(b.name) for b in group if b.name)
            con.execute('INSERT INTO documents(path,title,symbols,body) VALUES(?,?,?,?)',(name,terms(name),symbols,body))
        con.executemany('INSERT INTO passages(block_id,name,path,body) VALUES(?,?,?,?)',
                        [(b.id,terms(b.name),terms(b.path),b.text) for b in blocks])
        con.executemany('INSERT INTO locations VALUES(?,?,?)',[(b.id,b.path,b.ordinal) for b in blocks])
        con.commit();return con
    except BaseException:
        con.close();raise


def match(query):
    values=content_terms(query)
    return ' OR '.join('"'+t+'"' for t in values)


def documents(con, query, limit=240):
    expr=match(query)
    if not expr:return []
    return [(r[0],r[1]) for r in con.execute(
        'SELECT path,bm25(documents,0,4,1,1) score FROM documents WHERE documents MATCH ? ORDER BY score,path COLLATE BINARY LIMIT ?',
        (expr,limit))]


def passages(con, query, limit=240, paths=None):
    expr=match(query)
    if not expr or paths==[]:return []
    sql=('SELECT p.block_id,l.path,bm25(passages,0,4,1,1) score FROM passages p '
         'JOIN locations l ON l.block_id=p.block_id WHERE passages MATCH ? ')
    params=[expr]
    if paths is not None:
        sql+='AND l.path IN ('+','.join('?' for _ in paths)+') ';params.extend(paths)
    sql+='ORDER BY score,l.path COLLATE BINARY,l.ordinal LIMIT ?';params.append(limit)
    return [tuple(r) for r in con.execute(sql,params)]


def rank(con, query, method, limit=240):
    if method not in METHODS:raise ValueError('unknown hierarchy challenger')
    if type(limit) is not int or limit<=0:raise ValueError('positive candidate limit required')
    if method=='flat_fields':
        flat=passages(con,query,limit)
        return [r[0] for r in flat],{'routed_paths':[],'policy':method}
    if method=='passage_parent4':
        flat=passages(con,query,limit)
        paths=list(dict.fromkeys(r[1] for r in flat))[:4]
    else:
        docs=documents(con,query,limit)
        paths=[r[0] for r in docs]
    if method.startswith('document_gate') or method=='passage_parent4':
        n=4 if method=='passage_parent4' else int(method.removeprefix('document_gate'))
        paths=paths[:n];ranked=passages(con,query,limit,paths)
        return [r[0] for r in ranked],{'routed_paths':paths,'policy':method}
    flat=passages(con,query,limit)
    if method=='document_soft':
        doc_rank={name:i for i,name in enumerate(paths)}
        scores={r[0]:1/(60+i)+(1/(60+doc_rank[r[1]]) if r[1] in doc_rank else 0)
                for i,r in enumerate(flat)}
        # Stable passage order breaks ties; no artifact insertion-order fallback.
        ordered=sorted([r[0] for r in flat],key=lambda key:-scores[key])
        return ordered,{'routed_paths':paths,'policy':method}
    paths=paths[:4]
    groups=[passages(con,query,limit, [path]) for path in paths]
    balanced=[]
    for i in range(max(map(len,groups),default=0)):
        for group in groups:
            if i<len(group):balanced.append(group[i][0])
    balanced=balanced[:limit]
    if method=='document_escape4':balanced=fuse([[r[0] for r in flat],balanced],limit)
    return balanced,{'routed_paths':paths,'policy':method}

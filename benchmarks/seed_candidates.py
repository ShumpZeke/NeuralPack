"""Non-generative seed challengers; none is promoted by existing runtime flags."""
import re
from npk.context.info_gain import content_terms,STOPWORDS


def expanded_terms(query):
    raw=re.findall(r'\w+',query)
    values=[token.lower() for token in raw]
    for token in raw:
        for part in token.split('_'):
            values.extend(piece.lower() for piece in re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+',part))
    return list(dict.fromkeys(t for t in values if len(t)>2 and t not in STOPWORDS))


def lexical(con,terms,limit,source_prefix=None):
    if not terms:return []
    match=' OR '.join('"'+t+'"' for t in terms)
    sql=('SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid '
         'JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? ')
    params=[match]
    if source_prefix is not None:
        sql+='AND substr(f.path,1,?)=? ';params.extend((len(source_prefix),source_prefix))
    sql+='ORDER BY bm25(lexical),f.path COLLATE BINARY,b.ordinal LIMIT ?';params.append(limit)
    return [r['block_id'] for r in con.execute(sql,params)]


def exact_shaped_definitions(con,query,limit):
    tokens=[t for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',query)
            if '_' in t or re.search(r'[a-z][A-Z]',t)]
    if not tokens:return []
    sql=('SELECT s.block_id FROM symbols s JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id '
         f'WHERE s.name IN ({",".join("?" for _ in tokens)}) AND s.is_def=1 '
         'GROUP BY s.block_id ORDER BY COUNT(*) DESC,f.path COLLATE BINARY,b.ordinal LIMIT ?')
    return [r[0] for r in con.execute(sql,(*tokens,limit))]


def fuse(lists,limit):
    scores={}
    for ordered in lists:
        for rank,key in enumerate(ordered):scores[key]=scores.get(key,0)+1/(60+rank)
    return sorted(scores,key=lambda key:-scores[key])[:limit]


def rank(con,query,limit,method):
    original=lexical(con,content_terms(query),limit)
    if method=='bm25':return original
    if method=='bm25_source_scope':return lexical(con,content_terms(query),limit,'src/click/')
    if method=='empty_seed_expansion' and original:return original
    expanded=lexical(con,expanded_terms(query),limit)
    if method in {'camel_expansion','empty_seed_expansion'}:return expanded
    if method=='lexical_fusion':return fuse([original,expanded],limit)
    if method=='symbol_priority':return list(dict.fromkeys(exact_shaped_definitions(con,query,limit)+expanded))[:limit]
    raise ValueError('unknown challenger')

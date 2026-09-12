"""Research controls for the pre-lowercasing camel-case information loss."""
import re
from npk.context.info_gain import _query_terms,STOPWORDS


def components(text):
    # ASCII programming-identifier boundaries. Whole Unicode tokens are retained
    # by the baseline; this is not a universal linguistic word segmenter.
    return [p.lower() for p in re.findall(r'[A-Z]+(?=[A-Z][a-z]|[0-9]|_|$)|[A-Z]?[a-z]+|[0-9]+',text)]


def additions(query):
    result={}
    for token in re.findall(r'\w+',query):
        parts=components(token)
        if len(parts)>1:
            extra=[p for p in parts if len(p)>2 and p not in STOPWORDS and p not in _query_terms(token)]
            if extra:result[token]=list(dict.fromkeys(extra))
    return result


def terms(query,con=None):
    result=[t for t in _query_terms(query) if t not in STOPWORDS and len(t)>2]
    for token,extra in additions(query).items():
        if con is not None:
            # Word tokens contain no FTS operators; still bind and quote them.
            present=con.execute('SELECT 1 FROM lexical WHERE lexical MATCH ? LIMIT 1',('"'+token.lower()+'"',)).fetchone()
            if present:continue
        result.extend(extra)
    return list(dict.fromkeys(result))

"""Research-only retrieval features on identical NPK source blocks.

The auxiliary SQLite file is not a new product format. It must be rebuilt after
its parent changes; incremental support is deferred until features earn it.
CRISP's frozen scorer is loaded only by the experiment harness, never runtime.
"""
from collections import Counter
import ast
import re
import sqlite3
from pathlib import Path

from npk.context.info_gain import STOPWORDS, _query_terms
from npk.pack.format import PackError, load_blocks, open_pack, read_manifest
from npk.pack.select import _lexical_terms


VERSION='seed-metadata-1'
# A challenger, not an asserted universally correct English stopword policy.
CODE_WORDS={'value','values','return','returns','get','set','use','used','using','exactly','exact','configured'}
FUNCTION_WORDS=STOPWORDS-CODE_WORDS
WORDS=re.compile(r'\w+',re.UNICODE)
CAMEL=re.compile(r'[A-Z]+(?=[A-Z][a-z]|[0-9]|_|$)|[A-Z]?[a-z]+|[0-9]+')
QUOTED=re.compile(r'(?<!`)`(\w+(?:\.\w+)*)`(?!`)')
SCHEMA='''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE files(id INTEGER PRIMARY KEY,path TEXT NOT NULL);
CREATE TABLE blocks(id INTEGER PRIMARY KEY,file_id INTEGER NOT NULL,ordinal INTEGER NOT NULL,tok_full INTEGER NOT NULL);
CREATE TABLE postings(term TEXT NOT NULL,block_id INTEGER NOT NULL,tf INTEGER NOT NULL);
CREATE INDEX postings_term ON postings(term);
CREATE TABLE terms(term TEXT PRIMARY KEY,df INTEGER NOT NULL);
CREATE TABLE symbols(name TEXT NOT NULL,block_id INTEGER NOT NULL,is_def INTEGER NOT NULL);
CREATE INDEX symbols_name ON symbols(name);
CREATE TABLE relations(block_id INTEGER NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL);
CREATE INDEX relations_lookup ON relations(kind,name);
CREATE VIRTUAL TABLE expanded USING fts5(body,tokenize="unicode61 remove_diacritics 2 tokenchars '_'");
CREATE VIRTUAL TABLE fields USING fts5(body,name,path,tokenize="unicode61 remove_diacritics 2 tokenchars '_'");'''


def analyzed(text):
    """Keep Unicode whole words and add ASCII identifier components."""
    out=[]
    for word in WORDS.findall(text):
        parts=[]
        for piece in word.split('_'):
            camel=CAMEL.findall(piece)
            parts.extend(p.lower() for p in camel) if len(camel)>1 else parts.append(piece.lower())
        # Do not double an ordinary word's frequency just for passing analysis.
        out.append(word.lower())
        if len(parts)>1:out.extend(p for p in parts if p and p!=word.lower())
    return out


def quoted_terms(query):
    return list(dict.fromkeys(part.lower() for literal in QUOTED.findall(query)
                              for part in [literal,*literal.split('.')]))


def query_terms(query):
    quoted=set(quoted_terms(query))
    return list(dict.fromkeys(t for t in analyzed(query) if
                             (t not in FUNCTION_WORDS and len(t)>1) or t in quoted))


def literal_terms(parent,query):
    return list(dict.fromkeys([*_lexical_terms(parent,query),*quoted_terms(query)]))


def original_index_rank(parent,query,limit,*,policy):
    if policy=='literal':terms=literal_terms(parent,query)
    elif policy=='retained':
        terms=list(dict.fromkeys([*literal_terms(parent,query),
                                  *(t for t in _query_terms(query) if t in CODE_WORDS)]))
    else:raise ValueError('Unknown query policy')
    if not terms:return []
    match=' OR '.join('"'+t+'"' for t in terms)
    return [r[0] for r in parent.execute('SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid '
            'JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? '
            'ORDER BY bm25(lexical,1.0,1.0,1.0),f.path COLLATE BINARY,b.ordinal LIMIT ?',
            (match,limit))]


def raise_sites(source):
    """Literal raise sites; no claim that a named exception actually executes."""
    try:tree=ast.parse(source)
    except SyntaxError:return []
    out=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Raise) or node.exc is None:continue
        value=node.exc.func if isinstance(node.exc,ast.Call) else node.exc
        name=value.id if isinstance(value,ast.Name) else value.attr if isinstance(value,ast.Attribute) else None
        if name:out.append((node.lineno,node.end_lineno,name.lower()))
    return out


def build(parent_path,output,source,*,rival_analyze,count_cl100k):
    output=Path(output)
    if output.exists():raise ValueError('Fresh auxiliary index required')
    source=Path(source)
    con=sqlite3.connect(output)
    try:
        con.executescript(SCHEMA)
        dfs=Counter();count=0;relation_count=0
        with open_pack(parent_path) as parent:
            root=read_manifest(parent)['root_sha256']
            blocks=load_blocks(parent,[r[0] for r in parent.execute('SELECT id FROM blocks')])
            sites={}
            for row in parent.execute('SELECT id,path,language FROM files ORDER BY path'):
                con.execute('INSERT INTO files VALUES(?,?)',(row['id'],row['path']))
                body=(source/row['path']).read_bytes().decode().replace('\r\n','\n').replace('\r','\n')
                sites[row['path']]=raise_sites(body) if row['language']=='python' else []
            for block in blocks:
                count+=1
                body=' '.join(analyzed(block.text));name=' '.join(analyzed(block.name or ''))
                path=' '.join(analyzed(block.path.rsplit('.',1)[0]))
                con.execute('INSERT INTO blocks VALUES(?,?,?,?)',(block.id,block.file_id,block.ordinal,count_cl100k(block.text)))
                con.execute('INSERT INTO expanded(rowid,body) VALUES(?,?)',(block.id,body))
                con.execute('INSERT INTO fields(rowid,body,name,path) VALUES(?,?,?,?)',(block.id,body,name,path))
                # Exact frozen CRISP analysis/path-presence convention. Keep its
                # BPE length normalization as a separately labeled baseline.
                tf=Counter(rival_analyze(block.text))
                for term in rival_analyze(block.path.replace('/',' ').rsplit('.',1)[0]):tf.setdefault(term,1)
                dfs.update(tf.keys())
                con.executemany('INSERT INTO postings VALUES(?,?,?)',[(t,block.id,n) for t,n in tf.items()])
                if block.name:
                    names={block.name.lower(),block.name.rsplit('.',1)[-1].lower()}
                    con.executemany('INSERT INTO symbols VALUES(?,?,1)',[(n,block.id) for n in sorted(names)])
                raised={name for lo,hi,name in sites[block.path] if block.start_line<=lo and hi<=block.end_line}
                con.executemany('INSERT INTO relations VALUES(?,?,?)',[(block.id,'raises',n) for n in sorted(raised)])
                relation_count+=len(raised)
            con.executemany('INSERT INTO terms VALUES(?,?)',list(dfs.items()))
            con.executemany('INSERT INTO metadata VALUES(?,?)',[('version',VERSION),('parent_root',root)])
        con.commit()
        return {'blocks':count,'relations':relation_count,'terms':len(dfs),'bytes':output.stat().st_size,
                'parent_root':root,'incremental':False}
    finally:con.close()


def require_parent(side,parent):
    meta=dict(side.execute('SELECT key,value FROM metadata'))
    if meta.get('version')!=VERSION or meta.get('parent_root')!=read_manifest(parent)['root_sha256']:
        raise PackError('Auxiliary seed index is stale or belongs to another artifact')


def field_rank(side,query,limit,*,mode):
    terms=query_terms(query)
    if not terms:return []
    match=' OR '.join('"'+t+'"' for t in terms)
    if mode=='subwords':table='expanded';weights=''
    elif mode=='fields':table='fields';weights=',1,1,1'
    elif mode=='names4':table='fields';weights=',1,4,1'
    else:raise ValueError('Unknown field policy')
    return [r[0] for r in side.execute(f'SELECT x.rowid FROM {table} x JOIN blocks b ON b.id=x.rowid '
            f'JOIN files f ON f.id=b.file_id WHERE {table} MATCH ? '
            f'ORDER BY bm25({table}{weights}),f.path COLLATE BINARY,b.ordinal LIMIT ?',(match,limit))]

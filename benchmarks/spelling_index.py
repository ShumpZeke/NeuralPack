"""Research side index: normalized FTS versus explicit spelling collisions.

No product schema change. This ordinary text-indexing experiment does not infer
that names with the same normalized spelling denote the same program object.
"""
from collections import defaultdict
from contextlib import contextmanager
import re
import sqlite3
from pathlib import Path
from benchmarks.identifier_spelling import components
from npk.context.info_gain import content_terms,STOPWORDS
from npk.pack.format import open_pack,load_blocks,read_manifest,require_supported
from npk.pack.integrity import require_clean_cache


VERSION='1'
WORDS=re.compile(r'(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]{1,79}(?![A-Za-z0-9_])')
SCHEMA='''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE owners(file_id INTEGER PRIMARY KEY,digest BLOB NOT NULL);
CREATE TABLE spellings(norm TEXT NOT NULL,form TEXT NOT NULL,block_id INTEGER NOT NULL,
                       file_id INTEGER NOT NULL,marked INTEGER NOT NULL,codeish INTEGER NOT NULL,
                       PRIMARY KEY(norm,form,block_id)) WITHOUT ROWID;
CREATE INDEX spelling_file ON spellings(file_id);
CREATE INDEX spelling_block ON spellings(block_id);
CREATE TABLE locations(block_id INTEGER PRIMARY KEY,file_id INTEGER NOT NULL,path TEXT NOT NULL,ordinal INTEGER NOT NULL);
CREATE VIRTUAL TABLE normalized USING fts5(content,tokenize='unicode61 remove_diacritics 2');'''


def norm(text):return text.replace('_','').lower()


def derived(text):
    words=WORDS.findall(text);marked=set()
    for literal in re.findall(r'`{1,2}([^`\n]{1,512})`{1,2}',text):marked.update(WORDS.findall(literal))
    extras=[];forms=[]
    for word in dict.fromkeys(words):
        parts=components(word);codeish='_' in word or len(parts)>1
        forms.append((norm(word),word,int(word in marked),int(codeish)))
    for word in words:
        if '_' in word:extras.append(norm(word))
        elif len(components(word))>1:extras.extend(components(word))
    return text+'\n'+' '.join(extras),forms


def ownership_snapshot(con):
    """Serialize writers before reading the cache used to decide invalidation."""
    con.execute('BEGIN IMMEDIATE')
    return dict(con.execute('SELECT file_id,digest FROM owners'))


def update(pack,index,*,create=False):
    index=Path(index)
    if create and index.exists():raise ValueError('New side-index path required')
    if not create and not index.exists():raise ValueError('Missing side index')
    con=sqlite3.connect(index)
    try:
        if create:con.executescript(SCHEMA)
        old=ownership_snapshot(con)
        if not create and dict(con.execute('SELECT key,value FROM metadata')).get('version')!=VERSION:
            raise ValueError('Unknown side-index version')
        with open_pack(pack) as parent:
            manifest=read_manifest(parent);require_supported(manifest);require_clean_cache(parent)
            current=dict(parent.execute('SELECT file_id,digest FROM integrity_files'))
            changed={i for i,digest in current.items() if old.get(i)!=digest};removed=set(old)-set(current)
            for file_id in sorted(changed|removed):
                con.execute('DELETE FROM normalized WHERE rowid IN (SELECT block_id FROM locations WHERE file_id=?)',(file_id,))
                con.execute('DELETE FROM spellings WHERE file_id=?',(file_id,))
                con.execute('DELETE FROM locations WHERE file_id=?',(file_id,));con.execute('DELETE FROM owners WHERE file_id=?',(file_id,))
            requested=[]
            for file_id in sorted(changed):
                requested.extend(r[0] for r in parent.execute('SELECT id FROM blocks WHERE file_id=? ORDER BY ordinal',(file_id,)))
            blocks=load_blocks(parent,requested) if requested else []
            forms_count=0
            for block in blocks:
                body,forms=derived(block.text)
                # AST/static symbols are another explicit marker, without
                # pretending that every word in a manual is a defined symbol.
                symbols={r[0] for r in parent.execute('SELECT name FROM symbols WHERE block_id=?',(block.id,))}
                con.execute('INSERT INTO normalized(rowid,content) VALUES(?,?)',(block.id,body))
                con.execute('INSERT INTO locations VALUES(?,?,?,?)',(block.id,block.file_id,block.path,block.ordinal))
                con.executemany('INSERT INTO spellings VALUES(?,?,?,?,?,?)',
                                [(key,form,block.id,block.file_id,int(marked or form in symbols),codeish) for key,form,marked,codeish in forms])
                forms_count+=len(forms)
            con.executemany('INSERT INTO owners VALUES(?,?)',[(i,current[i]) for i in sorted(changed)])
            con.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('version',VERSION),('parent_root',manifest['root_sha256'])])
            con.commit()
            return {'files_changed':len(changed),'files_removed':len(removed),'blocks_derived':len(blocks),'forms_written':forms_count,
                    'files_reused':len(current)-len(changed),'parent_root':manifest['root_sha256']}
    except BaseException:
        con.rollback();raise
    finally:con.close()


def require_parent(con,parent):
    manifest=read_manifest(parent);require_supported(manifest);require_clean_cache(parent)
    metadata=dict(con.execute('SELECT key,value FROM metadata'))
    if metadata.get('version')!=VERSION or metadata.get('parent_root')!=manifest['root_sha256']:
        raise ValueError('Side index is stale or belongs to a different artifact')


@contextmanager
def open_index(index,parent):
    con=sqlite3.connect(Path(index).absolute().as_uri()+'?mode=ro',uri=True)
    try:
        con.execute('BEGIN');require_parent(con,parent);yield con
    finally:con.close()


def normalized_rank(con,query,limit=60):
    tokens=content_terms(query)
    if not tokens:return []
    match=' OR '.join('"'+t+'"' for t in tokens)
    return [r[0] for r in con.execute('SELECT n.rowid FROM normalized n JOIN locations l ON l.block_id=n.rowid '
            'WHERE normalized MATCH ? ORDER BY bm25(normalized),l.path COLLATE BINARY,l.ordinal LIMIT ?',(match,limit))]


def query_keys(query):
    words=list(WORDS.finditer(query));keys={}
    for i,word in enumerate(words):
        token=word.group()
        if '_' in token or len(components(token))>1:keys.setdefault(norm(token),[]).append(token)
        for n in range(2,5):
            group=words[i:i+n]
            if len(group)!=n:break
            if any(not re.fullmatch(r'[ \t]+',query[a.end():b.start()]) for a,b in zip(group,group[1:])):break
            if group[0].group().lower() in STOPWORDS or group[-1].group().lower() in STOPWORDS:continue
            key=''.join(norm(w.group()) for w in group)
            if len(key)<=80:keys.setdefault(key,[]).append(query[group[0].start():group[-1].end()])
    return keys


def canonical_rank(con,query,limit=60,*,marked_only=False):
    scores=defaultdict(set);observed=[];lookup=query_keys(query);locations={}
    for key,views in lookup.items():
        condition='marked=1' if marked_only else '(marked=1 OR codeish=1)'
        eligible=con.execute('SELECT 1 FROM spellings WHERE norm=? AND '+condition+' LIMIT 1',(key,)).fetchone()
        if not eligible:continue
        rows=con.execute('SELECT s.form,s.block_id,l.path,l.ordinal FROM spellings s JOIN locations l ON l.block_id=s.block_id '
                         'WHERE s.norm=?'+(' AND s.marked=1' if marked_only else '')+' ORDER BY s.form,s.block_id',(key,)).fetchall()
        forms=sorted({r[0] for r in rows})
        observed.append({'normalized':key,'query_views':views,'forms':forms,'collision':len(forms)>1})
        for form,block_id,path,ordinal in rows:
            scores[block_id].add(key);locations[block_id]=(path,ordinal)
    ranked=sorted(scores,key=lambda identity:(-len(scores[identity]),locations[identity]))
    return ranked[:limit],observed


def fuse(left,right,limit=60):
    scores={}
    for ids in (left,right):
        for rank,identity in enumerate(ids):scores[identity]=scores.get(identity,0)+1/(60+rank)
    return sorted(scores,key=lambda identity:-scores[identity])[:limit]


def variant_rank(parent,query,limit=60):
    """No-index control: concatenate/split identifier views into FTS phrases."""
    phrases={}
    for key,views in query_keys(query).items():
        phrases.setdefault(key,None)
        for view in views:
            parts=components(view)
            if len(parts)>1:phrases.setdefault(' '.join(parts),None)
    if not phrases:return []
    match=' OR '.join('"'+phrase+'"' for phrase in phrases)
    return [r[0] for r in parent.execute('SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid '
            'JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? '
            'ORDER BY bm25(lexical,1.0,1.0,1.0),f.path COLLATE BINARY,b.ordinal LIMIT ?',
            (match,limit))]

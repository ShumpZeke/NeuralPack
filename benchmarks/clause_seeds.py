"""Research-only verbatim query views; no generation and no product promotion."""
from dataclasses import dataclass
import re
import sqlite3
from benchmarks.fielded_seeds import terms
from benchmarks.hierarchical_seeds import passages


METHODS=('flat_fields','clause_rrf','clause_balanced','clause_rrf_focus')
ABBREVIATIONS=frozenset({'e.g.','i.e.','etc.','vs.','mr.','mrs.','dr.','prof.'})
OUTPUT_CLAUSE=re.compile(r'^(?:return|respond|output|give)\s+(?:only\s+)?(?:a\s+)?json\b',re.I)


def build(path,blocks):
    """Only the passage index needed here; no unused document or graph index."""
    con=sqlite3.connect(path)
    try:
        con.executescript('''BEGIN;
          CREATE VIRTUAL TABLE passages USING fts5(block_id UNINDEXED,name,path,body,tokenize='unicode61 remove_diacritics 2');
          CREATE TABLE locations(block_id INTEGER PRIMARY KEY,path TEXT NOT NULL,ordinal INTEGER NOT NULL);
        ''')
        con.executemany('INSERT INTO passages VALUES(?,?,?,?)',[(b.id,terms(b.name),terms(b.path),b.text) for b in blocks])
        con.executemany('INSERT INTO locations VALUES(?,?,?)',[(b.id,b.path,b.ordinal) for b in blocks])
        con.commit();return con
    except BaseException:
        con.close();raise


@dataclass(frozen=True)
class View:
    start:int
    end:int
    text:str


def split_clauses(query):
    """Verbatim spans outside quoted strings/brackets, not semantic decomposition."""
    if not isinstance(query,str):raise ValueError('query must be text')
    spans=[];start=0;i=0;quote=None;stack=[]
    def add(end):
        nonlocal start
        left=start;right=end
        while left<right and query[left].isspace():left+=1
        while right>left and query[right-1].isspace():right-=1
        if left<right:spans.append(View(left,right,query[left:right]))
        start=end
    while i<len(query):
        char=query[i]
        if quote:
            if char=='\\':i+=2;continue
            if query.startswith(quote,i):i+=len(quote);quote=None;continue
            i+=1;continue
        if char in "\"'`":
            # Apostrophes inside words are not quotation delimiters.
            if char=="'" and i and i+1<len(query) and query[i-1].isalnum() and query[i+1].isalnum():
                i+=1;continue
            quote=char*3 if query.startswith(char*3,i) else char
            i+=len(quote);continue
        if char in '([{':stack.append(char)
        elif char in ')]}' and stack:
            if stack[-1]=={')':'(',']':'[','}':'{'}[char]:stack.pop()
        elif not stack and char in '.;?!\n':
            boundary=char=='\n' or i+1==len(query) or query[i+1].isspace()
            if char=='.' and boundary:
                token=query[start:i+1].rsplit(None,1)[-1].lower()
                if token in ABBREVIATIONS or re.fullmatch(r'(?:[a-z]\.){2,}',token):boundary=False
            if boundary:add(i+1)
        i+=1
    add(len(query))
    return spans


def query_views(query,*,max_clauses=8,focus=False):
    if type(max_clauses) is not int or max_clauses<=0:raise ValueError('positive clause limit required')
    clauses=split_clauses(query);seen={query};views=[View(0,len(query),query)];excluded=0;duplicates=0;omitted=0
    for clause in clauses:
        if focus and OUTPUT_CLAUSE.match(clause.text):excluded+=1;continue
        if clause.text in seen:duplicates+=1;continue
        seen.add(clause.text)
        if len(views)>max_clauses:omitted+=1;continue
        views.append(clause)
    return views,{'output_views_excluded':excluded,'duplicates':duplicates,'omitted_clauses':omitted,
                  'semantic_decomposition':False,'original_query_retained':True}


def fuse(lists,limit,*,balanced=False):
    if balanced:
        seen=set();out=[]
        for position in range(max(map(len,lists),default=0)):
            for group in lists:
                if position<len(group) and group[position] not in seen:
                    seen.add(group[position]);out.append(group[position])
                    if len(out)==limit:return out
        return out
    scores={}
    for group in lists:
        for position,key in enumerate(group):scores[key]=scores.get(key,0)+1/(60+position)
    # All input rankings already have canonical source-order ties. Stable sort
    # makes the first occurrence deterministic without artifact insertion IDs.
    return sorted(scores,key=lambda key:-scores[key])[:limit]


def rank(con,query,method,limit=240):
    if method not in METHODS:raise ValueError('unknown clause method')
    if type(limit) is not int or limit<=0:raise ValueError('positive candidate limit required')
    if method=='flat_fields':views=[View(0,len(query),query)];info={}
    else:views,info=query_views(query,focus=method=='clause_rrf_focus')
    lists=[[r[0] for r in passages(con,v.text,limit)] for v in views]
    return fuse(lists,limit,balanced=method=='clause_balanced'),{
        **info,'views':[{'start':v.start,'end':v.end,'text':v.text,'candidates':len(ids)} for v,ids in zip(views,lists)],
        'policy':method,'original_query':query,'generative_calls':0}

"""Research query views: literal questions and static Python operation names.

Views only propose retrieval seeds. They never replace the caller's query,
execute supplied Python or assert semantic sufficiency or binding identity.
"""
import ast
from dataclasses import asdict
import re
from benchmarks.clause_seeds import View,split_clauses,query_views,fuse
from npk.pack.format import read_manifest,PackError
from npk.pack.select import _lexical_channel,_symbol_channel,_embedding_channel


METHODS=('bm25','clause_rrf','clause_balanced','question_only','operations_only','operations_rrf','hybrid','question_hybrid')
MAX_PARSE_CHARS=65536
MAX_AST_NODES=4096


def question_views(query):
    if not isinstance(query,str):raise ValueError('Query must be text')
    return [v for v in split_clauses(query) if v.text.rstrip().endswith('?')]


def python_regions(query):
    """Bounded literal regions; unsupported mixed syntax leaves broad retrieval."""
    regions=[]
    for match in re.finditer(r'^```(?:python|py)?[ \t]*\r?\n(.*?)^```[ \t]*\r?$',query,re.M|re.S):
        regions.append(View(match.start(1),match.end(1),match.group(1)))
        if len(regions)==8:break
    if regions:return regions
    # Plain Python or a trailing top-level definition after explanatory prose.
    starts=[0,*[m.start() for m in re.finditer(r'^(?:async[ \t]+)?(?:def|class)[ \t]+',query,re.M)]]
    return [View(start,len(query),query[start:]) for start in dict.fromkeys(starts)][:8]


def physical_lines(text):
    """Keep exact CR/LF spelling; Unicode separators inside strings are data."""
    return re.split(r'(?<=\n)|(?<=\r)(?!\n)',text)


def node_view(region,node):
    lines=physical_lines(region.text)
    def offset(line,column):
        # CPython AST columns are UTF-8 bytes, not Python string indexes.
        return sum(map(len,lines[:line-1]))+len(lines[line-1].encode('utf-8')[:column].decode('utf-8'))
    start=offset(node.lineno,node.col_offset);end=offset(node.end_lineno,node.end_col_offset)
    return View(region.start+start,region.start+end,region.text[start:end])


def operation_views(query):
    if not isinstance(query,str):raise ValueError('Query must be text')
    if len(query)>MAX_PARSE_CHARS:return [],{'parse_status':'query_limit','uncertainty':['static_parse_limit']}
    regions=python_regions(query);views=[];notes=[];parsed=False
    for region in regions:
        try:tree=ast.parse(region.text)
        except (SyntaxError,ValueError,RecursionError):continue
        nodes=[]
        for node in ast.walk(tree):
            nodes.append(node)
            if len(nodes)>MAX_AST_NODES:return [],{'parse_status':'node_limit','uncertainty':['static_parse_limit']}
        parsed=True
        for node in nodes:
            if isinstance(node,ast.Call):
                if isinstance(node.func,(ast.Name,ast.Attribute)):
                    view=node_view(region,node.func)
                    if isinstance(node.func,ast.Attribute):
                        part=view.text.rsplit('.',1)[-1].strip()
                        view=View(view.end-len(part),view.end,part)
                    if view.text.isidentifier():views.append(view)
                    if view.text in {'getattr','setattr','eval','exec','globals','locals','__import__','import_module'}:
                        notes.append('dynamic_behavior_unresolved')
                else:notes.append('dynamic_call_target_unresolved')
                for keyword in node.keywords:
                    if keyword.arg is not None:views.append(node_view(region,keyword))
                    else:notes.append('dynamic_keyword_arguments_unresolved')
            elif isinstance(node,ast.withitem) and isinstance(node.context_expr,ast.Attribute):
                view=node_view(region,node.context_expr);part=view.text.rsplit('.',1)[-1].strip()
                if part.isidentifier():views.append(View(view.end-len(part),view.end,part))
        # The first valid plain-code/suffix parse contains subsequent definitions.
        if region.end==len(query):break
    unique={}
    for view in sorted(views,key=lambda v:(v.start,v.end)):
        assert query[view.start:view.end]==view.text
        unique.setdefault(view.text,view)
    return list(unique.values()),{'parse_status':'parsed' if parsed else 'unsupported_syntax','uncertainty':sorted(set(notes))}


def focused_text(query):
    views=question_views(query)
    return '\n'.join(v.text for v in views) if views else query,views


def focused_lexical(con,query,view,limit):
    ids=_lexical_channel(con,view,limit)
    broadened=view==query
    if not ids and view!=query:
        ids=_lexical_channel(con,query,limit);broadened=True
    return ids,broadened


def rank(con,query,method,limit=60):
    if method not in METHODS:raise ValueError('Unknown operation method')
    if type(limit) is not int or limit<=0:raise ValueError('Positive candidate limit required')
    info={'method':method,'original_query':query,'generative_calls':0,'risk':'uncalibrated'}
    if method in ('hybrid','question_hybrid'):
        view,spans=focused_text(query) if method=='question_hybrid' else (query,[])
        manifest=read_manifest(con)
        if int(manifest['embedding_dim'])<=0:raise PackError('Hybrid requires actual compiled embeddings')
        lex=_lexical_channel(con,view,limit);symbols=_symbol_channel(con,view,limit)
        dense,top=_embedding_channel(con,view,limit,manifest)
        if not dense:raise PackError('Hybrid encoder unavailable')
        channels={'lexical':lex,'symbol':symbols}
        if top is None or top>=.35:channels['embedding']=dense
        info.update({'views':[asdict(v) for v in spans],'retrieval_query':view,'embedding_similarity':top,
                     'embedding_used':'embedding' in channels,'channels':[k for k,v in channels.items() if v]})
        ids=fuse(list(channels.values()),limit)
        if not ids and view!=query:
            ids,broad=rank(con,query,'hybrid',limit);info['broader_fallback']=True;info['fallback_signals']=broad
        return ids,info
    if method=='bm25':views=[View(0,len(query),query)]
    elif method.startswith('clause_'):
        views,observed=query_views(query);info.update(observed)
    elif method=='question_only':
        text,views=focused_text(query)
        ids,broadened=focused_lexical(con,query,text,limit)
        info.update({'views':[asdict(v) for v in views],'retrieval_query':text,'broader_fallback':broadened,'channels':['lexical']})
        return ids,info
    else:
        operations,observed=operation_views(query);info.update(observed)
        text=' '.join(v.text for v in operations)
        info.update({'operation_spans':[asdict(v) for v in operations],'operation_query':text,'channels':['lexical']})
        if method=='operations_only':
            ids,broadened=focused_lexical(con,query,text if operations else query,limit)
            info['broader_fallback']=broadened
            return ids,info
        questions=question_views(query)
        streams=[query,*(['\n'.join(v.text for v in questions)] if questions else []),*([text] if operations else [])]
        streams=list(dict.fromkeys(streams));info['retrieval_queries']=streams
        return fuse([_lexical_channel(con,s,limit) for s in streams],limit),info
    info.update({'views':[asdict(v) for v in views],'channels':['lexical']})
    return fuse([_lexical_channel(con,v.text,limit) for v in views],limit,balanced=method=='clause_balanced'),info

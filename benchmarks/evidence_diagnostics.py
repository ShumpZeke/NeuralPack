"""LOCAL source controls and provenance rendering; no generative selection.

Trace controls use privileged executable test definitions. They are diagnostics
of answer failure, not a deployable retrieval method or proof of minimal context.
Only pinned library source is rendered; oracle bodies, values and return data
are never added to evidence.
"""
import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from unittest.mock import patch
from npk.pack.compile import _class_member_spans,estimate_tokens


@dataclass(frozen=True)
class Piece:
    path:str
    start:int
    end:int
    text:str
    symbols:tuple=()

    @property
    def span(self):return f'{self.path}:{self.start}-{self.end}'


def definitions(path):
    result={};contexts={}
    def visit(body,prefix='',owners=()):
        for node in body:
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):continue
            name=prefix+node.name
            start=min([node.lineno]+[d.lineno for d in node.decorator_list])
            result[name]={'span':(start,node.end_lineno),'owners':owners,'kind':'class' if isinstance(node,ast.ClassDef) else 'function'}
            if isinstance(node,ast.ClassDef):
                contexts[name]=[(s,e) for s,e,kind,_ in _class_member_spans(node,name) if kind=='class_context']
                visit(node.body,name+'.',(*owners,name))
            else:visit(node.body,name+'.',owners)
    visit(ast.parse(path.read_text(encoding='utf-8')).body)
    return result,contexts


def pieces_from_symbols(source,requests,*,include_class_context=False):
    spans=[];parsed={}
    for path,symbol in sorted(set(requests)):
        if path not in parsed:parsed[path]=definitions(source/path)
        defs,contexts=parsed[path]
        if symbol not in defs:raise ValueError('diagnostic symbol does not match source')
        item=defs[symbol];spans.append((path,*item['span'],symbol))
        if include_class_context:
            for owner in item['owners']:
                spans.extend((path,start,end,owner) for start,end in contexts[owner])
    merged=[]
    for path,start,end,symbol in sorted(spans):
        if merged and merged[-1][0]==path and start<=merged[-1][2]+1:
            row=merged[-1];row[2]=max(row[2],end);row[3].add(symbol)
        else:merged.append([path,start,end,{symbol}])
    result=[]
    for path,start,end,symbols in merged:
        text='\n'.join((source/path).read_text(encoding='utf-8').split('\n')[start-1:end])
        result.append(Piece(path,start,end,text,tuple(sorted(symbols))))
    return result


def trace_called_symbols(oracle,registered_files):
    """Record Python function identity only, with no locals, outputs or branch trace."""
    observed=set();unmapped=set()
    def profile(frame,event,arg):
        if event!='call':return
        path=registered_files.get(frame.f_code.co_filename)
        if path is None:return
        name=frame.f_code.co_qualname.replace('.<locals>.','.')
        if '<' not in name:observed.add((path,name))
        else:unmapped.add((path,name))
    previous=sys.getprofile()
    try:
        with patch('socket.socket.connect',side_effect=AssertionError('oracle attempted network')):
            sys.setprofile(profile)
            answer=oracle()
    finally:sys.setprofile(previous)
    return observed,unmapped,answer


def from_evidence(evidence):
    start,end=map(int,evidence.span.rsplit(':',1)[1].split('-'))
    return Piece(evidence.path,start,end,evidence.text,(evidence.name,) if evidence.name else ())


def render(pieces,labeled):
    import json
    return '\n\n'.join(
        ('[Source: '+p.span+'; symbols: '+json.dumps(p.symbols,ensure_ascii=False)+']\n' if labeled else '')+p.text
        for p in pieces)


def fit_labeled(pieces,budget):
    kept=[]
    for piece in pieces:
        if estimate_tokens(render([*kept,piece],True))<=budget:kept.append(piece)
    return kept


def validate_pieces(source,pieces):
    for piece in pieces:
        path=(source/piece.path).resolve()
        if not path.is_relative_to(source.resolve()):raise ValueError('evidence path escaped source')
        lines=path.read_text(encoding='utf-8').split('\n')
        if not 1<=piece.start<=piece.end<=len(lines) or piece.text!='\n'.join(lines[piece.start-1:piece.end]):
            raise ValueError('evidence is not literal source at its declared span')

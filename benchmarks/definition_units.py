"""Research: whole definitions and conservative local lexical binding links.

Links are syntactic hypotheses, not a proof of executable dependency closure.
All possible simple binders are retained; compound statements keep their guards.
No code executes. Dynamic imports, runtime mutation and inheritance are not solved.
"""
from dataclasses import dataclass, field
import ast
import symtable


@dataclass
class Unit:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str
    kind: str
    scope: tuple[str, ...]
    name: str | None
    links: set[str] = field(default_factory=set)


def bound_names(node):
    def targets(target):
        if isinstance(target,ast.Name):return {target.id}
        if isinstance(target,(ast.Tuple,ast.List)):
            return set().union(*(targets(t) for t in target.elts))
        return set()
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):return {node.name}
    if isinstance(node,ast.Import):return {a.asname or a.name.split('.')[0] for a in node.names}
    if isinstance(node,ast.ImportFrom):return {a.asname or a.name for a in node.names if a.name!='*'}
    if isinstance(node,ast.Assign):return set().union(*(targets(t) for t in node.targets))
    if isinstance(node,(ast.AnnAssign,ast.AugAssign)):return targets(node.target)
    if isinstance(node,(ast.If,ast.Try,ast.With,ast.For,ast.While,ast.AsyncWith,ast.AsyncFor)):
        found=set()
        for fieldname in ('body','orelse','finalbody'):
            for child in getattr(node,fieldname,[]):found.update(bound_names(child))
        for handler in getattr(node,'handlers',[]):
            for child in handler.body:found.update(bound_names(child))
        if isinstance(node,(ast.For,ast.AsyncFor)):found.update(targets(node.target))
        return found
    return set()


def referenced_globals(table):
    names={s.get_name() for s in table.get_symbols() if s.is_referenced() and s.is_global()}
    for child in table.get_children():names.update(referenced_globals(child))
    return names


class DefinitionIndex:
    def __init__(self,source):
        self.source=dict(source);self.units={};self.binders={};self.nodes={};self.scopes={};self.parse_failures=[]
        for path,text in sorted(source.items()):
            try:tree=ast.parse(text);table=symtable.symtable(text,path,'exec')
            except (SyntaxError,ValueError):self.parse_failures.append(path);continue
            tables={}
            def table_visit(t):
                tables[t.get_name(),t.get_lineno()]=t
                for child in t.get_children():table_visit(child)
            table_visit(table)
            self.scopes[path]=tables
            lines=text.split('\n')
            def visit(body,scope=()):
                for node in body:
                    lo=min([node.lineno,*[d.lineno for d in getattr(node,'decorator_list',[])]])
                    name=getattr(node,'name',None)
                    uid=f'{path}:{lo}-{node.end_lineno}:{type(node).__name__}'
                    unit=Unit(uid,path,lo,node.end_lineno,'\n'.join(lines[lo-1:node.end_lineno]),type(node).__name__,scope,name)
                    self.units[uid]=unit;self.nodes[uid]=node
                    for name in bound_names(node):self.binders.setdefault((path,scope,name),set()).add(uid)
                    if isinstance(node,ast.ClassDef):visit(node.body,(*scope,node.name))
            visit(tree.body)
        for uid,unit in self.units.items():self._link(uid,unit)

    def _lookup(self,path,scope,name):
        # A default expression is evaluated in the enclosing class/module scope.
        for n in range(len(scope),-1,-1):
            ids=self.binders.get((path,scope[:n],name))
            if ids:return ids
        return set()

    def _link(self,uid,unit):
        node=self.nodes[uid];names=set();local=set()
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            table=self.scopes[unit.path].get((node.name,node.lineno))
            if table:names.update(referenced_globals(table))
            signature=[*node.args.defaults,*[x for x in node.args.kw_defaults if x is not None],*node.decorator_list]
            for expr in signature:
                for child in ast.walk(expr):
                    if isinstance(child,ast.Name) and isinstance(child.ctx,ast.Load):local.add(child.id)
            # A heuristic for conventional instance/class method references.
            # Instance attributes may depend on construction; include __init__.
            args=[*node.args.posonlyargs,*node.args.args]
            is_static=any(isinstance(d,ast.Name) and d.id=='staticmethod' for d in node.decorator_list)
            if unit.scope and args and not is_static:
                receiver=args[0].arg
                for child in ast.walk(node):
                    if isinstance(child,ast.Attribute) and isinstance(child.ctx,ast.Load) and isinstance(child.value,ast.Name) and child.value.id==receiver:
                        member=self.binders.get((unit.path,unit.scope,child.attr),set())
                        if member:unit.links.update(member)
                        else:unit.links.update(self.binders.get((unit.path,unit.scope,'__init__'),set()))
        else:
            # Compound declarations are preserved whole. This deliberately may
            # over-approximate local reads inside them; no sufficiency claim.
            local.update(n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load))
        for name in names:unit.links.update(self.binders.get((unit.path,(),name),set()))
        for name in local:unit.links.update(self._lookup(unit.path,unit.scope,name))
        if isinstance(node,ast.ImportFrom):
            package=unit.path[:-3].split('/')
            if package[-1]=='__init__':package=package[:-1]
            else:package=package[:-1]
            if node.level:
                base=package[:len(package)-node.level+1]
                module='.'.join([*base,*((node.module or '').split('.') if node.module else [])])
            else:module=node.module or ''
            for target in (module.replace('.','/')+'.py',module.replace('.','/')+'/__init__.py'):
                if target in self.source:
                    for alias in node.names:unit.links.update(self.binders.get((target,(),alias.name),set()))
        unit.links.discard(uid)

    def owner(self,path,start,end):
        """Only a whole function containing the block is an automatic bundle."""
        candidates=[u for u in self.units.values() if u.path==path and u.kind in ('FunctionDef','AsyncFunctionDef')
                    and u.start_line<=start and u.end_line>=end]
        return min(candidates,key=lambda u:(u.end_line-u.start_line,u.start_line)).id if candidates else None

    def closure(self,seeds,depth):
        if type(depth) is not int or depth<0:raise ValueError('Nonnegative integer depth required')
        if any(uid not in self.units for uid in seeds):raise ValueError('Unknown definition seed')
        seen=set(seeds);front=set(seeds)
        for _ in range(depth):
            new=set().union(*(self.units[uid].links for uid in front))-seen if front else set()
            seen.update(new);front=new
        return sorted(seen)

    def pieces(self,ids):
        spans={}
        for uid in ids:
            u=self.units[uid];spans.setdefault(u.path,[]).append((u.start_line,u.end_line))
        out=[]
        for path,ranges in sorted(spans.items()):
            merged=[]
            for lo,hi in sorted(ranges):
                if merged and lo<=merged[-1][1]+1:merged[-1][1]=max(merged[-1][1],hi)
                else:merged.append([lo,hi])
            for lo,hi in merged:out.append({'path':path,'start_line':lo,'end_line':hi,
                                           'text':'\n'.join(self.source[path].split('\n')[lo-1:hi])})
        return out


def render(pieces):
    return '\n\n'.join(f"[Source: {p['path']}:{p['start_line']}-{p['end_line']}]\n{p['text']}" for p in pieces)


def merge_pieces(source,pieces):
    """Canonical union of physical source intervals, preserving source order."""
    ranges={}
    for p in pieces:ranges.setdefault(p['path'],[]).append((p['start_line'],p['end_line']))
    result=[]
    for path,spans in sorted(ranges.items()):
        merged=[]
        for lo,hi in sorted(spans):
            if merged and lo<=merged[-1][1]+1:merged[-1][1]=max(merged[-1][1],hi)
            else:merged.append([lo,hi])
        lines=source[path].split('\n')
        for lo,hi in merged:
            if not 1<=lo<=hi<=len(lines):raise ValueError('Invalid source interval')
            result.append({'path':path,'start_line':lo,'end_line':hi,'text':'\n'.join(lines[lo-1:hi])})
    return result


def select(index,blocks,ranked,query,budget,count,*,mode):
    if mode not in ('raw','unit','links2','links4'):raise ValueError('Unknown definition policy')
    if type(budget) is not int or budget<1:raise ValueError('Positive integer budget required')
    if len(ranked)!=len(set(ranked)) or any(bid not in blocks for bid in ranked):raise ValueError('Invalid candidate identities')
    pieces=[];requests=[]
    for rank,bid in enumerate(ranked):
        b=blocks[bid]
        raw=[{'path':b['path'],'start_line':b['start_line'],'end_line':b['end_line'],'text':b['text']}]
        owner=index.owner(b['path'],b['start_line'],b['end_line']) if mode!='raw' else None
        options=[raw];wanted=raw
        if owner:
            unit=index.pieces([owner]);depth=int(mode[-1]) if mode.startswith('links') else 0
            wanted=index.pieces(index.closure([owner],depth))
            options=[wanted,unit,raw] if depth else [unit,raw]
        for option in options:
            proposed=merge_pieces(index.source,[*pieces,*option]);context=render(proposed)
            if context.strip() and count(context)<=budget:
                pieces=proposed;requests.append({'seed_block_id':bid,'rank':rank+1,'owner':owner,'wanted':wanted});break
    coverage={}
    for p in pieces:coverage.setdefault(p['path'],set()).update(range(p['start_line'],p['end_line']+1))
    unmet=[r['seed_block_id'] for r in requests if any(not set(range(p['start_line'],p['end_line']+1))<=coverage.get(p['path'],set()) for p in r['wanted'])]
    context=render(pieces);tokens=count(context)
    assert tokens<=budget
    return {'query':query,'budget':budget,'pieces':pieces,'context':context,'tokens':tokens,
            'mode':mode,'seed_requests':requests,'fallback_required':not pieces,
            'status':'fallback_required' if not pieces else 'structural_request_incomplete' if unmet else 'selected',
            'risk':{'calibration':'uncalibrated','unfulfilled_structural_requests':unmet,
                    'limitations':['Links are syntactic, not a sufficiency guarantee','Dynamic behavior and inheritance are unresolved']},
            'used_generative_llm':False}

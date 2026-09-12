"""Prospective source-behavior cases for clause-retrieval experiments.

Trusted local oracles are evaluated only to freeze answer labels. Their code,
values and privileged source-span labels are never used by a retriever.
"""
from collections import ChainMap, Counter
from collections.abc import Sequence
from contextlib import ExitStack, suppress
from functools import lru_cache, partialmethod, singledispatch, total_ordering
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from benchmarks.stdlib_tasks import Task
from benchmarks.repository_tasks import anchors


def outcome(call):
    try:return call()
    except (KeyError,TypeError) as error:return {'error':type(error).__name__}


def layered_scope():
    parent=ChainMap({'rate':2},{'rate':1,'timeout':9})
    child=parent.new_child({'local':'x'});child['rate']=7;del child['local']
    def remove():del child['timeout']
    return {'rate':child['rate'],'parent_rate':parent['rate'],'timeout':child['timeout'],
            'delete_inherited':outcome(remove),'front':dict(child.maps[0]),'keys':list(child)}


def signed_counts():
    c=Counter(a=2,b=0,c=-1)
    before={'equal_ignoring_zero':c==Counter(a=2,c=-1),'elements':list(c.elements()),
            'total':c.total(),'positive':dict(+c)}
    c.subtract({'a':3,'d':2})
    return {**before,'after_subtract':dict(c),'added':dict(c+Counter(a=2,c=2))}


def nested_cache():
    calls=[]
    @lru_cache(maxsize=2,typed=True)
    def f(x):calls.append(type(x[0]).__name__);return type(x[0]).__name__
    values=[f(x) for x in ((1,),(1.0,),(2,),(3,),(1.0,))]
    info=f.cache_info()
    return {'values':values,'calls':calls,'hits':info.hits,'misses':info.misses,'size':info.currsize}


def derived_ordering():
    @total_ordering
    class Item:
        def __init__(self,n):self.n=n
        def __lt__(self,other):return self.n<other.n if isinstance(other,Item) else NotImplemented
        def __eq__(self,other):return self.n==other.n if isinstance(other,Item) else NotImplemented
    a,b=Item(3),Item(3)
    return {'greater':a>b,'less_equal':a<=b,'greater_equal':a>=b,
            'direct_unsupported':a.__gt__(3) is NotImplemented,
            'operator_unsupported':outcome(lambda:a>3)}


def cleanup_suppression():
    def run(use_suppress):
        events=[]
        try:
            with ExitStack() as stack:
                def cleanup():events.append('cleanup');return True
                stack.callback(cleanup)
                if use_suppress:stack.enter_context(suppress(ValueError))
                events.append('body');raise ValueError('fixture')
        except ValueError:events.append('raised')
        else:events.append('suppressed')
        return events
    return {'callback_only':run(False),'with_suppress':run(True)}


def bound_partial():
    class Base:
        base=0
        def combine(self,left,right=0):return self.base+10*left+right
        fixed=partialmethod(combine,1)
    class Derived(Base):
        base=20
        def combine(self,left,right=0):return 999
    return {'base':Base().fixed(right=2),'derived':Derived().fixed(3),
            'overridden_direct':Derived().combine(1,3)}


def dispatched_types():
    @singledispatch
    def classify(value):return 'default'
    classify.register(Sequence,lambda value:'sequence')
    classify.register(str,lambda value:'text')
    classify.register(int|float,lambda value:'number')
    return {'values':[classify(v) for v in ('abc',(1,2),True,2.5,{'a':1})],
            'bool_dispatch':classify.dispatch(bool)(True)}


def missing_front():
    class Front(dict):
        def __missing__(self,key):self[key]=[];return self[key]
    front=Front();c=ChainMap(front,{'ready':[7]})
    missing=c.get('absent');before=dict(front)
    ready=c.get('ready')
    return {'missing':missing,'front_before':before,'ready':ready,'front_after':dict(front),
            'parent_ready':c.parents['ready'],'keys':list(c)}


TASKS=[
 Task('layered_scope',"Use the standard layered-dictionary view with front {'rate':2} and inherited {'rate':1,'timeout':9}. Create a child with {'local':'x'}; assign child rate=7, then delete local. Attempt to delete inherited timeout. Return JSON rate, parent_rate, timeout, delete_inherited ({\"error\":exception class}), front (child's first dictionary), keys (iteration order). Do not flatten the view before these operations.",layered_scope,
      (('collections/__init__.py','ChainMap.__getitem__'),('collections/__init__.py','ChainMap.new_child'),('collections/__init__.py','ChainMap.__delitem__'),('collections/__init__.py','ChainMap.__iter__'))),
 Task('signed_counts',"Start a standard counting dictionary with a=2,b=0,c=-1. Compare it to one with a=2,c=-1; list its repeated elements; compute total; apply unary plus. Next subtract {'a':3,'d':2} in place and add a new counting dictionary a=2,c=2. Return JSON equal_ignoring_zero, elements, total, positive, after_subtract, added. Keep zero and negative entries in plain dictionary conversions; do not replace subtraction with the binary subtraction operator.",signed_counts,
      (('collections/__init__.py','Counter.__eq__'),('collections/__init__.py','Counter.elements'),('collections/__init__.py','Counter.__pos__'),('collections/__init__.py','Counter.subtract'),('collections/__init__.py','Counter.__add__'))),
 Task('nested_cache',"Decorate f(x) with the standard least-recently-used memoization decorator, maxsize=2 and typed=True. Each actual function execution appends type(x[0]).__name__ to calls and returns that string. Call it with tuples (1,), (1.0,), (2,), (3,), (1.0,) in order. Return JSON values, calls, hits, misses, size. Do not assume the type option recursively distinguishes tuple contents.",nested_cache,
      (('functools.py','_make_key'),('functools.py','_lru_cache_wrapper'))),
 Task('derived_ordering',"A class Item(n) defines only __lt__ and __eq__: with another Item they compare n, otherwise each returns NotImplemented. Apply the standard decorator that fills the remaining ordering methods. For a=Item(3), b=Item(3), return JSON greater (a>b), less_equal (a<=b), greater_equal (a>=b), direct_unsupported (whether calling a.__gt__(3) returns NotImplemented), operator_unsupported (a>3 or {\"error\":exception class}). Do not treat NotImplemented as a boolean result of the operator.",derived_ordering,
      (('functools.py','total_ordering'),('functools.py','_gt_from_lt'),('functools.py','_le_from_lt'),('functools.py','_ge_from_lt'))),
 Task('cleanup_suppression',"Use the standard contextlib dynamic exit stack. Register via callback a no-argument function which appends 'cleanup' and returns True. Append 'body', then raise ValueError inside the with block; outside append 'raised' if ValueError escapes, otherwise 'suppressed'. Repeat in a fresh stack, entering suppress(ValueError) after registering the callback. Return JSON callback_only and with_suppress as event arrays. Does the callback's truthy return itself suppress the exception? Encode the answer in the arrays; do not invoke any external resource.",cleanup_suppression,
      (('contextlib.py','_BaseExitStack.callback'),('contextlib.py','_BaseExitStack._create_cb_wrapper'),('contextlib.py','ExitStack.__exit__'),('contextlib.py','suppress.__exit__'))),
 Task('bound_partial',"Base.base=0 and Base.combine(self,left,right=0) returns self.base+10*left+right. In Base's class body, create fixed using the standard partial-method descriptor on combine with first argument 1. Derived inherits Base, sets base=20, and overrides combine to return 999. Return JSON base (Base().fixed(right=2)), derived (Derived().fixed(3)), overridden_direct (Derived().combine(1,3)). Determine descriptor binding; do not simply dispatch fixed through the overridden method name.",bound_partial,
      (('functools.py','partialmethod.__init__'),('functools.py','partialmethod.__get__'))),
 Task('dispatched_types',"Create a standard single-dispatch generic function returning 'default'. Register the abstract Sequence type to return 'sequence', str to return 'text', and the union int|float to return 'number'. Evaluate on 'abc', (1,2), True, 2.5, and {'a':1}, in that order. Return JSON values and bool_dispatch (invoke dispatch(bool)'s returned implementation on True). Do not convert input types before dispatch.",dispatched_types,
      (('functools.py','singledispatch'),('functools.py','_find_impl'),('functools.py','_compose_mro'))),
 Task('missing_front',"Front is a dict subclass whose __missing__(key) inserts [] at that key and returns it. Put an empty Front first and {'ready':[7]} second in the standard layered-dictionary view. Call view.get('absent'), snapshot the front dictionary, then call view.get('ready'). Return JSON missing, front_before, ready, front_after, parent_ready (look up ready in the parents view), keys (final iteration order). Do not assume a get on the layered view is a plain dict.get on each component.",missing_front,
      (('collections/__init__.py','ChainMap.get'),('collections/__init__.py','ChainMap.__getitem__'),('collections/__init__.py','ChainMap.__contains__'),('collections/__init__.py','ChainMap.parents'))),
]


def freeze(source,output):
    assert sys.version_info[:3]==(3,12,10)
    if output.exists():raise ValueError('new frozen task file required')
    rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('oracle attempted network')):
        for task in TASKS:
            required=[{'path':'cpython/Lib/'+path,'symbol':symbol,'span':anchors(source/'cpython/Lib'/path)[symbol]}
                      for path,symbol in task.required]
            rows.append({'id':task.id,'family':task.id,'cohort':'prospective_clauses',
                         'question':'In CPython 3.12.10, '+task.question,'answer':task.oracle(),'required':required})
    data={'evidence_mode':'LOCAL','generative_calls':0,'python_version':'3.12.10','tasks':rows,
          'definition_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'limitations':['Developer-authored before retrieval, not independently sealed',
                         'Known standard-library code; new behaviors include missing methods, nested types and exception protocols',
                         'Required spans are conservative diagnostics, not proven sufficient/minimal evidence',
                         'The pure-Python memoization implementation describes behavior also supplied by the CPython C accelerator']}
    raw=json.dumps(data,indent=2).encode();output.write_bytes(raw)
    output.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest())
    print({'tasks':len(rows),'sha256':hashlib.sha256(raw).hexdigest(),'generative_calls':0})


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();freeze(a.source,a.output)

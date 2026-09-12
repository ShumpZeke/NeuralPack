"""Executable oracle checks independent of any retrieval implementation."""
from benchmarks import clause_tasks as c


def test_layered_mapping_scope_and_missing_factory():
    assert c.layered_scope()=={'rate':7,'parent_rate':2,'timeout':9,'delete_inherited':{'error':'KeyError'},'front':{'rate':7},'keys':['rate','timeout']}
    assert c.missing_front()=={'missing':None,'front_before':{},'ready':[],'front_after':{'ready':[]},'parent_ready':[7],'keys':['ready']}


def test_signed_count_semantics():
    assert c.signed_counts()=={'equal_ignoring_zero':True,'elements':['a','a'],'total':1,'positive':{'a':2},
                               'after_subtract':{'a':-1,'b':0,'c':-1,'d':-2},'added':{'a':1,'c':1}}


def test_nested_cache_types_are_not_recursive():
    assert c.nested_cache()=={'values':['int','int','int','int','float'],'calls':['int','int','int','float'],'hits':1,'misses':4,'size':2}


def test_ordering_and_exception_protocols():
    assert c.derived_ordering()=={'greater':False,'less_equal':True,'greater_equal':True,'direct_unsupported':True,'operator_unsupported':{'error':'TypeError'}}
    assert c.cleanup_suppression()=={'callback_only':['body','cleanup','raised'],'with_suppress':['body','cleanup','suppressed']}


def test_descriptor_and_dispatch_binding():
    assert c.bound_partial()=={'base':12,'derived':33,'overridden_direct':999}
    assert c.dispatched_types()=={'values':['text','sequence','number','number','default'],'bool_dispatch':'number'}

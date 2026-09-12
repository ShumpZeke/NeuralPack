from benchmarks.definition_units import DefinitionIndex,render,select


def named(index,name):
    return next(uid for uid,u in index.units.items() if u.name==name)


def test_default_dependencies_include_original_class_binding():
    src='class Policy:\n    LIMIT = 120\n    def __init__(self, cap=LIMIT):\n        self.cap = cap\n'
    index=DefinitionIndex({'a.py':src});uid=named(index,'__init__')
    body=render(index.pieces(index.closure([uid],1)))
    assert 'LIMIT = 120' in body and 'cap=LIMIT' in body


def test_compound_binding_keeps_condition_and_both_branches():
    src='FLAG = False\nif FLAG:\n    LIMIT = 3\nelse:\n    LIMIT = 9\ndef run():\n    return LIMIT\n'
    index=DefinitionIndex({'a.py':src});body=render(index.pieces(index.closure([named(index,'run')],2)))
    assert 'FLAG = False\nif FLAG:\n    LIMIT = 3\nelse:\n    LIMIT = 9' in body


def test_local_shadowing_does_not_pull_in_unrelated_global():
    src='X = "global decoy"\ndef run():\n    X = "local"\n    return X\n'
    index=DefinitionIndex({'a.py':src});body=render(index.pieces(index.closure([named(index,'run')],2)))
    assert 'global decoy' not in body and 'return X' in body


def test_transitive_aliases_and_relative_imports():
    index=DefinitionIndex({'p/a.py':'from .b import C\ndef run():\n    return C\n',
                           'p/b.py':'A=3\nB=A+4\nC=B*2\n'})
    uid=named(index,'run');short=render(index.pieces(index.closure([uid],1)))
    long=render(index.pieces(index.closure([uid],4)))
    assert 'A=3' not in short
    assert 'A=3\nB=A+4\nC=B*2' in long


def test_empty_seed_closure_stays_empty_and_different_requests_are_isolated():
    index=DefinitionIndex({'a.py':'A=3\ndef run():\n    return A\n'})
    before=index.closure([named(index,'run')],1)
    assert index.closure([],10)==[]
    assert index.closure([named(index,'run')],1)==before


def test_owner_recovers_whole_function_from_inner_capped_block():
    src='def f():\n    x=3\n    return x\ndef g():\n    return 7\n'
    index=DefinitionIndex({'a.py':src});uid=index.owner('a.py',2,3)
    assert uid==named(index,'f') and index.owner('a.py',2,5) is None
    p=index.pieces([uid])[0]
    assert p['start_line']==1 and p['end_line']==3 and p['text']=='def f():\n    x=3\n    return x'


def test_instance_member_links_include_constructor_without_linking_other_class():
    src='class A:\n    def __init__(self):\n        self.x=3\n    def run(self):\n        return self.x\nclass B:\n    def __init__(self):\n        self.x=9\n'
    index=DefinitionIndex({'a.py':src});body=render(index.pieces(index.closure([named(index,'run')],1)))
    assert 'self.x=3' in body and 'self.x=9' not in body


def test_staticmethod_argument_is_not_an_instance_receiver():
    src='class A:\n    def __init__(self):\n        self.x=3\n    @staticmethod\n    def read(other):\n        return other.x\n'
    index=DefinitionIndex({'a.py':src});body=render(index.pieces(index.closure([named(index,'read')],1)))
    assert 'self.x=3' not in body


def test_source_order_and_budget_include_headers_and_partial_reason():
    src='VALUE = '+repr('a'*180)+'\ndef run():\n    return VALUE\n'
    index=DefinitionIndex({'a.py':src})
    blocks={1:{'path':'a.py','start_line':2,'end_line':3,'text':'def run():\n    return VALUE'}}
    query='Keep\r\n猫 exactly'
    for cap in (1,50,90,200,400):
        r=select(index,blocks,[1],query,cap,len,mode='links2')
        assert r['query']==query and r['tokens']==len(r['context'])<=cap
        assert r['fallback_required']==(not r['pieces'])
        if cap==90:
            assert r['status']=='structural_request_incomplete'
            assert r['risk']['unfulfilled_structural_requests']==[1]
        if cap==400:
            assert r['status']=='selected' and r['context'].index('VALUE =')<r['context'].index('def run')
    empty=select(index,blocks,[],query,400,len,mode='links2')
    assert empty['fallback_required'] and empty['context']==''

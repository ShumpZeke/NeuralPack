from dataclasses import asdict
import pytest
from benchmarks.source_views import (docstring_lines,omit_docstrings,pack_views,
                                     prepared_pack_views)
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount,PreparedCostGraph
from tests.test_boundary_tokenizer import pipeline


def test_literal_only_full_file_docstring_detection():
    source = '\n'.join(['"module docs"', 'x = "value"', 'class C:', '    "class docs"',
                        '    async def f(self):', '        "function docs"', '        x = "kept"',
                        '        return x', 'def g(): "one line docs"; return 9',
                        'def h():', '    "docs" # retain comment', '    return 4'])
    assert docstring_lines(source) == ((1, 1), (4, 4), (6, 6))
    assert docstring_lines('def invalid(:') == ()
    assert docstring_lines('x = "ordinary literal"') == ()
    assert docstring_lines('def f():\n    f"interpolation"\n    return 1') == ()


def test_utf8_offsets_do_not_cut_a_statement_after_docstring():
    assert docstring_lines('def f():\n    "猫"; return 3') == ()
    assert docstring_lines('def f():\n    "猫"\n    return 3') == ((2, 2),)


def test_partial_block_has_exact_surviving_spans_and_marked_omissions():
    source = 'def f():\n    """cat\n    more\n    docs"""\n    return "猫"\n'
    spans = docstring_lines(source)
    view = omit_docstrings('\n'.join(source.split('\n')[2:]), 3, spans)
    assert view.omitted == ((3, 4),)
    assert view.text == '# [NPK: docstring omitted; source lines 3-4]\n    return "猫"\n'
    assert [asdict(f) for f in view.fragments] == [
        {'start_line':5, 'end_line':6, 'text':'    return "猫"\n'}]
    assert omit_docstrings('    more\n    docs"""', 3, spans) is None


def fixture():
    source = 'def f():\n    """' + 'documentation '*30 + '"""\n    return 7'
    block = {'path':'a.py', 'span':'a.py:1-3', 'name':'f', 'kind':'function',
             'start_line':1, 'end_line':3, 'text':source}
    return {1:block}, {1:omit_docstrings(source, 1, docstring_lines(source))}


def test_exact_budget_includes_markers_and_all_separators():
    blocks, views = fixture()
    blocks[2] = dict(blocks[1], path='b.py', span='b.py:1-1', end_line=1, text='second fact')
    query = '  keep\r\n猫 exactly  '
    for cap in range(1, 650, 7):
        for policy in ('raw', 'compact', 'rescue'):
            row = pack_views(query, cap, [1,2], blocks, views, len, policy=policy)
            assert row['query'] == query and row['tokens'] == len(row['context']) <= cap
            assert row['fallback_required'] == (not row['items'])
            assert row['context'] == '\n\n'.join(i['text'] for i in row['items'])
            assert not row['used_generative_llm']
    cap = len(views[1].text)
    assert pack_views(query, cap-1, [1], blocks, views, len, policy='rescue')['fallback_required']
    result = pack_views(query, cap, [1], blocks, views, len, policy='rescue')
    assert result['status'] == 'selected_with_omissions'
    assert result['risk'] == 'uncalibrated:docstrings_omitted'
    assert result['items'][0]['omitted'] == [(2, 2)]
    assert pack_views(query, 999, [1], blocks, views, len, policy='rescue')['status'] == 'selected'


def test_empty_seeds_and_cross_request_isolation():
    blocks, views = fixture()
    a = pack_views('a', 100, [1], blocks, views, len, policy='compact')
    b = pack_views('b', 100, [], blocks, views, len, policy='compact')
    assert b['fallback_required'] and b['context'] == '' and b['items'] == []
    c = pack_views('a', 100, [1], blocks, views, len, policy='compact')
    assert a == c


def test_prepared_admission_matches_whole_payload_counter():
    blocks, views = fixture()
    calls=[]
    def prepared(parts):
        calls.append(tuple(parts))
        return len('\n\n'.join(parts))
    for cap in range(1,650,13):
        for policy in ('raw','compact','rescue'):
            a=pack_views('q',cap,[1],blocks,views,len,policy=policy)
            b=pack_views('q',cap,[1],blocks,views,len,policy=policy,count_parts=prepared)
            assert a==b
    assert calls


def test_incremental_source_view_admission_matches_whole_tokenizer(pipeline):
    codec,asset=pipeline;blocks,views=fixture()
    blocks[2]=dict(blocks[1],path='b.py',span='b.py:1-1',name='small',
                   end_line=1,text='small implementation fact')
    texts=[b['text'] for b in blocks.values()]+[v.text for v in views.values()]
    fast=CompactBoundaryCount(asset);fast.prepare(texts)
    slow=CompactBoundaryCount(asset,prepared_bytes=0);slow.prepare(texts)
    compact_ids={bid for bid,view in views.items()
                 if fast.count(view.text)<fast.count(blocks[bid]['text'])}
    fields=('context','tokens','fallback_required','status','risk','policy')
    for cap in (2,8,20,80):
        for policy in ('raw','compact','rescue'):
            control=pack_views('q',cap,[1,2],blocks,views,fast.count,policy=policy,
                               count_parts=fast.count_parts)
            actual=pack_views('q',cap,[1,2],blocks,views,fast.count,policy=policy,
                              count_parts=fast.count_parts,state_counter=fast,
                              compact_ids=compact_ids)
            fallback=pack_views('q',cap,[1,2],blocks,views,slow.count,policy=policy,
                                count_parts=slow.count_parts,state_counter=slow)
            assert {k:actual[k] for k in fields}=={k:control[k] for k in fields}
            assert actual['items']==control['items']==fallback['items']
            assert actual['incremental_attempts']>0 and actual['fallback_attempts']==0
            assert fallback['fallback_attempts']>0
            assert actual['tokens']==len(codec.encode(actual['context'],add_special_tokens=False))

    graph=PreparedCostGraph(fast,texts)
    for policy in ('raw','compact','rescue'):
        packed=prepared_pack_views([1,2],[2,8,20,80],blocks,views,compact_ids,graph,policy)
        for cap,result in packed.items():
            context='\n\n'.join(views[bid].text if compact else blocks[bid]['text']
                                for bid,compact in result.representations)
            control=pack_views('q',cap,[1,2],blocks,views,fast.count,policy=policy)
            assert context==control['context']
            assert result.total_tokens==control['tokens']==len(
                codec.encode(context,add_special_tokens=False))



def test_docstrings_are_runtime_data_counterexample():
    # Actual execution is only of this synthetic test fixture, never repository source.
    source = 'def f():\n    """salt=7"""\n    return f.__doc__\n'
    full = {}; exec(source, full)
    view = omit_docstrings(source, 1, docstring_lines(source))
    compact = {}; exec(view.text, compact)
    assert full['f']() == 'salt=7' and compact['f']() is None
    assert 'salt=7' not in view.text  # Literal evidence has been lost, not safely summarized.


def test_documentation_question_can_lose_its_only_answer():
    blocks, views = fixture()
    q = 'What does the documentation of f say?'
    raw = pack_views(q, 999, [1], blocks, views, len, policy='raw')
    compact = pack_views(q, 999, [1], blocks, views, len, policy='compact')
    assert 'documentation '*30 in raw['context']
    assert 'documentation '*30 not in compact['context']
    assert compact['status'] == 'selected_with_omissions'


def test_compaction_can_displace_implementation_evidence_without_doc_dependence():
    # Smaller early noise can now fit, crowding out a later useful definition.
    # This falsifies universal retention dominance even for implementation questions.
    blocks, views = fixture()
    blocks[2]=dict(blocks[1],name='target',span='a.py:4-5',start_line=4,end_line=5,
                   text='def target():\n    return "critical fact"')
    cap=len(views[1].text)
    raw=pack_views('What does target return?',cap,[1,2],blocks,views,len,policy='raw')
    compact=pack_views('What does target return?',cap,[1,2],blocks,views,len,policy='compact')
    assert [i['block_id'] for i in raw['items']]==[2]
    assert [i['block_id'] for i in compact['items']]==[1]
    assert 'critical fact' in raw['context'] and 'critical fact' not in compact['context']


def test_reject_invalid_candidate_identity_and_budget():
    blocks, views = fixture()
    for ids, cap in (([1,1],100), ([9],100), ([1],True), ([1],0)):
        with pytest.raises(ValueError): pack_views('q', cap, ids, blocks, views, len, policy='raw')

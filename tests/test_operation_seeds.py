"""Counterexamples for optional static retrieval views and caller preservation."""
from unittest.mock import patch
import pytest
from benchmarks.operation_seeds import operation_views,question_views,rank,MAX_PARSE_CHARS
from benchmarks.unit_passages import select
from npk.pack import compile_pack
from npk.pack.format import open_pack


def test_static_names_use_byte_correct_literal_query_spans():
    query='What happens without a flush?\n\ndef scenario():\n    café="é"; séance.commit(); result=Session(autoflush=False)\n'
    views,info=operation_views(query)
    assert info['parse_status']=='parsed'
    assert [v.text for v in views]==['commit','Session','autoflush=False']
    assert all(query[v.start:v.end]==v.text for v in views)
    assert question_views(query)[0].text=='What happens without a flush?'


def test_dynamic_and_unparseable_behavior_is_not_claimed_resolved():
    views,info=operation_views("getattr(session, 'reset')(**options)\n")
    assert {'dynamic_behavior_unresolved','dynamic_call_target_unresolved','dynamic_keyword_arguments_unresolved'}<=set(info['uncertainty'])
    assert not any(v.text=='reset' for v in views)
    assert operation_views('def broken(:')[1]['parse_status']=='unsupported_syntax'
    assert operation_views('a'*(MAX_PARSE_CHARS+1))[1]['parse_status']=='query_limit'


def test_supplied_python_is_parsed_without_execution(tmp_path):
    victim=tmp_path/'must-not-exist'
    query=f'from pathlib import Path\nPath({str(victim)!r}).write_text("executed")\n'
    operation_views(query)
    assert not victim.exists()


def test_fenced_regions_do_not_import_strings_as_operations():
    query='Why?\n```python\ntext="session.delete()"\nsession.commit()\n```\nOther prose.\n```python\nsession.rollback()\n```'
    views,info=operation_views(query)
    assert [v.text for v in views]==['commit','rollback']


@pytest.mark.parametrize('method',['bm25','clause_rrf','clause_balanced','question_only','operations_only','operations_rrf'])
def test_views_preserve_query_system_and_budget_and_do_not_cross_requests(tmp_path,method):
    tree=tmp_path/'source';tree.mkdir();(tree/'source.txt').write_text('commit writes pending rows.\n\nrollback discards changes.\n')
    pack=tmp_path/'source.npk';compile_pack(tree,pack)
    query='Preserve café and do NOT delete anything.\nWhat does commit do?\n\ndef f():\n    session.commit()\n'
    def routed(con,q,limit):return rank(con,q,method,limit)[0]
    with patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')):
        with patch('benchmarks.unit_passages._lexical_channel',routed):
            first=select(pack,query,128,system_prompt='Never change these instructions.')
            unrelated=select(pack,'zzzznothingmatches',128)
            again=select(pack,query,128,system_prompt='Never change these instructions.')
            tiny=select(pack,query,1,system_prompt='Never change these instructions.')
    assert first.query==query and first.system_prompt=='Never change these instructions.'
    assert first.pieces and first.selected_tokens<=128 and first.context_text()==again.context_text()
    assert not unrelated.pieces and unrelated.status=='fallback_required'
    assert tiny.selected_tokens==0 and tiny.status=='fallback_required' and tiny.query==query


def test_unsupported_operations_broaden_to_original_query(tmp_path):
    tree=tmp_path/'source';tree.mkdir();(tree/'doc.txt').write_text('rollback undoes pending work.\n')
    pack=tmp_path/'source.npk';compile_pack(tree,pack)
    with open_pack(pack) as con:
        ids,info=rank(con,'How does rollback work?','operations_only')
    assert ids and info['broader_fallback'] and info['parse_status']=='unsupported_syntax'


@pytest.mark.parametrize('method',['question_only','operations_only'])
def test_empty_focused_seeds_retry_the_original_query(tmp_path,method):
    tree=tmp_path/'source';tree.mkdir();(tree/'doc.txt').write_text('rollback undoes pending work.\n')
    pack=tmp_path/'source.npk';compile_pack(tree,pack)
    query='The relevant operation is rollback. What is zzzmissing?\n\ndef f():\n    zzzmissing()\n'
    with open_pack(pack) as con:ids,info=rank(con,query,method)
    assert ids and info['broader_fallback'], 'A failed focused seed must broaden to the original request'


@pytest.mark.parametrize('newline',['\n','\r\n','\r'])
def test_unicode_line_separator_inside_a_string_is_not_a_python_newline(newline):
    query='label="first\u2028second"'+newline+'séance.commit()'+newline
    views,info=operation_views(query)
    assert info['parse_status']=='parsed' and [v.text for v in views]==['commit']
    assert all(query[v.start:v.end]==v.text for v in views)

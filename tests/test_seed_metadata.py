"""Seed failure and metadata integrity counterexamples before promotion."""
import importlib
import sqlite3
from unittest.mock import patch
import pytest

from benchmarks.seed_metadata import (analyzed,build,field_rank,literal_terms,original_index_rank,
                                      quoted_terms,raise_sites,require_parent)
from npk.pack import PackSelector,compile_pack,update_pack
from npk.pack.format import PackError,open_pack


def fixture(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'file.py').write_text('def get(id):\n    return id\n',encoding='utf-8')
    pack=tmp_path/'project.npk';compile_pack(source,pack,python_members=True)
    return source,pack


@pytest.mark.parametrize('name',['get','set','value','return','id','q','值'])
def test_explicit_literal_query_survives_the_filter(tmp_path,name):
    source=tmp_path/'source';source.mkdir()
    (source/'file.txt').write_text(f'{name} = 17',encoding='utf-8')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    query=f'What is `{name}`?\r\n'
    with open_pack(pack) as con:assert name in literal_terms(con,query)
    def challenger(con,q,limit,*_weights):return original_index_rank(con,q,limit,policy='literal')
    with patch('npk.pack.select._lexical_channel',challenger):
        result=PackSelector(pack).select(query,budget_tokens=50)
    assert result.query==query and result.context_text()==f'{name} = 17' and not result.seed_failed


def test_code_fences_are_not_misread_as_single_literal_identifiers():
    assert quoted_terms('```get``` and ``set`` and `value`')==['value']
    assert quoted_terms('`module.get`')==['module.get','module','get']
    assert analyzed('HTTPRequest retry_limit')==['httprequest','http','request','retry_limit','retry','limit']


def test_auxiliary_index_rejects_updated_parent_and_finds_metadata(tmp_path):
    source,pack=fixture(tmp_path);side=tmp_path/'seed.sqlite'
    build(pack,side,source,rival_analyze=analyzed,count_cl100k=len)
    con=sqlite3.connect(side)
    try:
        with open_pack(pack) as parent:
            require_parent(con,parent)
            assert field_rank(con,'file get',10,mode='fields')
        (source/'file.py').write_text('def set(id):\n    return id\n')
        update_pack(pack,source)
        with open_pack(pack) as parent:
            with pytest.raises(PackError,match='stale'):require_parent(con,parent)
    finally:con.close()


def test_raise_sites_keep_actual_physical_statement_locations():
    text='def outer():\n    text = "separator'+chr(0x2028)+'not a newline"\n    def inner():\n        raise errors.Special("x")\n    return inner\n'
    assert raise_sites(text)==[(4,4,'special')]
    assert raise_sites('def broken(:')==[]

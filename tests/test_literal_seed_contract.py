"""Explicit code references must survive natural-language query filtering."""
import pytest
from npk.pack import PackSelector,compile_pack


@pytest.mark.parametrize('name',['get','set','value','return','id','q','值','7'])
def test_public_selector_retrieves_explicit_short_or_filtered_literal(tmp_path,name):
    source=tmp_path/'source';source.mkdir()
    body=f'{name} = 17'
    (source/'fact.txt').write_text(body,encoding='utf-8')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    query=f'What is `{name}`?\r\n'
    result=PackSelector(pack).select(query,budget_tokens=50)
    assert result.query==query
    assert not result.seed_failed and result.context_text()==body
    assert result.total_tokens<=50 and not result.used_generative_llm


def test_literal_restoration_does_not_turn_function_words_into_evidence(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'fact.txt').write_text('the return value is 17',encoding='utf-8')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    for query in ('what is it','What is `missing_symbol`?'):
        result=PackSelector(pack).select(query,budget_tokens=50)
        assert result.query==query and result.seed_failed and not result.evidence
        assert result.as_dict()['reduction_pct'] is None


def test_atomic_references_keep_components_and_do_not_misread_fences():
    from npk.pack.select import _explicit_literals
    assert _explicit_literals('`Module.get` and `get`')==['module.get','module','get']
    assert _explicit_literals('```get``` and ``set`` and `value`')==['value']

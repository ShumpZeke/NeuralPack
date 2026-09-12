"""Research spelling expansion must retain literals and respect exact matches."""
import sqlite3
import pytest
from benchmarks.identifier_spelling import additions,terms


@pytest.mark.parametrize(('text','expected'),[
    ('retryBackoffMillis',['retry','backoff','millis']),
    ('HTTPStatusCode',['http','status','code']),
    ('getHTTPResponseCode',['http','response','code']),
    ('expireOnCommit',['expire','commit']),
])
def test_original_case_is_used_before_normalization(text,expected):
    result=terms(text);assert text.lower() in result
    assert all(p in result for p in expected)


def test_expansion_cannot_replace_originals_or_invent_missing_symbols():
    assert not additions('expire_on_commit HTTP plain')
    assert 'übergang' in terms('Übergang')
    assert 'forbidden' in terms('Do not drop forbidden values.  ')


def test_vocabulary_control_keeps_exact_compounds_undiluted():
    con=sqlite3.connect(':memory:');con.execute('CREATE VIRTUAL TABLE lexical USING fts5(body)')
    con.execute('INSERT INTO lexical VALUES(?)',('HTTPStatusCode is an actual symbol. expire_on_commit is a parameter.',))
    assert terms('HTTPStatusCode',con)==['httpstatuscode']
    assert 'expire' in terms('expireOnCommit',con)
    con.close()


def test_compiled_runtime_recovers_an_absent_camel_alias_without_a_model(tmp_path):
    from unittest.mock import patch
    from npk.pack import compile_pack,PackSelector
    root=tmp_path/'source';root.mkdir()
    (root/'retry.py').write_text('retry_backoff_millis = 300\n',encoding='utf-8')
    artifact=tmp_path/'project.npk';compile_pack(root,artifact)
    query='Explain retryBackoffMillis. Preserve this constraint.  '
    with patch('socket.socket.connect',side_effect=AssertionError('Runtime attempted network')):
        result=PackSelector(artifact).select(query,budget_tokens=100)
    assert result.query==query and 'retry_backoff_millis = 300' in result.context_text()
    assert not result.seed_failed and not result.used_generative_llm and result.total_tokens<=100


def test_compiled_runtime_keeps_a_known_compound_and_its_components(tmp_path):
    from npk.pack import compile_pack,PackSelector
    from npk.pack.format import open_pack
    from npk.pack.select import _lexical_terms
    root=tmp_path/'source';root.mkdir()
    (root/'enum.txt').write_text('HTTPStatusCode is an enum.\n')
    (root/'prose.txt').write_text('HTTP status code is unrelated prose.\n')
    artifact=tmp_path/'project.npk';compile_pack(root,artifact)
    with open_pack(artifact) as con:
        query_terms=_lexical_terms(con,'HTTPStatusCode')
        assert query_terms[0]=='httpstatuscode'
        assert all(term in query_terms for term in ('http','status','code'))
    result=PackSelector(artifact,candidate_limit=1).select('HTTPStatusCode',budget_tokens=100)
    assert len(result.evidence)==1 and result.evidence[0].path=='enum.txt'


def test_lowercase_occurrence_cannot_hide_later_case_boundaries():
    from npk.pack.select import _lexical_terms
    con=sqlite3.connect(':memory:');con.execute('CREATE VIRTUAL TABLE lexical USING fts5(body)')
    con.execute('INSERT INTO lexical VALUES(?)',('expire_on_commit is a parameter.',))
    result=_lexical_terms(con,'expireoncommit expireOncommit expireOnCommit')
    assert all(t in result for t in ('expireoncommit','expire','oncommit','commit'))
    con.close()


def test_literal_presence_is_not_proof_of_alias_resolution(tmp_path):
    """Preserve the observed someotherobject/some_other_object counterexample."""
    from npk.pack import compile_pack,PackSelector
    root=tmp_path/'source';root.mkdir()
    (root/'example.txt').write_text('someobject.related = someotherobject\n')
    (root/'parameter.txt').write_text('some_other_object is a different spelling.\n')
    artifact=tmp_path/'project.npk';compile_pack(root,artifact)
    result=PackSelector(artifact,candidate_limit=1).select('someOtherObject',budget_tokens=100)
    assert 'someotherobject' in result.context_text() and 'some_other_object' not in result.context_text()
    assert result.risk_band.startswith('uncalibrated:')

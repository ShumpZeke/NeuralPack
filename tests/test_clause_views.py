"""Research-channel invariants and counterexamples, not quality claims."""
import pytest
from benchmarks.clause_seeds import query_views,split_clauses,fuse


@pytest.mark.parametrize('query',[
    'Use version 3.12.10. Keep A.B and 1.5 intact; never delete the negative constraint.',
    'Read "a; b. c?" and \'x. y\'. Then compare.',
    'Use {"a": "x; y", "b": [1, 2]}. Return JSON a, b.',
    "Don't strip the user's input. Inspect `obj.method()`; stop.",
    'Use e.g. this example in the U.S.A. before leaving. Compare vs. that option.',
    '  First.\nSecond!\n\nKeep the final space.  ',
    '', 'No punctuation', 'An unmatched "quote. Holds the entire remainder; intact.',
    'Nested (one; two [three. four]) stays together. End.',
])
def test_every_view_is_a_verbatim_span_and_original_survives(query):
    views,info=query_views(query)
    assert views[0].text==query and info['original_query_retained']
    assert all(query[v.start:v.end]==v.text for v in views)
    spans=split_clauses(query)
    assert ''.join(c for v in spans for c in v.text if not c.isspace())==''.join(c for c in query if not c.isspace())


def test_quotes_versions_and_brackets_do_not_create_spurious_views():
    query='Use 3.12.10 and "one. two; three" with (a; b). Keep the constraint.'
    assert [v.text for v in split_clauses(query)]==[
        'Use 3.12.10 and "one. two; three" with (a; b).','Keep the constraint.']


def test_output_focus_keeps_original_question_and_all_constraints():
    query='Find the entry. Return JSON original_value and forbidden_value. Do not use version 2.'
    views,info=query_views(query,focus=True)
    assert views[0].text==query
    assert info['output_views_excluded']==1
    assert views[-1].text=='Do not use version 2.'


def test_duplicate_and_excess_clauses_do_not_silently_rewrite_original():
    query='Alpha. Alpha. Beta. Gamma. Delta.'
    views,info=query_views(query,max_clauses=2)
    assert views[0].text==query and len(views)==3
    assert info['duplicates']==1 and info['omitted_clauses']==2


def test_fusion_never_manufactures_seeds():
    for balanced in (False,True):
        assert fuse([[],[]],8,balanced=balanced)==[]
        result=fuse([[7,2],[2,3]],3,balanced=balanced)
        assert set(result)=={7,2,3} and len(result)==3


def test_views_do_not_leak_between_queries():
    query_views('private_alpha. More private_alpha.',focus=True)
    views,_=query_views('public_beta. More public_beta.')
    assert not any('private_alpha' in v.text for v in views)

from dataclasses import dataclass, field
import random

import pytest

from benchmarks.structural_intent import filter_relations, guarded_plan, surface_names


@pytest.mark.parametrize('query', [
    'Where is TypeError raised?', 'Where does code raise TypeError?',
    'Which function throws errors.TypeError?', 'Explain `raise TypeError`.',
    'Under what conditions is TypeError thrown?',
])
def test_explicit_positive_relation_survives(query):
    assert filter_relations(query, [('raises', 'typeerror')], 'conservative').relations == (('raises', 'typeerror'),)


@pytest.mark.parametrize('query', [
    'Create a traceback info Args: exc_type (Type[BaseException]): type?',
    'Where is TypeError caught?', 'Find raise_TypeError', 'Inspect errors.raise and TypeError',
    'Describe raiseTypeError and exception behavior', 'Describe \u03b1raise TypeError',
])
def test_nouns_and_identifier_parts_do_not_create_actions(query):
    for mode in ('action', 'conservative'):
        assert not filter_relations(query, [('raises', 'exc'), ('raises', 'typeerror')], mode).relations


@pytest.mark.parametrize('query', [
    'Which function does not raise TypeError?', 'How can we avoid raising TypeError?',
    "Which path doesn't raise TypeError?", 'Which path doesn\u2019t raise TypeError?',
    'Where is TypeError raised without being caught?',
    'Find mentions of the literal `raise TypeError`.',
    'Which function catches TypeError but raises ValueError?',
])
def test_conservative_guard_abstains_on_ambiguous_surface(query):
    relations = [('raises', 'typeerror'), ('raises', 'valueerror')]
    assert not filter_relations(query, relations, 'conservative').relations
    # The simpler action challenger intentionally does NOT solve negation.
    assert filter_relations(query, relations, 'action').relations == tuple(relations)


def test_guard_does_not_invent_argument_from_subwords():
    assert filter_relations('Where is BaseException raised?', [('raises', 'exc')], 'conservative').suppressed
    assert filter_relations('Where is exc_type raised?', [('raises', 'exc')], 'conservative').suppressed
    assert 'baseexception' in surface_names('BaseException')
    assert 'aseexception' not in surface_names('BaseException')


def test_conservative_false_negative_is_recorded():
    # Valid positive clause, but this deliberately limited parser abstains when
    # another clause negates a different exception. This is an accepted loss,
    # not evidence that all natural-language intent has been understood.
    query = 'Where is ValueError raised and TypeError not raised?'
    assert filter_relations(query, [('raises', 'valueerror')], 'conservative').suppressed


def test_no_relations_added_query_preserved_and_cross_request_isolation():
    @dataclass
    class Plan:
        raw: str
        facets: list = field(default_factory=lambda: [('typeerror', 2.5)])
        relations: list = field(default_factory=lambda: [('raises', 'typeerror')])

    rng = random.Random(2919)
    for _ in range(100):
        query = rng.choice(['\u503c: TypeError raised?', 'TypeError not raised?', 'No action'])
        plan = Plan(query)
        for mode in ('original', 'disabled', 'action', 'conservative'):
            fresh, decision = guarded_plan(plan, mode)
            assert fresh is not plan and fresh.raw.encode() == query.encode()
            assert fresh.facets == plan.facets == [('typeerror', 2.5)]
            assert set(decision.relations) <= set(plan.relations)
            assert list(decision.relations) + list(decision.suppressed) == plan.relations
            assert plan.relations == [('raises', 'typeerror')]


def test_unknown_mode_and_relation_fail_explicitly():
    with pytest.raises(ValueError): filter_relations('Q', [], 'magic')
    with pytest.raises(ValueError): filter_relations('Q', [('calls', 'foo')], 'conservative')

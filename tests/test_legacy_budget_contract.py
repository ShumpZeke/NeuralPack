"""Legacy prompt selector regressions, separate from compiled pack guarantees."""
import pytest
from npk.context.analyzer import estimate_tokens
from npk.context.info_gain import InformationGainSelector
from npk.context.retrieval import CodeContextRetriever


def block(text, name='fixture'):
    return {'name': name, 'text': text, 'content': text}


def test_oversized_seed_requires_fallback_instead_of_budget_override():
    blocks = [block('critical_setting = 7\n' * 80), block('irrelevant = 9')]
    out = InformationGainSelector(enable_escalation=False).select(blocks, 'critical_setting', {}, 20)
    assert out.seed_failed and not out.kept_indices
    assert out.selected_tokens == 0 and 'budget' in out.reason


def test_smaller_relevant_seed_is_tried_when_best_cannot_fit():
    blocks = [block('critical_setting = 7\n' * 80, 'critical_setting'), block('critical_setting=7')]
    out = InformationGainSelector(enable_escalation=False).select(blocks, 'critical_setting', {}, 20)
    assert out.kept_indices == [1] and not out.seed_failed


def test_joined_seed_budget_includes_separators_and_rounding():
    blocks = [block('retry=7', f'part{i}') for i in range(8)]
    out = InformationGainSelector(strategy='budget_fill', enable_escalation=False).select(blocks, 'retry', {}, 8)
    joined = '\n\n'.join(blocks[i]['text'] for i in out.kept_indices)
    assert estimate_tokens(joined) <= 8
    assert out.selected_tokens == estimate_tokens(joined)


@pytest.mark.parametrize('budget', [-1, 0, True, 1.5, '10'])
def test_invalid_seed_budget_rejected(budget):
    with pytest.raises(ValueError, match='positive integer'):
        InformationGainSelector(enable_escalation=False).select([block('retry=7')], 'retry', {}, budget)


def test_retriever_oversized_seed_is_explicit_full_fallback():
    context = '```File: huge.py\n' + 'critical_setting = 7\n' * 80 + '\n```\n\n```File: tiny.py\nirrelevant=9\n```'
    out, stats = CodeContextRetriever(enable_escalation=False).retrieve_relevant_context(context, 'critical_setting', max_token_budget=20)
    assert out == context and stats['seed_failed']
    assert stats['fallback_required'] and stats['budget_exceeded']


def test_dependency_join_overflow_requires_explicit_fallback(monkeypatch):
    retriever = CodeContextRetriever(enable_escalation=False)
    blocks = [block('retry=7', f'part{i}') for i in range(8)]
    monkeypatch.setattr(retriever, 'parse_blocks', lambda text: blocks)
    monkeypatch.setattr('npk.context.retrieval.ProgramGraphSlicer.compute_transitive_closure',
                        lambda *a, **k: set(range(8)))
    context = '\n\n'.join(b['text'] for b in blocks)
    out, stats = retriever.retrieve_relevant_context(context, 'retry', max_token_budget=8)
    assert out == context and stats['fallback_required'] and stats['seed_failed']


def test_single_block_over_budget_is_not_success():
    context = 'retry = 7\n' * 80
    out, stats = CodeContextRetriever(enable_escalation=False).retrieve_relevant_context(context, 'retry', max_token_budget=20)
    assert out == context and stats['fallback_required'] and stats['seed_failed']

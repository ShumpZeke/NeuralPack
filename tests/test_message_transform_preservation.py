"""Counterexamples to unconditional duplicate removal and prefix reordering."""
import pytest
from benchmarks.message_transform_cases import cases
from npk.context.safety import assess_risk, check_invariants
from npk.planner import ContextExecutionPlanner


@pytest.mark.parametrize('case', cases(), ids=lambda case: case['id'])
def test_default_preserves_semantically_significant_repetition_and_spacing(case):
    output, plan = ContextExecutionPlanner().plan_and_optimize(case['messages'])
    assert output == case['messages']
    assert plan.tokens_avoided == 0


def test_missing_selection_measurements_do_not_imply_losslessness():
    risk = assess_risk(strategy='unmeasured_transform', original_tokens=1000, optimized_tokens=200)
    assert risk.band == 'uncalibrated:unknown'
    assert risk.signals['missing_selection_signals'] is True
    assert risk.signals.get('lossless_only') is not True
    assert risk.calibrated is False


def test_unchanged_context_is_an_explicit_preservation_signal():
    risk = assess_risk(strategy='passthrough', original_tokens=1000, optimized_tokens=1000,
                       context_unchanged=True)
    assert risk.signals['context_unchanged'] is True
    assert risk.band == 'uncalibrated:passthrough'
    assert risk.calibrated is False


@pytest.mark.parametrize('change', ['tool_link', 'assistant_content', 'order', 'system_duplicate'])
def test_message_envelope_and_history_changes_are_rejected(change):
    original = [
        {'role': 'system', 'content': 'Preserve transaction chronology.'},
        {'role': 'system', 'content': 'Preserve transaction chronology.'},
        {'role': 'assistant', 'content': 'The last check failed.'},
        {'role': 'tool', 'tool_call_id': 'synthetic-call-1', 'content': 'status=failed'},
        {'role': 'user', 'content': 'What happened?'},
    ]
    changed = [dict(m) for m in original]
    if change == 'tool_link': changed[3]['tool_call_id'] = 'synthetic-call-2'
    elif change == 'assistant_content': changed[2]['content'] = 'The last check passed.'
    elif change == 'order': changed[2], changed[3] = changed[3], changed[2]
    else: changed.pop(0)
    assert not check_invariants(original, changed).ok

"""Cost claims need an identified provider and real, scoped pricing evidence."""
import json
import pytest
from npk.cost import ModelPricing, estimate_cost, get_pricing, calculate_savings
from npk.planner import ContextExecutionPlanner
from npk.runtime import NeuralPackClient
from npk.telemetry import analyze_traces


@pytest.mark.parametrize('model', ['unknown-model', 'mock', 'default', 'meta/llama-3.2-11b-vision-instruct'])
def test_unknown_or_mock_prices_are_absent(model):
    assert get_pricing(model) is None
    assert estimate_cost(model, 10000, 100) is None
    assert calculate_savings(model, 10000, 2000) == (None, None, None, None)


@pytest.mark.parametrize('counts', [(-1, 0, 0), (1, -1, 0), (1, 0, 2), (True, 0, 0), (1.5, 0, 0)])
def test_invalid_usage_is_rejected_even_without_a_price(counts):
    rejected = False
    try:
        estimate_cost('unknown', *counts)
    except ValueError:
        rejected = True
    assert rejected


def test_placeholder_provenance_cannot_be_verified():
    rejected = False
    try:
        ModelPricing(1, 1, 1, 'openai', 'RE-VERIFY before publishing', '2026-09-05')
    except ValueError:
        rejected = True
    assert rejected


def test_provider_identity_precision_and_signed_savings():
    assert get_pricing('gpt-4o-mini', provider='mock') is None
    assert get_pricing('gpt-4o-mini', provider='openai_compatible') is None
    assert get_pricing('gpt-4o-mini') is None
    quote = get_pricing('gpt-4o-mini', provider='openai')
    assert quote.source.startswith('https://developers.openai.com/')
    assert quote.verified_on == '2026-09-07'
    assert estimate_cost('gpt-4o-mini', 1, cached_input_tokens=1, provider='openai') == pytest.approx(0.000000075)
    original, optimized, saved, percent = calculate_savings('gpt-4o-mini', 100, 200, provider='openai')
    assert saved < 0 and percent == pytest.approx(-100)
    assert calculate_savings('gpt-4o-mini', 0, 0, provider='openai')[-1] is None


def test_unpriced_planner_still_works_without_inventing_forecasts():
    messages = [{'role': 'system', 'content': 'Keep this instruction.'}, {'role': 'user', 'content': 'Explain retries.'}]
    result, plan = ContextExecutionPlanner(target_model='unknown').plan_and_optimize(messages)
    assert result == messages
    assert all(c.estimated_cost_usd is None for c in plan.candidates)
    assert all(c.estimated_output_tokens is None and c.estimated_latency_ms is None for c in plan.candidates)
    assert plan.estimated_savings is None
    assert 'N/A' in plan.to_yaml_str()


@pytest.mark.parametrize('mode', ['baseline', 'optimized', 'shadow'])
def test_mock_runtime_cannot_emit_dollar_claims_or_mixed_token_counts(tmp_path, mode):
    path = tmp_path/'traces.jsonl'
    client = NeuralPackClient(provider='mock', default_model='gpt-4o-mini', mode=mode, trace_path=str(path))
    client.chat_completion([{'role': 'user', 'content': 'Explain retries.'}])
    row = json.loads(path.read_text())
    assert row['original_cost_est'] is None and row['cost_saved_est'] is None
    assert row['tokens_avoided'] == row['original_tokens'] - row['optimized_tokens']
    assert row['evidence_mode'] == 'MOCK'
    summary = analyze_traces(path)
    assert summary['total_cost_saved_est'] is None


def test_legacy_trace_cost_claims_are_not_accepted_as_evidence(tmp_path):
    path = tmp_path/'old.jsonl'
    path.write_text(json.dumps({'request_id': 'old', 'original_tokens': 100, 'optimized_tokens': 1,
                               'tokens_avoided': 999, 'original_cost_est': 100, 'optimized_cost_est': 1,
                               'cost_saved_est': 99})+'\n')
    report = analyze_traces(path)
    assert report['total_cost_saved_est'] is None
    assert report['total_tokens_avoided'] is None
    assert report['legacy_records'] == 1


def test_corrupt_trace_is_not_silently_skipped(tmp_path):
    path = tmp_path/'bad.jsonl'; path.write_text('{bad\n')
    rejected = False
    try: analyze_traces(path)
    except ValueError: rejected = True
    assert rejected


@pytest.mark.parametrize('mode', ['optimized', 'shadow'])
def test_runtime_risk_limit_is_not_inverted(tmp_path, monkeypatch, mode):
    client = NeuralPackClient(provider='mock', quality_threshold=.05, trace_path=str(tmp_path/'trace'))
    original = client.planner.plan_and_optimize
    observed = []
    def spy(*args, **kwargs):
        observed.append(kwargs['quality_threshold'])
        return original(*args, **kwargs)
    monkeypatch.setattr(client.planner, 'plan_and_optimize', spy)
    client.chat_completion([{'role': 'user', 'content': 'Explain retries.'}], mode_override=mode)
    assert observed == [.95]


def test_shadow_does_not_count_hypothetical_reduction_as_executed(tmp_path):
    path = tmp_path/'shadow.jsonl'
    # Relevant source plus distinct unrelated files exercises real lexical
    # selection; repeated paragraphs cannot be assumed semantically redundant.
    text = '```File: settings.py\nRETRY_COUNT = 4\n```\n\n' + '\n\n'.join(
        f'```File: drawing_{i}.py\ndef draw_{i}():\n    return {i}\n```' for i in range(20))
    client = NeuralPackClient(provider='mock', mode='shadow', quality_threshold=.5, trace_path=str(path))
    client.chat_completion([{'role': 'user', 'content': text}, {'role': 'user', 'content': 'What is RETRY_COUNT?'}])
    row = json.loads(path.read_text())
    assert row['tokens_avoided'] == 0
    assert row['plan_details']['hypothetical_plan']['metadata']['tokens_avoided'] > 0


def test_passthrough_is_preservation_evidence_not_calibrated_answer_risk():
    _, plan = ContextExecutionPlanner().plan_and_optimize([{'role': 'user', 'content': 'Explain retries.'}])
    assert all(c.risk_calibrated is False for c in plan.candidates)
    assert plan.candidates[0].risk_signals['dropped_context_fraction'] == 0

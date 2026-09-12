"""Economics must use the same frozen prompts, answers and usage as its grades."""
import hashlib
import json
import socket
import pytest
from benchmarks.economics import report
from benchmarks.prospective_eval import request_key, write_json
from benchmarks.repository_eval import grade_answer


def fixture(root):
    (root/'contexts').mkdir(); (root/'responses').mkdir()
    context = 'source'; digest = hashlib.sha256(context.encode()).hexdigest()
    (root/'contexts'/(digest+'.txt')).write_text(context)
    settings = {'model': 'gpt-4o-mini', 'temperature': 0, 'max_output_tokens': 10, 'system_prompt': 'Answer as JSON'}
    question = 'What is the answer?'; key = request_key(settings, question, context)
    observation = {'task': 'one', 'method': 'bm25', 'budget': 100, 'request_sha256': key, 'selected_tokens': 1}
    plan = {'settings': settings, 'dataset': {'tasks': [{'id': 'one', 'answer': {'a': 1}}]},
            'observations': [observation], 'requests': {key: {'question': question, 'context_sha256': digest}}}
    usage = {'prompt_tokens': 10, 'completion_tokens': 2}
    result = {'evidence_mode': 'MOCK', 'request_sha256': key, 'content': '{"a":1}',
              'transport_success': True, 'api_attempts_this_run': 0, 'usage': usage,
              'raw_response': {'model': 'gpt-4o-mini', 'choices': [{'message': {'content': '{"a":1}'}}], 'usage': usage}}
    write_json(root/'plan.json', plan)
    plan_sha = hashlib.sha256((root/'plan.json').read_bytes()).hexdigest(); (root/'plan.sha256').write_text(plan_sha)
    write_json(root/'ledger.json', {key: {'state': 'DONE', 'result': result}})
    write_json(root/'responses'/(key+'.json'), result)
    write_json(root/'results.json', {'plan': plan, 'plan_sha256': plan_sha,
                                    'rows': [{**observation, **result, **grade_answer(result['content'], {'a': 1})}]})


def test_report_has_no_hidden_calls_or_borrowed_economics(tmp_path, monkeypatch):
    fixture(tmp_path)
    def forbidden(*a, **kw): raise AssertionError('network called')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    summary = report(tmp_path)
    assert summary['live_attempts_in_ledger'] == 0
    assert summary['evidence_mode'] == 'REPLAY' and summary['new_api_calls'] == 0
    assert summary['metric'] == 'exact JSON fixture pass counts'
    assert summary['completed_unique_text_quote_usd'] is None
    assert summary['break_even_requests'] is None and summary['net_savings_usd'] is None
    assert len(summary['arms']) == 1 and summary['arms'][0]['passed'] == 1
    priced = report(tmp_path, provider='openai')
    assert priced['completed_unique_text_quote_usd'] == pytest.approx(0.0000027)
    assert priced['actual_billed_usd'] is None
    assert priced['pricing_sources']['gpt-4o-mini']['verified_on'] == '2026-09-07'


@pytest.mark.parametrize('attack', ['drop', 'answer', 'usage', 'context', 'plan'])
def test_economic_report_rejects_changed_evidence(tmp_path, attack):
    fixture(tmp_path)
    path = tmp_path/'results.json'; data = json.loads(path.read_text())
    if attack == 'drop': data['rows'] = []
    elif attack == 'answer':
        data['rows'][0]['content'] = '{"a":2}'
        data['rows'][0].update(grade_answer('{"a":2}', {'a': 1}))
    elif attack == 'usage': data['rows'][0]['usage']['prompt_tokens'] = 1
    elif attack == 'context': next((tmp_path/'contexts').iterdir()).write_text('changed')
    elif attack == 'plan': data['plan']['dataset']['tasks'][0]['answer'] = {'a': 2}
    write_json(path, data)
    rejected = False
    try: report(tmp_path)
    except ValueError: rejected = True
    assert rejected


def test_unknown_call_count_is_not_reported_as_zero(tmp_path):
    fixture(tmp_path)
    ledger = json.loads((tmp_path/'ledger.json').read_text())
    key = next(iter(ledger)); del ledger[key]['result']['api_attempts_this_run']
    write_json(tmp_path/'ledger.json', ledger)
    write_json(tmp_path/'responses'/(key+'.json'), ledger[key]['result'])
    with pytest.raises(ValueError, match='API attempt'):
        report(tmp_path)

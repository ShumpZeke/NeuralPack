"""Synthetic transport fixtures only: these tests never contact a model."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest

from benchmarks import answer_recovery as recovery
from benchmarks import prospective_eval as executor
from benchmarks.answer_records import sha
from benchmarks.prospective_eval import request_key, write_json


def refused(call):
    try: call()
    except ValueError: return True
    return False


def fixture(root):
    parent = root/'parent'; parent.mkdir()
    for directory in ('contexts', 'responses'): (parent/directory).mkdir()
    settings = {'model': 'synthetic/model', 'system_prompt': 'JSON only', 'temperature': 0,
                'max_output_tokens': 16, 'chat_template_kwargs': {'enable_thinking': False}, 'timeout_seconds': 4}
    plan = {'created_utc': '2026-01-01T00:00:00+00:00', 'settings': settings,
            'requests': {}, 'observations': [], 'dataset': {'tasks': []},
            'corpus_tokens': 1, 'tokenizer_assets': {'files': {}}}
    ledger = {}; keys = []
    for i, status in enumerate((200, 503, 429, None)):
        context = 'Synthetic source '+str(i); question = 'Example question '+str(i)
        digest = sha(context.encode()); key = request_key(settings, question, context); keys.append(key)
        (parent/'contexts'/(digest+'.txt')).write_text(context)
        plan['requests'][key] = {'question': question, 'context_sha256': digest}
        plan['observations'].append({'task': str(i), 'method': 'none' if status else 'full',
            'budget': None, 'request_sha256': key, 'context_sha256': digest,
            'selected_tokens': 1, 'selected_prompt_tokens': 1, 'corpus_tokens': 1, 'available_tokens': 1})
        if status is None: continue  # Later stage has never been attempted.
        plan['dataset']['tasks'].append({'id': str(i), 'question': question, 'answer': {'value': i}})
        result = {'request_sha256': key, 'question': question, 'context_sha256': digest,
                  'evidence_mode': 'LIVE', 'api_attempts_this_run': 1, 'latency_ms': 1,
                  'transport_success': status == 200}
        if status == 200: result = answer(result)  # Deliberately WRONG answer: still must not be resampled.
        else: result['http_status'] = status
        write_json(parent/'responses'/(key+'.json'), result)
        ledger[key] = {'state': 'DONE', 'result': result}
    write_json(parent/'plan.json', plan); bind_plan(parent)
    write_json(parent/'ledger.json', ledger)
    return parent, root/'child', keys


def answer(result):
    result = deepcopy(result); result.pop('http_status', None)
    content = '{"value":999}'
    usage = {'prompt_tokens': 1, 'completion_tokens': 1}
    result.update(transport_success=True, content=content, usage=usage,
                  raw_response={'choices': [{'message': {'content': content}}], 'usage': usage})
    return result


def bind_plan(root):
    (root/'plan.sha256').write_text(sha((root/'plan.json').read_bytes()))


def prepare(parent, child):
    return recovery.prepare(parent, child, expected_plan=sha((parent/'plan.json').read_bytes()),
                            expected_ledger=sha((parent/'ledger.json').read_bytes()))


def test_known_failures_get_one_attempt_and_wrong_answers_are_never_resampled(tmp_path, monkeypatch):
    parent, child, keys = fixture(tmp_path)
    original = {p: p.read_bytes() for p in parent.rglob('*') if p.is_file()}
    def denied(*a, **kw): raise AssertionError('Preparation used network')
    monkeypatch.setattr('urllib.request.urlopen', denied)
    before = prepare(parent, child)
    assert before['original_answers'] == 1 and before['pending_retry_attempts'] == 2
    assert before['cumulative_api_attempts'] == 3 and before['retry_attempts'] == 0
    assert recovery.read(child/'plan.json')['transport_recovery']['retry_keys'] == keys[1:3]
    calls = []
    def fake_answer(**kw):
        key = request_key(recovery.read(child/'plan.json')['settings'], kw['question'], kw['context'])
        calls.append(key)
        result = answer(recovery.read(parent/'responses'/(key+'.json')))
        write_json(kw['cache']/(key+'.json'), result)
        return result
    monkeypatch.setattr(executor, 'live_answer', fake_answer)
    monkeypatch.setattr(executor.RequestPacer, 'wait', lambda self: None)
    args = SimpleNamespace(output=child, live=True, workers=1, max_requests=10,
                           min_request_interval=15, stop_after_errors=3)
    executor.execute(args); executor.execute(args)
    assert calls == keys[1:3], 'Executor repeated an answer or a terminal retry'
    after = recovery.validate_recovery(child)
    assert after['cumulative_api_attempts'] == 5 and after['retry_attempts'] == 2
    assert after['recovered_answers'] == 2 and after['unanswered_payloads'] == 0
    assert all(p.read_bytes() == body for p, body in original.items()), 'Parent attempt evidence changed'


@pytest.mark.parametrize('attack', ['STARTED', 'unknown_error', '401', 'hidden_answer', 'response_mismatch', 'wrong_digest'])
def test_recovery_refuses_uncertain_or_unapproved_parent_outcomes(tmp_path, attack):
    parent, child, keys = fixture(tmp_path); ledger = recovery.read(parent/'ledger.json')
    entry = ledger[keys[1]]
    if attack == 'STARTED': entry['state'] = 'STARTED'
    elif attack == 'unknown_error': entry['result'].pop('http_status')
    elif attack == '401': entry['result']['http_status'] = 401
    elif attack == 'hidden_answer': entry['result']['content'] = '{"value":5}'
    elif attack == 'response_mismatch': entry['result']['latency_ms'] = 500
    if attack != 'response_mismatch': write_json(parent/'responses'/(keys[1]+'.json'), entry['result'])
    write_json(parent/'ledger.json', ledger)
    if attack == 'wrong_digest':
        call = lambda: recovery.prepare(parent, child, expected_plan='0'*64,
                                         expected_ledger=sha((parent/'ledger.json').read_bytes()))
    else: call = lambda: prepare(parent, child)
    assert refused(call), 'Unsafe parent outcome accepted for recovery'
    assert not child.exists()


@pytest.mark.parametrize('attack', ['settings', 'task_answer', 'selection', 'retry_eligibility', 'missing_origin',
                                   'origin_bytes', 'context', 'resampled_success', 'missing_success',
                                   'changed_replay', 'unknown_retry', 'orphan_response', 'answer_type',
                                   'selection_type', 'policy_version_type', 'policy_status_type'])
def test_recovery_attacks_cannot_change_the_frozen_experiment(tmp_path, attack):
    parent, child, keys = fixture(tmp_path); prepare(parent, child)
    plan = recovery.read(child/'plan.json'); ledger = recovery.read(child/'ledger.json')
    if attack == 'settings': plan['settings']['temperature'] = 1
    elif attack == 'task_answer': plan['dataset']['tasks'][0]['answer'] = {'value': 999}
    elif attack == 'answer_type': plan['dataset']['tasks'][0]['answer'] = {'value': 0.0}
    elif attack == 'selection_type': plan['observations'][0]['selected_tokens'] = True
    elif attack == 'policy_version_type': plan['transport_recovery']['version'] = True
    elif attack == 'policy_status_type': plan['transport_recovery']['eligible_http_statuses'] = [429.0, 503.0]
    elif attack == 'selection': plan['observations'][0]['selected_tokens'] = 999
    elif attack == 'retry_eligibility': plan['transport_recovery']['retry_keys'] = keys[:3]
    elif attack == 'missing_origin': del plan['transport_recovery']['parent_records'][keys[1]]
    elif attack == 'origin_bytes':
        (child/'replay-origins'/(plan['transport_recovery']['parent_records'][keys[1]]+'.json')).write_text('{}')
    elif attack == 'context':
        (child/'contexts'/(plan['requests'][keys[1]]['context_sha256']+'.txt')).write_text('Changed source')
    elif attack == 'resampled_success':
        ledger[keys[0]]['result'] = recovery.read(parent/'responses'/(keys[0]+'.json'))
    elif attack == 'missing_success':
        del ledger[keys[0]]; (child/'responses'/(keys[0]+'.json')).unlink()
    elif attack == 'changed_replay':
        ledger[keys[0]]['result']['content'] = '{"value":0}'
        ledger[keys[0]]['result']['raw_response']['choices'][0]['message']['content'] = '{"value":0}'
    elif attack == 'unknown_retry': ledger[keys[1]] = {'state': 'STARTED'}
    else: write_json(child/'responses'/(keys[1]+'.json'), recovery.read(parent/'responses'/(keys[1]+'.json')))
    write_json(child/'plan.json', plan); bind_plan(child)
    write_json(child/'ledger.json', ledger)
    for key, entry in ledger.items():
        if entry['state'] == 'DONE': write_json(child/'responses'/(key+'.json'), entry['result'])
    assert refused(lambda: recovery.validate_recovery(child)), 'Recovery accepted corrupted experiment evidence'


@pytest.mark.parametrize('field,value', [('workers', 2), ('max_requests', 0), ('max_requests', 11),
                                       ('min_request_interval', 0), ('stop_after_errors', 4)])
def test_recovery_pacing_cannot_be_bypassed(tmp_path, monkeypatch, field, value):
    parent, child, keys = fixture(tmp_path); prepare(parent, child)
    args = SimpleNamespace(output=child, live=True, workers=1, max_requests=10,
                           min_request_interval=15, stop_after_errors=3)
    setattr(args, field, value)
    calls = []
    monkeypatch.setattr(executor, 'live_answer', lambda **kw: calls.append(kw))
    assert refused(lambda: executor.execute(args))
    assert not calls


@pytest.mark.parametrize('field,value', [('workers', 2), ('max_requests', 0), ('max_requests', 11),
                                       ('min_request_interval', 0), ('stop_after_errors', 4)])
def test_recovery_execution_bounds_reject_unbounded_calls(field, value):
    args = SimpleNamespace(workers=1, max_requests=10, min_request_interval=15, stop_after_errors=3)
    setattr(args, field, value)
    assert refused(lambda: recovery.require_bounded_execution(args)), 'Unbounded recovery policy accepted'


def test_report_distinguishes_terminal_attempts_from_missing_answers(tmp_path):
    from benchmarks.library_answer_report import report
    tokenizers = pytest.importorskip('tokenizers')
    parent, child, keys = fixture(tmp_path); assets = tmp_path/'assets'; assets.mkdir()
    codec = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    (assets/'tokenizer.json').write_text(codec.to_str())
    (assets/'chat_template.jinja').write_text('{{ messages }}')
    plan = recovery.read(parent/'plan.json')
    plan['tokenizer_assets']['files'] = {p.name: {'sha256': sha(p.read_bytes())} for p in assets.iterdir()}
    write_json(parent/'plan.json', plan); bind_plan(parent); prepare(parent, child)
    ledger = recovery.read(child/'ledger.json')
    for key in keys[1:3]:
        result = recovery.read(parent/'responses'/(key+'.json'))
        ledger[key] = {'state': 'DONE', 'result': result}  # Synthetic repeated terminal failures.
        write_json(child/'responses'/(key+'.json'), result)
    write_json(child/'ledger.json', ledger)
    output = tmp_path/'report.json'; report(SimpleNamespace(run=child, assets=assets, output=output))
    result = recovery.read(output)
    assert result['attempt_stage_complete'] is True and result['answer_stage_complete'] is False
    assert result['summaries'][0]['accuracy'] is None
    assert result['transport_recovery']['cumulative_api_attempts'] == 5
    assert result['transport_recovery']['unanswered_payloads'] == 2

"""LOCAL synthetic controls: evidence completeness and experiment tamper checks."""
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

from benchmarks import complete_program_controls as module
from benchmarks import prospective_eval as executor
from benchmarks.answer_records import sha
from benchmarks.prospective_eval import write_json


SOURCE = {'jinja2/filters.py': '''def do_int(value, default=0, base=10):
    try:
        return int(value, base) if isinstance(value, str) else int(value)
    except (ValueError, TypeError):
        try:
            return int(float(value))
        except (ValueError, TypeError, OverflowError):
            return default
''', 'werkzeug/utils.py': '''_charset_mimetypes = {"application/sql"}
def get_content_type(mimetype, charset):
    if mimetype.startswith("text/") or mimetype in _charset_mimetypes or mimetype.endswith("+xml"):
        mimetype += "; charset=" + charset
    return mimetype
'''}


def refused(call):
    try: call()
    except ValueError: return True
    return False


def trial(tmp_path, monkeypatch):
    parent = tmp_path/'parent'; parent.mkdir(); assets = tmp_path/'assets'; assets.mkdir()
    for name, text in SOURCE.items():
        p = parent/'source'/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(text.encode())
    plan = {'source_manifest': {name: sha(text.encode()) for name, text in SOURCE.items()},
            'tokenizer_assets': {'files': {}},
            'settings': {'model': 'synthetic-target', 'temperature': 1, 'timeout_seconds': 10}}
    write_json(parent/'plan.json', plan); (parent/'plan.sha256').write_text(sha((parent/'plan.json').read_bytes()))
    monkeypatch.setattr(module, 'counters', lambda *a: (len, lambda q, c: len(q+c)))
    return SimpleNamespace(parent=parent, assets=assets, output=tmp_path/'study', python=[Path(sys.executable)])


def test_complete_programs_execute_with_all_initialization_and_class_only_errors():
    programs = module.programs(SOURCE)
    expected = {'public_integer': [12, 7, 5, 12, 7],
                'public_mime': ['application/json', 'application/sql; charset=utf-8',
                                'image/svg+xml; charset=utf-8', 'text/plain; charset=utf-8', 'image/png'],
                'default_capture': [3, 19], 'conditional_binding': [7, True],
                'transitive_initializer': [7, 99, 7, 14], 'closure_binding': [[8, 8, 8], [0, 1, 2]],
                'exception_class_only': [2, 'StopIteration', 'TypeError'], 'constraint_and_collision': [0, 4, 9]}
    actual = {name: module.run_program(fixture['program'], Path(sys.executable))[0] for name, fixture in programs.items()}
    assert actual == expected


def test_complete_oracle_refuses_missing_global_instead_of_creating_an_answer():
    broken = module.programs(SOURCE)['default_capture']['program'].replace('CONFIG = 3\n', '')
    assert refused(lambda: module.run_program(broken, Path(sys.executable))), 'Incomplete source labeled executable'


@pytest.mark.parametrize('output', ['print("not-json")', 'print("{} {}")', 'print("{\\\"x\\\":1,\\\"x\\\":2}")'])
def test_program_oracle_rejects_ambiguous_output(output):
    assert refused(lambda: module.run_program(output, Path(sys.executable)))


def test_complete_study_is_paired_without_model_calls_or_empty_context(tmp_path, monkeypatch):
    args = trial(tmp_path, monkeypatch); module.prepare(args)
    meta, plans, accounts = module.validate(args.output)
    assert all(a['attempts'] == 0 for a in accounts.values())
    a, b = [plans[arm] for arm in module.ARMS]
    assert a['settings'] == {**b['settings'], 'chat_template_kwargs': {'enable_thinking': False, 'low_effort': True}}
    assert a['dataset'] == b['dataset'] and len(a['requests']) == len(b['requests']) == 8
    assert not set(a['requests']) & set(b['requests'])
    for row in a['observations']:
        assert row['available_tokens'] == row['corpus_tokens'] == row['selected_tokens'] > 0
        assert row['baseline_prompt_tokens'] == row['selected_prompt_tokens']
    result = module.report(args.output)
    assert result['pairs']['missing'] and not result['pairs']['wins']
    assert all(s['accuracy'] is None for s in result['summaries'].values())
    assert len(meta['dataset']['tasks']) == 8


@pytest.mark.parametrize('attack', ['query', 'answer', 'system', 'output_cap', 'thinking', 'context', 'source',
                                    'tokens', 'available', 'budget', 'drop', 'duplicate', 'unknown', 'orphan',
                                    'boolean_answer_as_number', 'fractional_token_type'])
def test_complete_study_rejects_tampering_before_execution(tmp_path, monkeypatch, attack):
    args = trial(tmp_path, monkeypatch); module.prepare(args); run = args.output/'direct'
    plan = module.read(run/'plan.json'); row = plan['observations'][0]
    if attack == 'query': plan['dataset']['tasks'][0]['question'] += ' changed'
    elif attack == 'answer': plan['dataset']['tasks'][0]['answer'] = 'invented'
    elif attack == 'boolean_answer_as_number':
        task = next(t for t in plan['dataset']['tasks'] if t['id'] == 'conditional_binding')
        task['answer'] = [7, 1]
    elif attack == 'fractional_token_type': row['selected_tokens'] = float(row['selected_tokens'])
    elif attack == 'system': plan['settings']['system_prompt'] = 'changed'
    elif attack == 'output_cap': plan['settings']['max_output_tokens'] = 16384
    elif attack == 'thinking': plan['settings']['chat_template_kwargs']['enable_thinking'] = True
    elif attack == 'context': (run/'contexts'/(row['context_sha256']+'.txt')).write_text('')
    elif attack == 'source': (args.output/'source/jinja2/filters.py').write_text('def do_int(): return 0')
    elif attack == 'tokens': row['selected_tokens'] = 0
    elif attack == 'available': row['available_tokens'] = 500000
    elif attack == 'budget': row['budget'] = 1
    elif attack == 'drop': plan['observations'].pop()
    elif attack == 'duplicate': plan['observations'].append(row)
    elif attack == 'unknown': write_json(run/'ledger.json', {row['request_sha256']: {'state': 'STARTED'}})
    elif attack == 'orphan':
        (run/'responses').mkdir(); write_json(run/'responses'/(row['request_sha256']+'.json'), {})
    write_json(run/'plan.json', plan); (run/'plan.sha256').write_text(sha((run/'plan.json').read_bytes()))
    assert refused(lambda: module.validate(args.output)), 'Altered paired study accepted'


def test_executor_checks_complete_program_study_before_target_call(tmp_path, monkeypatch):
    args = trial(tmp_path, monkeypatch); module.prepare(args); run = args.output/'direct'
    plan = module.read(run/'plan.json'); row = plan['observations'][0]
    row['available_tokens'] = 999999
    write_json(run/'plan.json', plan); (run/'plan.sha256').write_text(sha((run/'plan.json').read_bytes()))
    called = []
    monkeypatch.setattr(executor, 'live_answer', lambda **kw: called.append(kw))
    attempt = SimpleNamespace(output=run, live=True, workers=1, max_requests=1,
                              min_request_interval=15, stop_after_errors=3)
    assert refused(lambda: executor.execute(attempt)) and not called

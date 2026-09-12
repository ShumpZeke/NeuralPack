"""Reference-arm source and trial integrity tests; synthetic, no network."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from benchmarks import reference_evidence as module
from benchmarks import prospective_eval as executor
from benchmarks.answer_records import sha
from benchmarks.prospective_eval import write_json


def refused(call):
    try: call()
    except ValueError: return True
    return False


def test_module_bindings_respect_local_shadowing_and_import_aliases():
    source = {'a.py': 'import math as m\nTABLE = {"x": 3}\nLOCAL = 99\n'
              'def f(LOCAL):\n    def nested():\n        return TABLE["x"]\n'
              '    return m.floor(LOCAL) + nested()\n'}
    primary, _ = module.source_segments(source, [('a.py', 'f')])
    expanded, meta = module.source_segments(source, [('a.py', 'f')], bindings=True)
    assert 'TABLE =' not in module.render(primary)
    assert 'TABLE =' in module.render(expanded) and 'import math as m' in module.render(expanded)
    assert 'LOCAL = 99' not in module.render(expanded), 'A shadowed global was selected as a dependency'
    assert meta[0]['included_direct_bindings'] == ['TABLE', 'm']


def test_overload_stubs_require_an_explicit_definition_line():
    text = 'from typing import overload\n@overload\ndef f(x: int): ...\n' \
           '@overload\ndef f(x: str): ...\ndef f(x):\n    return x + 1\n'
    source = {'a.py': text}
    assert refused(lambda: module.source_segments(source, [('a.py', 'f')])), 'Ambiguous overload accepted'
    pieces, _ = module.source_segments(source, [('a.py', 'f', 6)])
    assert 'return x + 1' in module.render(pieces) and '@overload' not in module.render(pieces)
    assert refused(lambda: module.source_segments(source, [('a.py', 'f', 500)]))


def test_reference_source_preserves_physical_lines_and_unicode():
    text = 'PREFIX = "line\u2028separator"\r\n\r\n@staticmethod\r\ndef f():\r\n    return "界\u2028界"\r\n'
    pieces, _ = module.source_segments({'a.py': text}, [('a.py', 'f')])
    assert pieces[0]['start_line'] == 3 and pieces[0]['end_line'] == 5
    assert pieces[0]['text'] == '\n'.join(text.split('\n')[2:5])
    assert '\u2028' in pieces[0]['text'] and '\r\n' in pieces[0]['text']
    assert pieces[0]['text_sha256'] == sha(pieces[0]['text'].encode())


def test_dynamic_initializers_are_source_data_and_never_executed(tmp_path):
    target = tmp_path/'must-not-exist'
    source = {'a.py': f'TABLE = __import__("pathlib").Path({str(target)!r}).write_text("executed")\n'
                      'def f():\n    return TABLE\n'}
    pieces, _ = module.source_segments(source, [('a.py', 'f')], bindings=True)
    assert '__import__' in module.render(pieces)
    assert not target.exists(), 'Reference preparation executed source code'


def test_reference_budget_counts_headers_and_the_whole_join():
    source = {'a.py': 'def f():\n    return 1\n'}; seen = []
    count = lambda text: (seen.append(text) or len(text))
    text = module.render(module.source_segments(source, [('a.py', 'f')])[0])
    assert refused(lambda: module.bounded_reference(source, [('a.py', 'f')], False, count, len(text)-1))
    assert seen == [text], 'Budget omitted headers or counted incompatible fragments'
    result = module.bounded_reference(source, [('a.py', 'f')], False, count, len(text))
    assert result[0] == text and result[1] == len(text)


@pytest.mark.parametrize('seeds', [[], [('a.py', 'missing')]])
def test_reference_empty_or_failed_seed_is_not_a_success(seeds):
    assert refused(lambda: module.source_segments({'a.py': 'def f(): return 1'}, seeds))


def trial(tmp_path, monkeypatch):
    tokenizers = pytest.importorskip('tokenizers')
    parent = tmp_path/'parent'; source = tmp_path/'source'; assets = tmp_path/'assets'
    for p in (parent, source, assets): p.mkdir()
    (source/'a.py').write_text('TABLE = {"x": 3}\ndef f():\n    return TABLE["x"]\n')
    codec = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    (assets/'tokenizer.json').write_text(codec.to_str())
    (assets/'chat_template.jinja').write_text('{{ messages }}')
    plan = {'settings': {'model': 'synthetic/model', 'system_prompt': 'Original system',
                        'chat_template_kwargs': {'enable_thinking': False}, 'max_output_tokens': 16},
            'dataset': {'tasks': [{'id': 'example', 'question': 'Original query\n  spacing', 'answer': {'v': 3}}]},
            'tokenizer_assets': {'files': {p.name: {'sha256': sha(p.read_bytes())} for p in assets.iterdir()}},
            'source_manifest': {'a.py': sha((source/'a.py').read_bytes())},
            'corpus_tokens': 1, 'available_tokens': 1,
            'requests': {}, 'observations': [{'task': 'example', 'baseline_prompt_tokens': 1}]}
    write_json(parent/'plan.json', plan)
    digest = sha((parent/'plan.json').read_bytes()); (parent/'plan.sha256').write_text(digest)
    monkeypatch.setattr(module, 'SEEDS', {'example': [['a.py', 'f']]})
    args = SimpleNamespace(parent=parent, source=source, assets=assets, output=tmp_path/'run', expected_parent=digest)
    return args


def test_reference_prepare_and_report_use_no_optimizer_model(tmp_path, monkeypatch):
    args = trial(tmp_path, monkeypatch)
    def denied(*a, **kw): raise AssertionError('Reference preparation used network')
    monkeypatch.setattr('urllib.request.urlopen', denied)
    module.prepare(args); result = module.validate_reference(args.output)
    assert result['observations'] == 2 and result['unique_payloads'] == 2
    plan = module.read(args.output/'plan.json')
    assert all(r['question'] == 'Original query\n  spacing' for r in plan['requests'].values())
    assert plan['settings']['system_prompt'] == 'Original system'
    assert plan['generative_optimization_calls'] == 0
    write_json(args.output/'ledger.json', {})
    from benchmarks.library_answer_report import report
    output = tmp_path/'report.json'
    report(SimpleNamespace(run=args.output, assets=args.assets, output=output))
    data = module.read(output)
    assert len(data['pairs']) == 2 and all(r['baseline'] == module.ARMS[0] for r in data['pairs'])
    assert all(r['accuracy'] is None for r in data['summaries'])


@pytest.mark.parametrize('attack', ['source', 'context', 'tokens', 'span', 'settings', 'answer', 'drop_cell',
                                   'extra_request', 'unknown_attempt', 'orphan_response'])
def test_reference_validator_rejects_changed_evidence_or_experiment(tmp_path, monkeypatch, attack):
    args = trial(tmp_path, monkeypatch); module.prepare(args); root = args.output
    plan = module.read(root/'plan.json'); row = plan['observations'][0]
    if attack == 'source': (root/'source/a.py').write_text('def f(): return 99')
    elif attack == 'context': (root/'contexts'/(row['context_sha256']+'.txt')).write_text('Changed')
    elif attack == 'tokens': row['selected_tokens'] = 0
    elif attack == 'span': row['segments'][0]['start_line'] += 1
    elif attack == 'settings': plan['settings']['system_prompt'] = 'Changed'
    elif attack == 'answer': plan['dataset']['tasks'][0]['answer'] = {'v': 99}
    elif attack == 'drop_cell': plan['observations'].pop()
    elif attack == 'extra_request': plan['requests']['foreign'] = {'question': 'new', 'context_sha256': '0'*64}
    elif attack == 'unknown_attempt': write_json(root/'ledger.json', {row['request_sha256']: {'state': 'STARTED'}})
    else:
        (root/'responses').mkdir(); write_json(root/'responses'/(row['request_sha256']+'.json'), {})
    write_json(root/'plan.json', plan); (root/'plan.sha256').write_text(sha((root/'plan.json').read_bytes()))
    assert refused(lambda: module.validate_reference(root)), 'Corrupted reference experiment accepted'


def test_executor_checks_reference_before_any_call(tmp_path, monkeypatch):
    args = trial(tmp_path, monkeypatch); module.prepare(args)
    (args.output/'source/a.py').write_text('def f(): return 99')
    called = []
    monkeypatch.setattr(executor, 'live_answer', lambda **kw: called.append(kw))
    attempt = SimpleNamespace(output=args.output, live=True, workers=1, max_requests=1,
                              min_request_interval=15, stop_after_errors=3)
    assert refused(lambda: executor.execute(attempt)) and not called

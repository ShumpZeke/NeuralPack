"""A report must bind counts and the ledger digest to the same snapshot."""
import json
from types import SimpleNamespace
import pytest
from benchmarks import library_answer_report as module


def empty_local_plan(tmp_path):
    tokenizers = pytest.importorskip('tokenizers')
    run = tmp_path/'run'; assets = tmp_path/'assets'; run.mkdir(); assets.mkdir()
    codec = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    (assets/'tokenizer.json').write_text(codec.to_str(), encoding='utf-8')
    (assets/'chat_template.jinja').write_text('{{ messages }}', encoding='utf-8')
    plan = {'settings': {'chat_template_kwargs': {}}, 'requests': {}, 'observations': [],
            'dataset': {'tasks': []}, 'corpus_tokens': 0,
            'tokenizer_assets': {'files': {p.name: {'sha256': module.sha(p.read_bytes())} for p in assets.iterdir()}}}
    (run/'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    (run/'plan.sha256').write_text(module.sha((run/'plan.json').read_bytes()))
    (run/'ledger.json').write_text('{}', encoding='utf-8')
    return SimpleNamespace(run=run, assets=assets, output=tmp_path/'report.json')


def test_changed_ledger_cannot_mix_old_counts_with_a_new_digest(tmp_path, monkeypatch):
    args = empty_local_plan(tmp_path); original = module.counts
    def concurrent_writer(ledger):
        (args.run/'ledger.json').write_text('{"new":{"state":"STARTED"}}', encoding='utf-8')
        return original(ledger)
    monkeypatch.setattr(module, 'counts', concurrent_writer)
    refused = False
    try:
        module.report(args)
    except AssertionError as error:
        assert 'ledger changed' in str(error)
        refused = True
    assert refused, 'report accepted a ledger that changed during its audit'
    assert not args.output.exists()


def test_quiescent_empty_diagnostic_uses_the_exact_captured_ledger(tmp_path):
    args = empty_local_plan(tmp_path); captured = (args.run/'ledger.json').read_bytes()
    module.report(args)
    result = json.loads(args.output.read_text())
    assert result['ledger_sha256'] == module.sha(captured)
    assert result['accounting']['attempts'] == 0 and result['rows'] == []
    assert (args.run/'report-ledgers'/(module.sha(captured)+'.json')).read_bytes() == captured

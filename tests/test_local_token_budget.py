"""Actual local-token caps, including tokenizer-state and final-edit attacks."""
import builtins
import json
from types import SimpleNamespace

import pytest

from npk.pack import LocalTokenizer, PackSelector, compile_pack, update_pack
from npk.pack.format import PackError
from npk.pack.select import Evidence, Selection


def tokenizer_asset(tmp_path, *, truncation=None, padding=False):
    tokenizers = pytest.importorskip('tokenizers')
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0, 'needle': 1}, unk_token='[UNK]'))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    if truncation: backend.enable_truncation(truncation)
    if padding: backend.enable_padding(length=100, pad_id=0, pad_token='[UNK]')
    path = tmp_path/'tokenizer.json'
    backend.save(str(path))
    return path


def pack(tmp_path, sources):
    source = tmp_path/'source'; source.mkdir()
    for name, text in sources.items(): (source/name).write_text(text, encoding='utf-8')
    artifact = tmp_path/'project.npk'; compile_pack(source, artifact)
    return source, artifact


def test_tokenizer_disables_stored_truncation_and_padding(tmp_path):
    path = tokenizer_asset(tmp_path, truncation=2, padding=True)
    before = path.read_bytes(); counter = LocalTokenizer(path)
    assert counter.count('needle '*50) == 50
    assert counter.count('needle') == 1
    assert counter.count('') == 0
    assert path.read_bytes() == before


def test_tokenizer_erasure_is_an_error_not_a_zero_cost_win(tmp_path):
    tokenizers = pytest.importorskip('tokenizers')
    path = tokenizer_asset(tmp_path)
    data = tokenizers.Tokenizer.from_file(str(path))
    data.normalizer = tokenizers.normalizers.Replace(tokenizers.Regex('.+'), '')
    data.save(str(path))
    with pytest.raises(PackError, match='discarded'):
        LocalTokenizer(path).count('required evidence')


def test_bad_tokenizer_data_is_refused_without_echoing_contents(tmp_path):
    path = tmp_path/'bad.json'; path.write_text('private-input-do-not-echo')
    with pytest.raises(PackError) as caught: LocalTokenizer(path)
    assert 'private-input-do-not-echo' not in str(caught.value)


def test_stochastic_bpe_dropout_is_refused(tmp_path):
    tokenizers = pytest.importorskip('tokenizers')
    backend = tokenizers.Tokenizer(tokenizers.models.BPE(
        vocab={'a': 0, 'b': 1, 'ab': 2}, merges=[('a', 'b')], dropout=0.5))
    path = tmp_path/'stochastic.json'; backend.save(str(path))
    refused = False
    try:
        LocalTokenizer(path)
    except PackError:
        refused = True
    assert refused, 'a stochastic tokenizer cannot enforce reproducible caps'


def test_exact_budget_can_admit_a_passage_rejected_by_character_estimates(tmp_path):
    counter = LocalTokenizer(tokenizer_asset(tmp_path))
    text = 'needle '+('longidentifier'*30)
    _, artifact = pack(tmp_path, {'fact.txt':text})
    result = PackSelector(artifact, tokenizer=counter).select('needle', budget_tokens=2)
    assert result.context_text() == text and result.total_tokens == 2
    assert not result.seed_failed


@pytest.mark.parametrize('budget', [1, 2, 3, 7, 13, 31])
def test_actual_budget_survives_selection_and_broadening(tmp_path, budget):
    path = tokenizer_asset(tmp_path)
    _, artifact = pack(tmp_path, {'large.txt': 'needle '+'x '*100,
                                  'small.txt': 'needle y', 'medium.txt': 'needle '+'z '*10})
    counter = LocalTokenizer(path)
    query = '  needle\r\ncurrent question 漢字  '
    result = PackSelector(artifact, tokenizer=counter).select(query, budget_tokens=budget)
    assert result.query == query
    assert counter.count(result.context_text()) == result.total_tokens <= budget
    serialized = result.as_dict()
    assert serialized['available_tokens'] is None
    assert serialized['available_tokens_estimate'] > 0
    assert serialized['reduction_pct'] is None
    assert serialized['tokenizer']['asset_sha256'] == counter.sha256
    assert result.used_generative_llm is False
    if result.evidence:
        assert serialized['sufficiency'] == 'unverified'
    else:
        assert result.seed_failed and serialized['status'] == 'fallback_required'


def test_no_stale_counts_after_incremental_update_or_other_query(tmp_path):
    path = tokenizer_asset(tmp_path); counter = LocalTokenizer(path)
    source, artifact = pack(tmp_path, {'fact.txt': 'needle short'})
    selector = PackSelector(artifact, tokenizer=counter)
    first = selector.select('needle', budget_tokens=4)
    assert first.context_text() == 'needle short'
    assert selector.select('absentidentifier', budget_tokens=4).seed_failed
    (source/'fact.txt').write_text('needle '+'long '*20)
    update_pack(artifact, source)
    assert selector.select('needle', budget_tokens=4).seed_failed
    assert first.context_text() == 'needle short'


def test_dependency_expansion_uses_the_same_actual_budget(tmp_path, monkeypatch):
    path = tokenizer_asset(tmp_path); counter = LocalTokenizer(path)
    _, artifact = pack(tmp_path, {'seed.txt': 'needle found', 'dependency.txt': 'hidden '+'more '*20})
    import importlib
    module = importlib.import_module('npk.pack.select')
    from npk.pack.format import open_pack
    with open_pack(artifact) as con:
        bid = con.execute("SELECT b.id FROM blocks b JOIN files f ON f.id=b.file_id WHERE f.path='dependency.txt'").fetchone()[0]
    monkeypatch.setattr(module, '_expand_dependencies', lambda *args, **kwargs: [bid])
    result = PackSelector(artifact, tokenizer=counter, enable_dependency_expansion=True).select('needle', budget_tokens=4)
    assert result.context_text() == 'needle found'
    assert result.total_tokens == 2
    assert 'expand_dependencies' in result.escalations


def test_final_guard_handles_nonadditive_counts_after_edits(tmp_path):
    counter = LocalTokenizer(tokenizer_asset(tmp_path))
    # Synthetic non-additive codec: removing B can make the joined A/C cost
    # larger. Final reconciliation must check the actual edited bytes.
    prices = {'A': 2, 'A\n\nB\n\nC': 5, 'A\n\nC': 9, '': 0}
    counter._backend = SimpleNamespace(encode=lambda text, **kw: SimpleNamespace(ids=[0]*prices[text]))
    items = [Evidence(i, 'source.py', f'source.py:{i}-{i}', 'chunk', None, 1, value, 1.)
             for i, value in enumerate(('A','C'),1)]
    selection = Selection('question', items, 0, 5, 0, [], [], 'uncalibrated:high', False, 0.)
    selector = PackSelector('unused.npk', tokenizer=counter)
    selector._enforce_final_budget(selection, 5)
    assert selection.context_text() == 'A' and selection.total_tokens == 2
    assert 'removed 1 passage' in selection.notes[0]


def test_exact_cli_is_local_and_reports_the_correct_units(tmp_path, capsys, monkeypatch):
    path = tokenizer_asset(tmp_path, truncation=1)
    _, artifact = pack(tmp_path, {'fact.txt': 'needle '+'x '*50})
    monkeypatch.setattr('socket.socket.connect', lambda *args: pytest.fail('Exact query contacted the network'))
    from npk.cli import main
    assert main(['query', str(artifact), 'needle', '--budget', '4', '--tokenizer-json', str(path), '--show-text']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'fallback_required' and result['total_tokens'] == 0
    assert result['token_accounting'].startswith('exact for supplied')


def test_default_mode_does_not_import_optional_tokenization(tmp_path, monkeypatch):
    _, artifact = pack(tmp_path, {'fact.txt': 'needle found'})
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in ('tokenizers', 'transformers', 'tiktoken'):
            raise AssertionError('default query imported an optional tokenizer')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    result = PackSelector(artifact).select('needle', budget_tokens=50)
    assert result.context_text() == 'needle found'
    assert result.as_dict()['token_accounting'].startswith('estimated')


def test_count_cache_is_bounded_disabled_and_isolated_between_tokenizers(tmp_path):
    path = tokenizer_asset(tmp_path)
    counter = LocalTokenizer(path, cache_bytes=1024)
    assert counter.count('needle one') == counter.count('needle one') == 2
    assert counter.cache_info()['hits'] == 1
    for n in range(1, 50):
        assert counter.count('needle '*n) == n
        assert counter.cache_info()['retained_bytes'] <= 1024
    disabled = LocalTokenizer(path, cache_bytes=0)
    for _ in range(2): assert disabled.count('needle one') == 2
    assert disabled.cache_info()['entries'] == disabled.cache_info()['hits'] == 0
    t = pytest.importorskip('tokenizers')
    other = t.Tokenizer.from_file(str(path))
    other.pre_tokenizer = t.pre_tokenizers.Digits(individual_digits=True)
    other_path = tmp_path/'digits.json'; other.save(str(other_path))
    assert counter.count('123') == 1
    assert LocalTokenizer(other_path).count('123') == 3
    counter.clear_cache()
    assert counter.cache_info()['retained_bytes'] == counter.cache_info()['entries'] == 0


def test_failed_counts_never_enter_the_cache(tmp_path, monkeypatch):
    counter = LocalTokenizer(tokenizer_asset(tmp_path))
    calls = []
    def fail(text):
        calls.append(text)
        raise PackError('synthetic count failure')
    monkeypatch.setattr(counter, '_count_uncached', fail)
    for _ in range(2):
        with pytest.raises(PackError): counter.count('needle')
    assert calls == ['needle', 'needle'] and counter.cache_info()['entries'] == 0


def test_concurrent_queries_do_not_mix_evidence_or_counts(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    counter = LocalTokenizer(tokenizer_asset(tmp_path), cache_bytes=1024)
    _, artifact = pack(tmp_path, {f'file{i}.txt':f'uniqueidentifier{i} '+'word '*i for i in range(1,17)})
    selector = PackSelector(artifact, tokenizer=counter)
    def select(i):
        result = selector.select(f'uniqueidentifier{i}', budget_tokens=32)
        assert result.query == f'uniqueidentifier{i}'
        assert [e.path for e in result.evidence] == [f'file{i}.txt']
        assert result.total_tokens == i+1 and not result.seed_failed
        return result.context_text()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(select, list(range(1,17))*3))
    assert results[:16] == results[16:32] == results[32:]
    assert counter.cache_info()['retained_bytes'] <= 1024


@pytest.mark.parametrize('size', [-1, 1.5, True])
def test_invalid_cache_configuration_is_rejected(tmp_path, size):
    with pytest.raises(ValueError, match='cache_bytes'):
        LocalTokenizer(tokenizer_asset(tmp_path), cache_bytes=size)

"""Real backend metadata and saved-record compatibility, no model download."""
import hashlib
import random
from unittest.mock import patch
import pytest
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount
from benchmarks.lean_boundary_tokenizer import LeanCompactBoundaryCount
from benchmarks.compiled_count_index import load_index
from tests.test_boundary_tokenizer import pipeline
from tests.test_compiled_count_index import inputs, bodies


def repin(codec, path, monkeypatch):
    path.write_text(codec.to_str(), encoding='utf-8')
    monkeypatch.setattr('benchmarks.boundary_tokenizer.PINNED_ASSET', hashlib.sha256(path.read_bytes()).hexdigest())


def test_lean_initializer_avoids_whole_vocab_roundtrip(pipeline, monkeypatch):
    import tokenizers
    import npk.pack.tokenizer as module
    codec, path = pipeline
    original = tokenizers.Tokenizer
    loads = module.json.loads
    calls = {'loads': 0, 'serialize': 0}
    class Backend:
        def __init__(self, inner): self.inner = inner
        def __getattr__(self, name): return getattr(self.inner, name)
        def to_str(self, *args, **kwargs):
            calls['serialize'] += 1
            return self.inner.to_str(*args, **kwargs)
    class Factory:
        @staticmethod
        def from_str(body): return Backend(original.from_str(body))
    def tracked_loads(*args, **kwargs):
        calls['loads'] += 1
        return loads(*args, **kwargs)
    monkeypatch.setattr(tokenizers, 'Tokenizer', Factory)
    monkeypatch.setattr(module.json, 'loads', tracked_loads)
    counter = LeanCompactBoundaryCount(path)
    assert counter.boundary_enabled
    assert calls == {'loads': 1, 'serialize': 0}


@pytest.mark.parametrize('guard', ['normalizer', 'lstrip', 'rstrip', 'normalized', 'single_word', 'lf', 'cr'])
def test_lean_preserves_every_loaded_metadata_guard(pipeline, monkeypatch, guard):
    import tokenizers as t
    codec, path = pipeline
    if guard == 'normalizer': codec.normalizer = t.normalizers.NFKC()
    elif guard in ('lf', 'cr'):
        codec.add_tokens([t.AddedToken('alpha'+ ('\n\n' if guard == 'lf' else '\r') +'beta', normalized=False)])
    else:
        options = dict(normalized=False); options[guard] = True
        codec.add_tokens([t.AddedToken('<fixture>', **options)])
    repin(codec, path, monkeypatch)
    counter = LeanCompactBoundaryCount(path)
    reference = CompactBoundaryCount(path)
    assert counter.boundary_enabled == reference.boundary_enabled == False
    parts = ['alpha', 'beta', 'ａｌｐｈａ <fixture> tail']
    counter.prepare(parts)
    assert counter.count_parts(parts) == len(codec.encode('\n\n'.join(parts), add_special_tokens=False))
    assert counter.fallback_calls == 1


def test_lean_requires_inspected_asset(pipeline, monkeypatch):
    _, path = pipeline
    monkeypatch.setattr('benchmarks.boundary_tokenizer.PINNED_ASSET', '0'*64)
    counter = LeanCompactBoundaryCount(path)
    assert not counter.boundary_enabled


def test_lean_added_token_fallback_and_unicode_join_equivalence(pipeline, monkeypatch):
    import tokenizers as t
    codec, path = pipeline
    codec.add_tokens([t.AddedToken('<fixture>', normalized=False)])
    repin(codec, path, monkeypatch)
    counter = LeanCompactBoundaryCount(path); reference = CompactBoundaryCount(path)
    parts = ['alpha beta gamma', 'first e\u0301界😀 last', '\t\r\n', '<fixture>', 'left middle right']
    counter.prepare(parts); reference.prepare(parts)
    assert counter.boundary_enabled and counter._prepared == reference._prepared
    rng = random.Random(2930)
    for _ in range(100):
        selected = rng.choices(parts, k=rng.randrange(0, 8))
        assert counter.count_parts(selected) == len(codec.encode('\n\n'.join(selected), add_special_tokens=False))
    assert counter.fallback_calls > 0 and counter.boundary_calls > 0


def test_lean_loads_previous_compact_format_without_recompiling(tmp_path, pipeline, monkeypatch):
    codec, asset, _, pack, index, compiled = inputs(tmp_path, pipeline)
    target = LeanCompactBoundaryCount(asset)
    calls = []
    original = target._segment
    def tracked(text): calls.append(text); return original(text)
    monkeypatch.setattr(target, '_segment', tracked)
    with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
        result = load_index(pack, index, target, expected_digest=compiled['receipt_sha256'])
        parts = bodies(pack)
        assert target.count_parts(parts) == len(codec.encode('\n\n'.join(parts), add_special_tokens=False))
    assert calls == [] and result['records_recompiled_for_verification'] == 0


@pytest.mark.parametrize('limit', [-1, True, 1.5])
def test_lean_rejects_invalid_memory_limit(pipeline, limit):
    _, path = pipeline
    with pytest.raises(ValueError): LeanCompactBoundaryCount(path, prepared_bytes=limit)

"""Attack the experimental decomposition with real synthetic BPE pipelines."""
import json
import pytest
from benchmarks.piece_tokenizer import PieceCount


def asset(tmp_path, *, added=False, normalize=False, post=False):
    t = pytest.importorskip('tokenizers')
    codec = t.Tokenizer(t.models.BPE({'a': 0, 'b': 1, 'ab': 2, ' ': 3, '[UNK]': 4},
                                    [('a', 'b')], unk_token='[UNK]'))
    codec.pre_tokenizer = t.pre_tokenizers.WhitespaceSplit()
    if added: codec.add_tokens([t.AddedToken('a b', lstrip=True, rstrip=True)])
    if normalize: codec.normalizer = t.normalizers.NFKC()
    if post: codec.post_processor = t.processors.TemplateProcessing(single='$A', special_tokens=[])
    path = tmp_path/'tokenizer.json'; path.write_text(codec.to_str(), encoding='utf-8')
    return codec, path


def test_reuse_happens_after_join_boundaries_are_recomputed(tmp_path):
    codec, path = asset(tmp_path); counter = PieceCount(path, cache_bytes=0)
    assert counter.count('a') + counter.count('b') == 2
    assert counter.count('ab') == len(codec.encode('ab').ids) == 1
    for text in ('a b', 'ab ab', '\na\t b\n', '界 ab', '', '  '):
        assert counter.differential_ids(text) == codec.encode(text, add_special_tokens=False).ids
        assert counter.count(text) == len(codec.encode(text, add_special_tokens=False).ids)
    assert counter.piece_info()['hits'] > 0


def test_added_token_is_a_counterexample_to_naive_piece_summing(tmp_path):
    codec, path = asset(tmp_path, added=True); text = '  a b  '
    naive = sum(len(codec.model.tokenize(piece)) for piece, _ in codec.pre_tokenizer.pre_tokenize_str(text))
    assert naive == 2 and len(codec.encode(text).ids) == 1
    counter = PieceCount(path)
    assert counter.count(text) == 1 and counter.piece_info()['fallbacks'] == 1
    assert counter.differential_ids(text) == codec.encode(text).ids


@pytest.mark.parametrize('option', ['normalize', 'post'])
def test_unsupported_pipeline_uses_the_regular_encoder(tmp_path, option):
    codec, path = asset(tmp_path, **{option: True}); counter = PieceCount(path)
    assert not counter.piece_enabled
    for text in ('ａｂ', 'ab a', '[UNK]'):
        assert counter.count(text) == len(codec.encode(text, add_special_tokens=False).ids)
    assert counter.piece_info()['fallbacks'] == 3


def test_piece_cache_bound_disable_clear_and_tokenizer_isolation(tmp_path):
    codec, path = asset(tmp_path); small = PieceCount(path, cache_bytes=0, piece_bytes=400)
    off = PieceCount(path, cache_bytes=0, piece_bytes=0)
    config = json.loads(path.read_text()); config['model']['merges'] = []
    changed = tmp_path/'other.json'; changed.write_text(json.dumps(config), encoding='utf-8')
    other = PieceCount(changed)
    assert small.count('ab') == 1 and other.count('ab') == 2
    for text in ('a b ab', 'ab b a', 'a ab b', 'ab ab'):
        assert small.count(text) == off.count(text) == len(codec.encode(text).ids)
        assert small.piece_info()['retained_bytes'] <= 400
    assert off.piece_info()['entries'] == 0
    small.clear_cache(); assert small.piece_info()['retained_bytes'] == small.piece_info()['hits'] == 0

"""Counterexamples to treating every ASCII substring as an isolated word."""
import random
from benchmarks.delimited_boundary_tokenizer import DelimitedBoundaryCount,safe_words
from tests.test_boundary_tokenizer import pipeline


def test_mixed_unicode_interiors_preserve_actual_join_ids(pipeline):
    codec,path=pipeline; counter=DelimitedBoundaryCount(path)
    parts=['first e\u0301界😀 last','first\x00界 é alpha\tlast','AbCd ١Ⅷ² 中 XyZ',
           '界alpha beta界','alpha\u0301 beta\u0301','界1e\u03012界',
           'left [😀,😀] right','Ａ\u200dalpha beta\u2028','', '\r\n','///a b /']
    counter.prepare(parts); prepared=counter.prepared_info()['compiled_parts']
    rng=random.Random(2926)
    for _ in range(400):
        selected=rng.choices(parts,k=rng.randrange(0,8))
        expected=codec.encode('\n\n'.join(selected),add_special_tokens=False).ids
        assert counter.differential_ids(selected)==expected
        assert counter.count_parts(selected)==len(expected)
    assert counter.prepared_info()['compiled_parts']==prepared
    assert counter._prepared['first e\u0301界😀 last'][0].split
    assert len(counter._prepared['first e\u0301界😀 last'][0].ids)>0
    assert not counter._prepared['界alpha beta界'][0].split
    assert not counter._prepared['alpha\u0301 beta\u0301'][0].split


def test_adjacent_unicode_cannot_implicitly_widen_word_barrier_scope():
    text='界alpha beta界 gamma\u0301 \u0301delta aZ1 bY_ ABCdefG élast endé'
    assert [word.group() for word in safe_words(text)]==['aZ','bY','ABCdefG']

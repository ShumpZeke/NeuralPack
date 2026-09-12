"""Barrier attacks with a real tiny vocabulary, not a mock token counter."""
import random
from benchmarks.digit_boundary_tokenizer import DigitBoundaryCount
from tests.test_boundary_tokenizer import pipeline


def test_digit_boundaries_preserve_actual_joined_token_ids(pipeline):
    codec,path=pipeline; counter=DigitBoundaryCount(path)
    parts=['alpha 1 beta 2 gamma','/1\n\n///2','1\n','\n2',
           '界1 e\u0301 2界','1\x00 2','12','(a)1b2(c)','9  0',
           'no digits here','one 1 only','Ａ١Ⅷ²','\r\n','', ' ']
    counter.prepare(parts); prepared=counter.prepared_info()['compiled_parts']
    rng=random.Random(2924)
    for _ in range(240):
        selected=rng.choices(parts,k=rng.randrange(0,8))
        expected=codec.encode('\n\n'.join(selected),add_special_tokens=False).ids
        assert counter.differential_ids(selected)==expected
        assert counter.count_parts(selected)==len(expected)
    assert counter.prepared_info()['compiled_parts']==prepared
    assert not counter._prepared['no digits here'][0].split
    assert not counter._prepared['one 1 only'][0].split
    assert not counter._prepared['Ａ١Ⅷ²'][0].split
    assert counter._prepared['alpha 1 beta 2 gamma'][0].split


def test_non_digit_asset_cannot_activate_barrier_optimization(pipeline,monkeypatch):
    codec,path=pipeline
    # A generic digit-grouping BPE may merge 12 across this proposed cut.
    import tokenizers
    codec.pre_tokenizer=tokenizers.pre_tokenizers.WhitespaceSplit()
    path.write_text(codec.to_str(),encoding='utf-8')
    counter=DigitBoundaryCount(path); counter.prepare(['alpha 123 beta 456'])
    assert not counter.boundary_enabled
    assert counter.count_parts(['alpha 123 beta 456'])==len(codec.encode('alpha 123 beta 456').ids)
    assert counter.prepared_info()['fallback_calls']==1

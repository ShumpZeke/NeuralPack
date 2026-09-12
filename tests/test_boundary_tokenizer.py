"""Real tiny BPE join attacks; fixture hash opt-in is test-only."""
import hashlib
import random
import pytest
from benchmarks.boundary_tokenizer import BoundaryCount


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    t=pytest.importorskip('tokenizers')
    # Same pre-tokenizer expression as the pinned research asset. A tiny trained
    # byte vocabulary makes these tests independent of downloaded artifacts.
    pattern=(r'[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+'
             r'|[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*'
             r'|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n/]*|\s*[\r\n]+|\s+(?!\S)|\s+')
    codec=t.Tokenizer(t.models.BPE())
    codec.pre_tokenizer=t.pre_tokenizers.Sequence([
        t.pre_tokenizers.Split(t.Regex(pattern),behavior='isolated'),
        t.pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False)])
    codec.train_from_iterator(['alpha beta gamma /\n\n///delta epsilon', 'a\n\n\n\nb c\r\n  d',
                               'red green blue', 'A1BC23', '界 界 e\u0301', '    x y z']*20,
                              trainer=t.trainers.BpeTrainer(vocab_size=320,show_progress=False,
                                  initial_alphabet=t.pre_tokenizers.ByteLevel.alphabet()))
    path=tmp_path/'tiny.json'; path.write_text(codec.to_str(),encoding='utf-8')
    monkeypatch.setattr('benchmarks.boundary_tokenizer.PINNED_ASSET',hashlib.sha256(path.read_bytes()).hexdigest())
    return codec,path


def test_prepared_interiors_preserve_join_ids_and_counts(pipeline):
    codec,path=pipeline; counter=BoundaryCount(path)
    parts=['alpha beta gamma /','///delta epsilon','red green blue','a\n\n\nb c',
           '界 界 e\u0301','A1BC23','\n\r \t','','(a)\n'*8]
    counter.prepare(parts); compiled=counter.prepared_info()['compiled_parts']
    rng=random.Random(2821)
    for _ in range(120):
        selected=rng.choices(parts,k=rng.randrange(0,7)); text='\n\n'.join(selected)
        expected=codec.encode(text,add_special_tokens=False).ids
        assert counter.differential_ids(selected)==expected
        assert counter.count_parts(selected)==len(expected)
    assert counter.prepared_info()['compiled_parts']==compiled
    assert counter.prepared_info()['boundary_calls']>0
    assert counter.prepared_info()['fallback_calls']==0


def test_unprepared_or_evicted_parts_use_full_encoder_without_compilation(pipeline):
    codec,path=pipeline; counter=BoundaryCount(path,prepared_bytes=750)
    counter.prepare(['alpha beta gamma','red green blue','delta epsilon zeta'])
    before=counter.prepared_info()['compiled_parts']
    parts=['unknown longer text','alpha beta gamma']
    assert counter.count_parts(parts)==len(codec.encode('\n\n'.join(parts)).ids)
    info=counter.prepared_info()
    assert info['compiled_parts']==before and info['fallback_calls']==1
    assert info['accounted_retained_bytes']<=info['max_bytes']==750


def test_unsupported_asset_cannot_use_prepared_boundaries(pipeline,monkeypatch):
    codec,path=pipeline
    monkeypatch.setattr('benchmarks.boundary_tokenizer.PINNED_ASSET','0'*64)
    counter=BoundaryCount(path); counter.prepare(['alpha beta gamma'])
    assert not counter.boundary_enabled
    assert counter.count_parts(['alpha beta gamma'])==len(codec.encode('alpha beta gamma').ids)
    assert counter.prepared_info()['fallback_calls']==1


def test_cross_separator_added_token_disables_boundary_hypothesis(pipeline,monkeypatch):
    codec,path=pipeline
    codec.add_tokens(['alpha\n\nbeta']); path.write_text(codec.to_str(),encoding='utf-8')
    monkeypatch.setattr('benchmarks.boundary_tokenizer.PINNED_ASSET',hashlib.sha256(path.read_bytes()).hexdigest())
    counter=BoundaryCount(path); counter.prepare(['alpha','beta'])
    assert not counter.boundary_enabled
    assert counter.count_parts(['alpha','beta'])==1


@pytest.mark.parametrize('parts',['abc',[None],[1],None])
def test_invalid_parts_rejected(pipeline,parts):
    _,path=pipeline; counter=BoundaryCount(path)
    with pytest.raises(TypeError): counter.prepare(parts)
    with pytest.raises(TypeError): counter.count_parts(parts)


def test_verified_partition_preserves_upstream_counts(pipeline):
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    codec,path=pipeline; counter=VerifiedBoundaryCount(path)
    parts=['alpha beta gamma /','///delta epsilon','red green blue','a\n\n\nb c','界 界 e\u0301','','\t\n']
    counter.prepare(parts); compiled=counter.prepared_info()['compiled_parts']
    rng=random.Random(2822)
    for _ in range(100):
        selected=rng.choices(parts,k=rng.randrange(0,7)); text='\n\n'.join(selected)
        expected=codec.encode(text,add_special_tokens=False).ids
        assert counter.differential_ids(selected)==expected
        assert counter.count_parts(selected)==len(expected)
    assert counter.prepared_info()['compiled_parts']==compiled
    assert counter.prepared_info()['verified_calls']>0


def test_wrong_proposed_partition_triggers_upstream_fallback(pipeline):
    from dataclasses import replace
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    codec,path=pipeline; counter=VerifiedBoundaryCount(path)
    text='alpha beta gamma'; counter.prepare([text])
    rec,size=counter._prepared[text]; assert rec.split and rec.pieces
    counter._prepared[text]=(replace(rec,pieces=('deliberately-invalid-piece',),tokens=999),size)
    assert counter.count_parts([text])==len(codec.encode(text).ids)
    assert counter.prepared_info()['gate_rejections']==counter.prepared_info()['fallback_calls']==1


def test_verified_counter_catches_added_token_across_the_join(pipeline):
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    codec,path=pipeline; codec.add_tokens(['alpha\n\nbeta'])
    path.write_text(codec.to_str(),encoding='utf-8')
    counter=VerifiedBoundaryCount(path); counter.prepare(['alpha','beta'])
    assert counter.verified_enabled
    assert counter.count_parts(['alpha','beta'])==1
    assert counter.prepared_info()['fallback_calls']==1


def test_verified_counter_never_compiles_missing_query_parts(pipeline):
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    codec,path=pipeline; counter=VerifiedBoundaryCount(path,prepared_bytes=700)
    counter.prepare(['alpha beta gamma','red green blue'])
    before=counter.prepared_info()['compiled_parts']
    assert counter.count_parts(['unprepared input'])==len(codec.encode('unprepared input').ids)
    info=counter.prepared_info()
    assert info['compiled_parts']==before and info['fallback_calls']==1
    assert info['accounted_retained_bytes']<=700


def test_verified_counter_unsupported_normalizer_uses_upstream(pipeline):
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    import tokenizers
    codec,path=pipeline; codec.normalizer=tokenizers.normalizers.NFKC()
    path.write_text(codec.to_str(),encoding='utf-8')
    counter=VerifiedBoundaryCount(path); counter.prepare(['ａｌｐｈａ beta gamma'])
    assert not counter.verified_enabled
    assert counter.count_parts(['ａｌｐｈａ beta gamma'])==len(codec.encode('ａｌｐｈａ beta gamma').ids)
    assert counter.prepared_info()['fallback_calls']==1


def test_verified_counter_cannot_discard_all_nonempty_input(tmp_path):
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    from npk.pack import LocalTokenizer
    from npk.pack.format import PackError
    t=pytest.importorskip('tokenizers')
    codec=t.Tokenizer(t.models.BPE({'a':0},[]))
    codec.pre_tokenizer=t.pre_tokenizers.WhitespaceSplit()
    path=tmp_path/'incomplete-vocabulary.json'; path.write_text(codec.to_str(),encoding='utf-8')
    assert codec.encode('z').ids==[]
    with pytest.raises(PackError): LocalTokenizer(path).count('z')
    counter=VerifiedBoundaryCount(path); counter.prepare(['z'])
    refused = False
    try:
        counter.count_parts(['z'])
    except PackError:
        refused = True
    assert refused, 'A nonempty input discarded by the vocabulary must be rejected'


def test_unencodable_boundary_rejects_preparation_but_preserves_full_count(tmp_path):
    from benchmarks.verified_boundary_tokenizer import VerifiedBoundaryCount
    t=pytest.importorskip('tokenizers')
    codec=t.Tokenizer(t.models.BPE({'a':0},[]))
    codec.pre_tokenizer=t.pre_tokenizers.Split('',behavior='isolated')
    path=tmp_path/'partial-vocabulary.json'; path.write_text(codec.to_str(),encoding='utf-8')
    assert codec.encode('zaz').ids==[0]
    counter=VerifiedBoundaryCount(path); counter.prepare(['zaz'])
    assert counter.count_parts(['zaz'])==1
    assert counter.prepared_info()['compile_rejections']==1
    assert counter.prepared_info()['fallback_calls']==1

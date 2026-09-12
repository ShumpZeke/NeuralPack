"""Counterexamples for the bounded exact-cache and additive challenger."""
import pytest
from benchmarks.local_budget_eval import CachedTokenizer


def asset(tmp_path):
    t=pytest.importorskip('tokenizers')
    b=t.Tokenizer(t.models.WordLevel({'[UNK]':0},unk_token='[UNK]'))
    b.pre_tokenizer=t.pre_tokenizers.Whitespace()
    p=tmp_path/'tokenizer.json';b.save(str(p));return p


def test_cache_keeps_literal_keys_bounded_and_separate_between_codecs(tmp_path):
    a=CachedTokenizer(asset(tmp_path),max_bytes=1000,max_entries=2)
    assert a.count('one two')==2 and a.count('one two')==2
    assert (a.hits,a.misses)==(1,1)
    for text in ('other','new','long '*1000,'漢字','last'):
        a.count(text)
        assert a.retained_bytes<=a.max_bytes and len(a.cache)<=2
    assert 'long '*1000 not in a.cache
    b=CachedTokenizer(tmp_path/'tokenizer.json')
    assert not b.cache and b.hits==0
    a.clear();assert not a.cache and a.retained_bytes==0


def test_cache_does_not_swallow_failed_counts(tmp_path,monkeypatch):
    a=CachedTokenizer(asset(tmp_path))
    from npk.pack.tokenizer import LocalTokenizer
    def fail(self,text):raise ValueError('synthetic count failure')
    monkeypatch.setattr(LocalTokenizer,'count',fail)
    with pytest.raises(ValueError,match='synthetic'):a.count('text')
    assert not a.cache


def test_additive_cost_can_discard_a_passage_that_fits_exactly(tmp_path,monkeypatch):
    import importlib
    from npk.pack import LocalTokenizer,PackSelector,compile_pack
    from npk.pack.format import open_pack
    from benchmarks.local_budget_eval import AdditiveSelector
    t=pytest.importorskip('tokenizers')
    pre=t.pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False)
    newline=pre.pre_tokenize_str('\n')[0][0]
    # Synthetic real BPE codec: a + two newlines becomes one token. Summing
    # a, the separator and b separately costs 3; the complete text costs 2.
    backend=t.Tokenizer(t.models.BPE(vocab={'a':0,'b':1,newline:2,newline*2:3,'a'+newline*2:4},
                                    merges=[(newline,newline),('a',newline*2)]))
    backend.pre_tokenizer=pre
    path=tmp_path/'boundary.json';backend.save(str(path));counter=LocalTokenizer(path)
    source=tmp_path/'source';source.mkdir()
    (source/'a.txt').write_text('a');(source/'b.txt').write_text('b')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    with open_pack(pack) as con:
        ids=[r[0] for r in con.execute('SELECT b.id FROM blocks b JOIN files f ON f.id=b.file_id ORDER BY f.path')]
    monkeypatch.setattr(importlib.import_module('npk.pack.select'),'_lexical_channel',lambda *args:ids)
    exact=PackSelector(pack,tokenizer=counter).select('fixed candidate ranking',budget_tokens=2)
    approximate=AdditiveSelector(pack,tokenizer=counter).select('fixed candidate ranking',budget_tokens=2)
    assert counter.count('a')+counter.count('\n\n')+counter.count('b')==3
    assert exact.context_text()=='a\n\nb' and exact.total_tokens==2
    assert approximate.context_text()=='a'

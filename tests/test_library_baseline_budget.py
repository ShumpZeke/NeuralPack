"""A competing baseline gets the same exact budget contract as the product."""
import pytest
pytest.importorskip('tokenizers')
from tokenizers import Tokenizer,models,pre_tokenizers
from benchmarks.library_crisp_baseline import exact_rank_pack,enforce_cap


def count_words():
    codec=Tokenizer(models.WordLevel({'[UNK]':0,'alpha':1,'beta':2,'gamma':3},unk_token='[UNK]'))
    codec.pre_tokenizer=pre_tokenizers.Whitespace()
    return lambda text:len(codec.encode(text,add_special_tokens=False).ids)


def test_guard_drops_lowest_relevance_not_last_source_path():
    items=[{'block_id':1,'text':'alpha','relevance':.9},
           {'block_id':2,'text':'beta','relevance':.1},
           {'block_id':3,'text':'gamma','relevance':.8}]
    kept,dropped=enforce_cap(items,2,count_words())
    assert [r['block_id'] for r in kept]==[1,3] and dropped==[2]
    assert len(items)==3


def test_oversized_view_leaves_an_explicit_empty_result():
    items=[{'block_id':1,'text':'alpha beta gamma','relevance':.9}]
    assert enforce_cap(items,2,count_words())==([],[1])
    assert exact_rank_pack(items,2,count_words())==[]


def test_rank_packing_uses_complete_join_not_additive_fragment_cost():
    codec=Tokenizer(models.BPE({'a':0,'\n':1,'b':2,'a\n':3,'a\n\n':4},
                               [('a','\n'),('a\n','\n')]))
    count=lambda text:len(codec.encode(text,add_special_tokens=False).ids)
    assert count('a')+count('\n\n')+count('b')>count('a\n\nb')==2
    items=[{'text':'a'},{'text':'b'}]
    assert exact_rank_pack(items,2,count)==items

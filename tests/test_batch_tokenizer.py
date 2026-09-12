"""Speculative counts must not become stale after accepting a new block."""
from types import SimpleNamespace
import random
import pytest
from benchmarks.batch_tokenizer import BatchCount, BatchSelector
from npk.pack import PackSelector, compile_pack


def make_counter(tmp_path):
    t = pytest.importorskip('tokenizers')
    codec = t.Tokenizer(t.models.BPE({'a': 0, 'b': 1, 'ab': 2, '[UNK]': 3},
                                    [('a', 'b')], unk_token='[UNK]'))
    codec.pre_tokenizer = t.pre_tokenizers.WhitespaceSplit()
    codec.add_tokens([t.AddedToken('a b', lstrip=True)])
    path = tmp_path/'tokenizer.json'; path.write_text(codec.to_str(), encoding='utf-8')
    return codec, BatchCount(path)


def test_prefetch_counts_whole_strings_and_never_reuses_a_different_prefix(tmp_path):
    codec, counter = make_counter(tmp_path)
    counter.prefetch(['ab', 'a b', 'a\n\nb', 'ab'])
    for text in ('a\n\nb', 'ab', 'b ab', 'a b', 'b\n\na b'):
        assert counter.count(text) == len(codec.encode(text, add_special_tokens=False).ids)
    assert counter.batch_info()['texts'] == 3 and counter.batch_info()['prefetch_hits'] == 3
    counter.clear_cache(); assert counter.batch_info()['retained_characters'] == 0


@pytest.mark.parametrize('batch_size', [1, 2, 8])
def test_admission_order_matches_greedy_for_arbitrary_nonadditive_counts(batch_size):
    rng = random.Random(2914)
    for _ in range(100):
        ids = list(range(12)); blocks = {bid: SimpleNamespace(text=str(bid)) for bid in ids}
        truth = {}; prefetched = {}; calls = []
        def exact(text):
            if text not in truth: truth[text] = rng.randrange(1, 24)
            return truth[text]
        def prefetch(texts):
            calls.append(texts)
            prefetched.update({text: exact(text) for text in texts})
        adapter = object.__new__(BatchSelector)
        adapter.batch_size = batch_size; adapter.batch_characters = 50
        adapter.tokenizer = SimpleNamespace(prefetch=prefetch)
        got = []
        for bid in adapter._batch_order(ids, blocks, got, 10):
            text = '\n\n'.join([b.text for b in got] + [blocks[bid].text])
            count = prefetched[text] if text in prefetched else exact(text)
            if count <= 10: got.append(blocks[bid])
        expected = []
        for bid in ids:
            if exact('\n\n'.join([b.text for b in expected]+[blocks[bid].text])) <= 10:
                expected.append(blocks[bid])
        assert [b.text for b in got] == [b.text for b in expected]
        assert all(sum(map(len, texts)) <= 50 and len(texts) <= batch_size for texts in calls)


def test_public_selector_adapter_keeps_fallback_risk_query_and_evidence(tmp_path):
    source = tmp_path/'repo'; source.mkdir()
    (source/'a.py').write_text('def a():\n    return 1\n\ndef b():\n    return a()\n', encoding='utf-8')
    pack = tmp_path/'a.npk'; compile_pack(source, pack)
    _, counter = make_counter(tmp_path)
    ordinary = PackSelector(pack, tokenizer=counter)
    batched = BatchSelector(pack, tokenizer=counter)
    for query in ('a', '`b`', 'zzzzmissing', 'Why does a call b?'):
        for budget in (1, 10, 100):
            counter.clear_cache(); before = ordinary.select(query, budget_tokens=budget).as_dict()
            counter.clear_cache(); after = batched.select(query, budget_tokens=budget).as_dict()
            before.pop('latency_ms'); after.pop('latency_ms')
            assert before == after

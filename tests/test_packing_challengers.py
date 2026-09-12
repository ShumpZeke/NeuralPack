from types import SimpleNamespace as Item
import importlib
import pytest

from benchmarks.packing_challengers import feedback_order, fuse_body, GroupedSelector,prepared_pack
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount
from npk.pack import compile_pack, LocalTokenizer
from npk.pack.format import open_pack, load_blocks
from tests.test_boundary_tokenizer import pipeline


def blocks():
    return {1: Item(id=1, name='First.exit', path='a.py'),
            2: Item(id=2, name='Second.exit', path='a.py'),
            3: Item(id=3, name='Builder.construct', path='b.py')}


@pytest.mark.parametrize('mode', ['leaf', 'file'])
def test_grouping_reacts_only_to_real_admissions(mode):
    evidence = []; order = feedback_order([1, 2, 3], blocks(), evidence, mode)
    assert next(order) == 1
    evidence.append(Item(block_id=1))
    assert list(order) == [3, 2], 'an accepted duplicate group should yield to another group'
    rejected = feedback_order([1, 2, 3], blocks(), [], mode)
    assert list(rejected) == [1, 2, 3], 'an oversized rejection is not an accepted group'


def test_anonymous_blocks_are_distinct_and_requests_do_not_share_group_state():
    data = {1: Item(id=1, name='', path='a.py'), 2: Item(id=2, name='', path='a.py'),
            3: Item(id=3, name='named', path='b.py')}
    evidence = []; order = feedback_order([1, 2, 3], data, evidence, 'leaf')
    assert next(order) == 1; evidence.append(Item(block_id=1))
    assert list(order) == [2, 3]
    assert list(feedback_order([1, 2, 3], data, [], 'leaf')) == [1, 2, 3]
    assert list(feedback_order([], data, [], 'leaf')) == []


def test_fusion_uses_both_channels_and_preserves_candidate_union():
    strong = [1, 2, 3, 4]; body = [4, 3, 5]
    assert fuse_body(strong, body) == [4, 3, 1, 2, 5]
    assert set(fuse_body(strong, body, 2)) == set(strong+body)
    assert fuse_body([], body) == body
    assert fuse_body(strong, []) == strong
    assert fuse_body([1, 2], [2, 1]) == [1, 2], 'ties retain first insertion order'
    with pytest.raises(ValueError): fuse_body([1, 1], body)
    with pytest.raises(ValueError): fuse_body(strong, body, True)


@pytest.mark.parametrize('mode', ['leaf', 'file'])
def test_grouping_can_displace_a_second_required_fact(mode):
    # Counterexample to universal quality dominance, not a new product policy.
    # Both required facts share a group. A different group has only noise.
    text = {1: 'fact A', 2: 'fact B', 3: 'noise'}
    def selected(order, evidence):
        for bid in order:
            if len('\n\n'.join(text[e.block_id] for e in [*evidence, Item(block_id=bid)])) <= 14:
                evidence.append(Item(block_id=bid))
        return [e.block_id for e in evidence]
    assert selected([1, 2, 3], []) == [1, 2]
    evidence = []
    assert selected(feedback_order([1, 2, 3], blocks(), evidence, mode), evidence) == [1, 3]


def test_body_fusion_can_overrule_a_correct_strong_first_result():
    # A weaker independent channel is not guaranteed to improve the champion.
    strong = [1, 2]; misleading_body = [2, *range(3, 20), 1]
    assert strong[0] == 1
    assert fuse_body(strong, misleading_body)[0] == 2


def test_heap_policy_matches_slow_reference_over_varied_admissions():
    import random
    from benchmarks.packing_audit import replay
    rng = random.Random(2919)
    for _ in range(80):
        data = {i: {'name': rng.choice(['A.exit', 'B.exit', 'C.run', '']),
                    'path': rng.choice(['a.py', 'b.py']), 'text': 'x'*rng.randrange(1, 40)} for i in range(12)}
        order = list(data); rng.shuffle(order); cap = rng.randrange(1, 100)
        for mode in ('leaf', 'file'):
            evidence = []; objects = {i: Item(id=i, **b) for i, b in data.items()}
            for bid in feedback_order(order, objects, evidence, mode):
                joined = '\n\n'.join(data[e.block_id]['text'] for e in [*evidence, Item(block_id=bid)])
                if len(joined) <= cap: evidence.append(Item(block_id=bid))
            assert [e.block_id for e in evidence] == replay(order, data, cap, mode, len)


def test_public_grouped_selection_uses_exact_budget_and_preserves_query(tmp_path, monkeypatch):
    tokenizers = pytest.importorskip('tokenizers')
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.WhitespaceSplit()
    asset = tmp_path/'tokenizer.json'; asset.write_text(backend.to_str(), encoding='utf-8')
    source = tmp_path/'src'; source.mkdir()
    (source/'a.py').write_text('class A:\n    def exit(self):\n        return 1\n\nclass B:\n    def exit(self):\n        return 2\n\nclass C:\n    def build(self):\n        return 3\n', encoding='utf-8')
    pack = tmp_path/'project.npk'; compile_pack(source, pack, python_members=True)
    with open_pack(pack) as con: data = {b.name: b for b in load_blocks(con)}
    ranked = [data[name].id for name in ('A.exit', 'B.exit', 'C.build')]
    monkeypatch.setattr(importlib.import_module('npk.pack.select'), '_lexical_channel', lambda *args: ranked)
    counter = LocalTokenizer(asset); selector = GroupedSelector(pack, tokenizer=counter)
    for cap in (1, 4, 8, 16, 64):
        result = selector.select('exact original 猫 query', budget_tokens=cap, allow_escalation=False)
        assert result.query == 'exact original 猫 query' and not result.used_generative_llm
        assert counter.count(result.context_text()) == result.total_tokens <= cap
        assert result.seed_failed == (not result.evidence)
        if cap == 8: assert [e.name for e in result.evidence] == ['A.exit', 'C.build']
    again = selector.select('exact original 猫 query', budget_tokens=8, allow_escalation=False)
    assert [e.name for e in again.evidence] == ['A.exit', 'C.build']


@pytest.mark.parametrize('mode',['rank','leaf','file'])
def test_partial_evaluator_matches_independent_exact_admission_and_fallback(pipeline,mode):
    codec,asset=pipeline
    data={
        1:Item(id=1,name='A.exit',path='a.py',text='alpha long body '+('x '*20)),
        2:Item(id=2,name='A.exit',path='a.py',text='small beta'),
        3:Item(id=3,name='C.build',path='b.py',text='界 gamma 😀'),
        4:Item(id=4,name='',path='c.py',text='tail delta'),
    }
    ordered=list(data);counter=CompactBoundaryCount(asset);counter.prepare([b.text for b in data.values()])
    for budget in (2,5,12,40):
        evidence=[]
        stream=(feedback_order(ordered,data,evidence,mode)
                if mode in ('leaf','file') else iter(ordered))
        for bid in stream:
            parts=[data[e.block_id].text for e in evidence]+[data[bid].text]
            if len(codec.encode('\n\n'.join(parts),add_special_tokens=False))<=budget:
                evidence.append(Item(block_id=bid))
        expected=tuple(e.block_id for e in evidence)
        result=prepared_pack(ordered,data,budget,counter,mode)
        assert result.ids==expected
        text='\n\n'.join(data[bid].text for bid in expected)
        assert result.total_tokens==len(codec.encode(text,add_special_tokens=False))<=budget
        assert result.incremental_attempts>0 and result.fallback_attempts==0

        fallback=CompactBoundaryCount(asset,prepared_bytes=0)
        fallback.prepare([b.text for b in data.values()])
        slow=prepared_pack(ordered,data,budget,fallback,mode)
        assert (slow.ids,slow.total_tokens)==(result.ids,result.total_tokens)
        assert slow.fallback_attempts==len(ordered)

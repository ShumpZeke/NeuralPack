from benchmarks.packing_audit import replay, hit, expected_pool


def test_reference_replay_distinguishes_rejection_from_admission():
    data = {1: {'name': 'A.exit', 'path': 'a.py', 'text': 'x'*100},
            2: {'name': 'B.exit', 'path': 'a.py', 'text': 'a'},
            3: {'name': 'C.build', 'path': 'b.py', 'text': 'b'}}
    assert replay([1, 2, 3], data, 1, 'leaf', len) == [2]
    data[1]['text'] = 'x'
    assert replay([1, 2, 3], data, 4, 'leaf', len) == [1, 3]
    assert replay([1, 2, 3], data, 4, 'rank', len) == [1, 2]
    assert replay([], data, 4, 'leaf', len) == []


def test_independent_metric_requires_attributable_source():
    task = {'path': 'a.py', 'span': 'a.py:1-2', 'needles': ['answer']}
    assert not hit([{'path': 'b.py', 'span': 'b.py:1-2', 'text': 'answer'}], task)
    assert not hit([{'path': 'a.py', 'span': 'a.py:10-12', 'text': 'answer'}], task)
    assert hit([{'path': 'a.py', 'span': 'a.py:1-2', 'text': 'answer'}], task)
    assert expected_pool({'body': [4, 3], 'fields': [1, 2, 3, 4]}, 'fields', 'fuse1') == [4, 3, 1, 2]

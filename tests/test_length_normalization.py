from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from benchmarks.length_normalization import rank


# These globals are deliberately shared by all fixture instances. The adapter
# must isolate the override even when calls use the same scorer concurrently.
B = 0.75
K1 = 1.2


class FixtureScorer:
    def candidates(self, plan, limit):
        return [(plan['query'], B, K1)][:limit]


def test_independent_parameter_bindings_and_parallel_isolation():
    scorer = FixtureScorer(); plan = {'query': '\u503c: preserve this question', 'weights': [1, 2, 3]}
    before = deepcopy(plan)
    values = [0, .25, .5, .75, 1]*20
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda b: rank(scorer, plan, 1, length_normalization=b), values))
    assert rows == [[(plan['query'], b, 1.2)] for b in values]
    assert plan == before and B == .75 and K1 == 1.2
    assert scorer.candidates(plan, 1) == [(plan['query'], .75, 1.2)]


@pytest.mark.parametrize('value', [-1, 1.01, float('inf'), float('nan'), True, '0.5', None])
def test_invalid_normalization_fails_explicitly(value):
    with pytest.raises(ValueError): rank(FixtureScorer(), {}, 1, length_normalization=value)


@pytest.mark.parametrize('limit', [0, -1, True, 1.5])
def test_invalid_limit_fails_explicitly(limit):
    with pytest.raises(ValueError): rank(FixtureScorer(), {}, limit, length_normalization=.5)


def test_unsupported_scorer_cannot_silently_ignore_the_flag():
    class NoLengthPenalty:
        def candidates(self, plan, limit): return []
    with pytest.raises(ValueError): rank(NoLengthPenalty(), {}, 1, length_normalization=.5)

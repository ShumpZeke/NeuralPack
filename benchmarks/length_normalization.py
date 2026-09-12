"""Research-only BM25 length-penalty ablation of the frozen rival scorer.

Reuse the captured candidate function with a private globals mapping. Never
patch process-wide scorer constants, change its query facets, or copy/rewrite
the ranking formula. The original .75 arm is an exact reproduction gate.
"""
import math
from types import FunctionType


def rank(scorer, plan, limit, *, length_normalization):
    if (type(length_normalization) not in (int, float)
            or not math.isfinite(length_normalization)
            or not 0 <= length_normalization <= 1):
        raise ValueError('Length normalization must be finite and between zero and one')
    if type(limit) is not int or limit < 1:
        raise ValueError('Candidate limit must be a positive integer')
    bound = scorer.candidates
    fn = getattr(bound, '__func__', None)
    if fn is None or not {'B', 'K1'} <= set(fn.__code__.co_names):
        raise ValueError('Expected the captured BM25 candidate function')
    scope = dict(fn.__globals__)
    if scope.get('B') != 0.75 or scope.get('K1') != 1.2:
        raise ValueError('Frozen scorer defaults changed')
    scope['B'] = float(length_normalization)
    isolated = FunctionType(fn.__code__, scope, fn.__name__, fn.__defaults__, fn.__closure__)
    isolated.__kwdefaults__ = fn.__kwdefaults__
    return isolated(scorer, plan, limit)

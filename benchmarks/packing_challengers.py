"""Local research challengers: lexical fusion and admission-aware grouping.

These are not product defaults or calibrated confidence estimators. No task
labels or answers enter either function. The public exact budget check remains
the admission authority, including for candidates tried in a different order.
"""
import ast
from collections import defaultdict, deque
import heapq
import importlib
import inspect
import textwrap
from dataclasses import dataclass

from npk.pack import PackSelector


@dataclass(frozen=True,slots=True)
class PreparedPacking:
    ids: tuple[int, ...]
    total_tokens: int
    incremental_attempts: int
    fallback_attempts: int


@dataclass(frozen=True,slots=True)
class _AdmissionItem:
    block_id: int
    text: str


def fuse_body(strong, body, strong_weight=1):
    """Rank-zero RRF, k=60, matching the product convention; stable ties."""
    if type(strong_weight) is not int or strong_weight not in (1, 2):
        raise ValueError('Only declared strong-channel weights 1 and 2 are supported')
    scores = {}
    for ids, weight in ((strong, strong_weight), (body, 1)):
        if len(set(ids)) != len(ids): raise ValueError('Duplicate rank entries')
        for rank, bid in enumerate(ids): scores[bid] = scores.get(bid, 0.0)+weight/(60+rank)
    return sorted(scores, key=lambda bid: -scores[bid])


def group_key(block, mode):
    if mode == 'file': return 'file', block.path
    if mode == 'leaf':
        return ('name', block.name.rsplit('.', 1)[-1]) if block.name else ('anonymous', block.id)
    raise ValueError('Unknown grouping policy')


def _was_admitted(evidence, previous_size, bid):
    return len(evidence) > previous_size and evidence[-1].block_id == bid


def feedback_order(ordered, blocks, evidence, mode):
    """Visit the least-admitted group first; preserve original rank for ties.

Rejected candidates do not consume their group's turn. All candidates are
eventually visited exactly once. Group state is private to one iterator.
"""
    if len(set(ordered)) != len(ordered): raise ValueError('Duplicate candidate ids')
    groups = defaultdict(deque)
    for rank, bid in enumerate(ordered):
        if bid in blocks: groups[group_key(blocks[bid], mode)].append((rank, bid))
    heap = [(0, entries[0][0], key) for key, entries in groups.items()]
    heapq.heapify(heap)
    while heap:
        accepted, _, key = heapq.heappop(heap)
        _, bid = groups[key].popleft(); previous_size = len(evidence)
        yield bid
        accepted += _was_admitted(evidence, previous_size, bid)
        if groups[key]: heapq.heappush(heap, (accepted, groups[key][0][0], key))


def prepared_pack(ordered,blocks,budget,counter,mode='rank',transition_cache=None):
    """Evaluate one frozen ranking without repeating selector/index work.

    Each budget still gets independent admission state. This is required:
    skipping an oversized passage makes selected sets non-nested across caps.
    The incremental path is exact for prepared boundary records. If a record is
    unavailable, counting falls back to the upstream whole-context operation.
    """
    if mode not in ('rank','leaf','file'):
        raise ValueError('Unknown packing mode')
    if type(budget) is not int or budget<1:
        raise ValueError('Positive integer budget required')
    if len(ordered)!=len(set(ordered)) or any(bid not in blocks for bid in ordered):
        raise ValueError('Candidate identities must be unique and known')
    evidence=[];texts=[];state=counter.initial_state();incremental=fallback=0;total=0
    stream=(feedback_order(ordered,blocks,evidence,mode)
            if mode in ('leaf','file') else iter(ordered))
    for bid in stream:
        block=blocks[bid]
        text=block['text'] if isinstance(block,dict) else block.text
        trial=(counter.extend_state(state,text,transition_cache=transition_cache)
               if state is not None else None)
        if trial is None:
            size=counter.count_parts(texts+[text]);fallback+=1
        else:
            size=trial.total_tokens;incremental+=1
        if size<=budget:
            evidence.append(_AdmissionItem(bid,text));texts.append(text)
            state=trial;total=size
    return PreparedPacking(tuple(item.block_id for item in evidence),total,incremental,fallback)


def adapt():
    module = importlib.import_module('npk.pack.select')
    tree = ast.parse(textwrap.dedent(inspect.getsource(PackSelector._select_once)))
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == 'block_id'
             and isinstance(n.iter, ast.Name) and n.iter.id == 'ordered_ids']
    if len(loops) != 1: raise ValueError('Public admission loop changed')
    loops[0].iter = ast.Call(func=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()),
                                              attr='_candidate_order', ctx=ast.Load()),
                             args=[ast.Name(id=name, ctx=ast.Load()) for name in ('ordered_ids', 'blocks', 'evidence')],
                             keywords=[])
    ast.fix_missing_locations(tree)
    namespace = dict(vars(module))
    for name in ('_lexical_channel', '_symbol_channel', '_embedding_channel'):
        def forward(*args, _name=name, **kwargs): return getattr(module, _name)(*args, **kwargs)
        namespace[name] = forward
    exec(compile(tree, __file__, 'exec'), namespace)
    return namespace['_select_once']


class GroupedSelector(PackSelector):
    _select_once = adapt()

    def __init__(self, *args, group_mode='leaf', **kwargs):
        if group_mode not in ('leaf', 'file'): raise ValueError('Unknown group mode')
        super().__init__(*args, **kwargs)
        self.group_mode = group_mode

    def _candidate_order(self, ordered, blocks, evidence):
        return feedback_order(ordered, blocks, evidence, self.group_mode)

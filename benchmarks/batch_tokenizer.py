"""Experimental exact speculative counts; the public greedy order is unchanged.

After a rejection, count a bounded batch of upcoming assemblies at the current
prefix. If another block is accepted, old counts remain keyed by exact text and
cannot be reused for its changed prefix. No assumption about count additivity
or monotonicity is made. Only the loop iterator is adapted in the public code.
"""
import ast
import importlib
import inspect
import textwrap

from benchmarks.fast_tokenizer_eval import FastCount
from npk.pack import PackSelector
from npk.pack.format import PackError


class BatchCount(FastCount):
    def __init__(self, path, **kwargs):
        super().__init__(path, **kwargs)
        self._prefetched = {}
        self.batch_calls = self.batch_texts = self.batch_characters = self.prefetch_hits = 0

    def prefetch(self, texts):
        with self._lock:
            missing = list(dict.fromkeys(t for t in texts if t not in self._cache))
            if not missing: return
            try:
                encoded = self._backend.encode_batch_fast(missing, add_special_tokens=False)
                values = [len(e) for e in encoded]
                if len(values) != len(missing): raise ValueError('Batch result length changed')
                if any(t.strip() and n == 0 for t, n in zip(missing, values)):
                    raise ValueError('Nonempty text discarded')
            except Exception:
                raise PackError('Local tokenizer could not count the supplied batch') from None
            self._prefetched = dict(zip(missing, values))
            self.batch_calls += 1; self.batch_texts += len(missing)
            self.batch_characters += sum(map(len, missing))

    def _count_uncached(self, text):
        value = self._prefetched.get(text)
        if value is not None:
            self.prefetch_hits += 1
            return value
        return super()._count_uncached(text)

    def clear_cache(self):
        with self._lock:
            super().clear_cache(); self._prefetched.clear()
            self.batch_calls = self.batch_texts = self.batch_characters = self.prefetch_hits = 0

    def batch_info(self):
        return {'calls': self.batch_calls, 'texts': self.batch_texts,
                'characters': self.batch_characters, 'prefetch_hits': self.prefetch_hits,
                'retained_characters': sum(map(len, self._prefetched))}


def adapted_select_once():
    """Fail on source drift; preserve every public selection statement."""
    module = importlib.import_module('npk.pack.select')
    tree = ast.parse(textwrap.dedent(inspect.getsource(PackSelector._select_once)))
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == 'block_id'
             and isinstance(n.iter, ast.Name) and n.iter.id == 'ordered_ids']
    if len(loops) != 1: raise ValueError('Public admission loop is no longer unique')
    loops[0].iter = ast.Call(func=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()),
                                             attr='_batch_order', ctx=ast.Load()),
                            args=[ast.Name(id=name, ctx=ast.Load()) for name in
                                  ('ordered_ids', 'blocks', 'evidence', 'budget')], keywords=[])
    ast.fix_missing_locations(tree)
    namespace = dict(vars(module)); exec(compile(tree, __file__, 'exec'), namespace)
    return namespace['_select_once']


class BatchSelector(PackSelector):
    _select_once = adapted_select_once()

    def __init__(self, *args, batch_size=8, batch_characters=128*1024, **kwargs):
        super().__init__(*args, **kwargs)
        for value in (batch_size, batch_characters):
            if type(value) is not int or value <= 0: raise ValueError('Positive batch limits required')
        if not isinstance(self.tokenizer, BatchCount): raise ValueError('Explicit BatchCount required')
        self.batch_size = batch_size; self.batch_characters = batch_characters

    def _batch_order(self, ordered_ids, blocks, evidence, budget):
        prepared_until = 0
        for index, block_id in enumerate(ordered_ids):
            previous_size = len(evidence)
            yield block_id
            if len(evidence) != previous_size:
                # Acceptance invalidates the prefix used by speculative work.
                prepared_until = 0
                continue
            start = index + 1
            if start < prepared_until: continue
            prefix = '\n\n'.join(e.text for e in evidence)
            texts = []; characters = 0
            for future in ordered_ids[start:start+self.batch_size]:
                block = blocks.get(future)
                if block is None: continue
                text = prefix+'\n\n'+block.text if evidence else block.text
                if characters + len(text) > self.batch_characters: break
                texts.append(text); characters += len(text)
            if texts:
                self.tokenizer.prefetch(texts)
                # Missing blocks can reduce batching efficiency, never alter
                # the yielded IDs or the admission check in public code.
                prepared_until = start + len(texts)

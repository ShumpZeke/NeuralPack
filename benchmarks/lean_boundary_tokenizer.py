"""Startup challenger: inspect loaded metadata without serializing the vocabulary.

Research only. The region algorithm, cache format, asset restriction and safe
fallback are inherited unchanged. LocalTokenizer still constructs its backend
from a single captured and hashed byte body and rejects stochastic BPE dropout.
"""
from collections import OrderedDict
import re

from benchmarks import boundary_tokenizer
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount
from benchmarks.fast_tokenizer_eval import FastCount


class LeanCompactBoundaryCount(CompactBoundaryCount):
    def __init__(self, path, *, cache_bytes=0, prepared_bytes=32*1024*1024):
        if type(prepared_bytes) is not int or prepared_bytes < 0:
            raise ValueError('prepared_bytes must be a non-negative integer')
        FastCount.__init__(self, path, cache_bytes=cache_bytes)
        # Documented metadata accessors return only the added vocabulary. Avoid
        # to_str(), which serializes the entire ordinary vocabulary and merges.
        added = list(self._backend.get_added_tokens_decoder().values())
        self.boundary_enabled = self._allows_boundaries(added)
        self._added = re.compile('|'.join(re.escape(t.content) for t in added)) if added else None
        self._prepared = OrderedDict()
        self._prepared_limit = prepared_bytes
        self._prepared_retained = 0
        self.compiled_parts = self.compile_rejections = self.fallback_calls = self.boundary_calls = 0

    def _allows_boundaries(self, added):
        return (self.sha256 == boundary_tokenizer.PINNED_ASSET
                and self._backend.normalizer is None
                and all(not (t.lstrip or t.rstrip or t.normalized or t.single_word)
                        and '\n' not in t.content and '\r' not in t.content for t in added))

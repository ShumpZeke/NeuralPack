"""Research hypothesis: compile block interiors, re-encode joins at query time.

This is NOT a general tokenizer decomposition theorem or production fast path.
The experiment is restricted to one pinned, inspected tokenizer pipeline.
Actual joined outputs must pass differential tests before any speed conclusion.
Ordinary count() remains the upstream whole-text implementation.
"""
from collections import OrderedDict
from dataclasses import dataclass
import json
import re
import sys

from benchmarks.fast_tokenizer_eval import FastCount

PINNED_ASSET = '623c34567aebb18582765289fbe23d901c62704d6518d71866e0e58db892b5b7'


@dataclass(frozen=True)
class _Interior:
    prefix: str
    suffix: str
    ids: tuple[int, ...]
    split: bool


class BoundaryCount(FastCount):
    def __init__(self, path, *, cache_bytes=0, prepared_bytes=32*1024*1024):
        super().__init__(path, cache_bytes=cache_bytes)
        if type(prepared_bytes) is not int or prepared_bytes < 0:
            raise ValueError('prepared_bytes must be a non-negative integer')
        config = json.loads(self._backend.to_str())
        added = config.get('added_tokens', [])
        self.boundary_enabled = (self.sha256 == PINNED_ASSET
                                 and config.get('normalizer') is None
                                 and all(not any(t.get(k, False) for k in ('lstrip','rstrip','normalized','single_word'))
                                         and '\n' not in t['content'] and '\r' not in t['content'] for t in added))
        self._added = re.compile('|'.join(re.escape(t['content']) for t in added)) if added else None
        self._prepared = OrderedDict()
        self._prepared_limit = prepared_bytes
        self._prepared_retained = 0
        self.compiled_parts = self.compile_rejections = self.fallback_calls = self.boundary_calls = 0

    def _segment(self, text):
        if not self.boundary_enabled or self._added and self._added.search(text): return None
        pieces = self._backend.pre_tokenizer.pre_tokenize_str(text)
        cursor = 0; anchors = []
        for i, (_, (start, end)) in enumerate(pieces):
            if start != cursor or end < start: return None
            cursor = end
            if any(c.isalnum() for c in text[start:end]): anchors.append(i)
        if cursor != len(text): return None
        if len(anchors) < 2:
            return _Interior(text, '', (), False)
        first, last = anchors[0], anchors[-1]
        prefix = text[:pieces[first][1][1]]
        suffix = text[pieces[last][1][0]:]
        ids = tuple(token.id for piece, _ in pieces[first+1:last]
                    for token in self._backend.model.tokenize(piece))
        segment = _Interior(prefix, suffix, ids, True)
        # Compile-time local check is necessary but not sufficient: a join may
        # still invalidate a boundary. The separate attack harness tests joins.
        reconstructed = (self._backend.encode(prefix, add_special_tokens=False).ids + list(ids)
                         + self._backend.encode(suffix, add_special_tokens=False).ids)
        if reconstructed != self._backend.encode(text, add_special_tokens=False).ids: return None
        return segment

    def prepare(self, texts):
        """Explicit reusable work. Missing/evicted text never compiles on query."""
        if not isinstance(texts, (list, tuple)) or any(not isinstance(t, str) for t in texts):
            raise TypeError('Prepared sources must be a list/tuple of text blocks')
        with self._lock:
            for text in dict.fromkeys(texts):
                if text in self._prepared: continue
                segment = self._segment(text); self.compiled_parts += 1
                if segment is None: self.compile_rejections += 1
                size = sys.getsizeof(text)+256
                if segment is not None:
                    size += sys.getsizeof(segment.prefix)+sys.getsizeof(segment.suffix)+sys.getsizeof(segment.ids)
                    size += sum(sys.getsizeof(i) for i in segment.ids)
                if size > self._prepared_limit: continue
                while self._prepared and (self._prepared_retained+size>self._prepared_limit or len(self._prepared)>=16384):
                    _, (_, released) = self._prepared.popitem(last=False); self._prepared_retained -= released
                self._prepared[text] = segment, size; self._prepared_retained += size

    def _units(self, parts):
        if not isinstance(parts, (list, tuple)) or any(not isinstance(t, str) for t in parts):
            raise TypeError('Context parts must be a list/tuple of strings')
        entries = [self._prepared.get(text) for text in parts]
        if not self.boundary_enabled or any(entry is None or entry[0] is None for entry in entries):
            self.fallback_calls += 1
            return ['\n\n'.join(parts)]
        units = []; pending = ''
        for index, (segment, _) in enumerate(entries):
            if index: pending += '\n\n'
            pending += segment.prefix
            if segment.split:
                units.extend((pending, segment.ids)); pending = segment.suffix
        units.append(pending); self.boundary_calls += 1
        return units

    def count_parts(self, parts):
        with self._lock:
            return sum(self.count(u) if isinstance(u, str) else len(u) for u in self._units(parts))

    def differential_ids(self, parts):
        with self._lock:
            return [token for u in self._units(parts) for token in
                    (self._backend.encode(u, add_special_tokens=False).ids if isinstance(u, str) else u)]

    def prepared_info(self):
        with self._lock:
            return {'enabled':self.boundary_enabled,'entries':len(self._prepared),
                    'max_bytes':self._prepared_limit,'accounted_retained_bytes':self._prepared_retained,
                    'compiled_parts':self.compiled_parts,'compile_rejections':self.compile_rejections,
                    'boundary_calls':self.boundary_calls,'fallback_calls':self.fallback_calls}

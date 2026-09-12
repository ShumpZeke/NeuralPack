"""Research counter with a whole-text pre-tokenization equality gate.

Only verified piece sequences use compiled interior counts. A failed gate
returns the upstream full count. This trades more query work for removing the
unproved boundary-stability assumption from accepted decompositions.
"""
from collections import OrderedDict
from dataclasses import dataclass
import json
import re
import sys

from benchmarks.fast_tokenizer_eval import FastCount
from npk.pack import PackSelector
from npk.pack.format import PackError


@dataclass(frozen=True, slots=True)
class PieceInterior:
    prefix: str
    suffix: str
    pieces: tuple[str, ...]
    tokens: int
    split: bool


class VerifiedBoundaryCount(FastCount):
    def __init__(self, path, *, cache_bytes=0, prepared_bytes=64*1024*1024):
        super().__init__(path, cache_bytes=cache_bytes)
        if type(prepared_bytes) is not int or prepared_bytes < 0:
            raise ValueError('prepared_bytes must be a non-negative integer')
        cfg = json.loads(self._backend.to_str())
        post = cfg.get('post_processor')
        self.verified_enabled = (cfg.get('normalizer') is None and cfg['model']['type']=='BPE'
                                 and cfg.get('pre_tokenizer') is not None
                                 and (post is None or post.get('type')=='ByteLevel'))
        added = [t['content'] for t in cfg.get('added_tokens', [])]
        self._added = re.compile('|'.join(re.escape(t) for t in added)) if added else None
        self._prepared = OrderedDict()
        self._prepared_limit = prepared_bytes; self._retained = 0
        self.compiled_parts = self.compile_rejections = 0
        self.verified_calls = self.fallback_calls = self.gate_rejections = 0

    def _pieces(self, text):
        return tuple(piece for piece, _ in self._backend.pre_tokenizer.pre_tokenize_str(text))

    def _eligible_text(self, text):
        return self.verified_enabled and not (self._added and self._added.search(text))

    def _segment(self, text):
        if not self._eligible_text(text): return None
        pieces = self._backend.pre_tokenizer.pre_tokenize_str(text)
        cursor = 0; anchors = []
        for i, (_, (start, end)) in enumerate(pieces):
            if start != cursor or end < start: return None
            cursor = end
            if any(c.isalnum() for c in text[start:end]): anchors.append(i)
        if cursor != len(text): return None
        if len(anchors) < 2: return PieceInterior(text, '', (), 0, False)
        first, last = anchors[0], anchors[-1]
        prefix = text[:pieces[first][1][1]]; suffix = text[pieces[last][1][0]:]
        middle = tuple(piece for piece, _ in pieces[first+1:last])
        tokens = sum(len(self._backend.model.tokenize(piece)) for piece in middle)
        rec = PieceInterior(prefix, suffix, middle, tokens, True)
        if self._pieces(prefix)+middle+self._pieces(suffix) != tuple(p for p, _ in pieces): return None
        try:
            if self.count(prefix)+tokens+self.count(suffix) != self.count(text): return None
        except PackError:
            # A fragment can be unencodable even when the whole input is valid.
            # Reject this optional decomposition and keep the full encoder.
            return None
        return rec

    @staticmethod
    def _size(text, record):
        size = sys.getsizeof(text)+256
        if record is not None:
            size += sys.getsizeof(record)+sys.getsizeof(record.prefix)+sys.getsizeof(record.suffix)
            size += sys.getsizeof(record.pieces)+sum(sys.getsizeof(p) for p in record.pieces)
        return size

    def prepare(self, texts):
        if not isinstance(texts, (list, tuple)) or any(not isinstance(t, str) for t in texts):
            raise TypeError('Prepared sources must be a list/tuple of text blocks')
        with self._lock:
            for text in dict.fromkeys(texts):
                if text in self._prepared: continue
                record = self._segment(text); self.compiled_parts += 1
                if record is None: self.compile_rejections += 1
                size = self._size(text, record)
                if size > self._prepared_limit: continue
                while self._prepared and (self._retained+size>self._prepared_limit or len(self._prepared)>=16384):
                    _, (_, released) = self._prepared.popitem(last=False); self._retained -= released
                self._prepared[text] = record, size; self._retained += size

    def _verified_partition(self, parts):
        if not isinstance(parts, (list, tuple)) or any(not isinstance(t, str) for t in parts):
            raise TypeError('Context parts must be a list/tuple of text blocks')
        text = '\n\n'.join(parts)
        entries = [self._prepared.get(p) for p in parts]
        if not self._eligible_text(text) or any(e is None or e[0] is None for e in entries):
            self.fallback_calls += 1
            return text, None, None
        units = []; pending = ''
        for i, (rec, _) in enumerate(entries):
            if i: pending += '\n\n'
            pending += rec.prefix
            if rec.split:
                units.extend((pending, rec)); pending = rec.suffix
        units.append(pending)
        expected = []; boundary_pieces = []; interior_tokens = 0
        for unit in units:
            if isinstance(unit, str):
                ps = self._pieces(unit); expected.extend(ps); boundary_pieces.extend(ps)
            else:
                expected.extend(unit.pieces); interior_tokens += unit.tokens
        actual = self._pieces(text)
        if tuple(expected) != actual:
            self.gate_rejections += 1; self.fallback_calls += 1
            return text, None, None
        self.verified_calls += 1
        return text, (interior_tokens, boundary_pieces), actual

    def count_parts(self, parts):
        with self._lock:
            text, verified, _ = self._verified_partition(parts)
            if verified is None: return self.count(text)
            interior_tokens, boundary_pieces = verified
            total = interior_tokens+sum(len(self._backend.model.tokenize(p)) for p in boundary_pieces)
            if text.strip() and total == 0:
                raise PackError('Local tokenizer discarded all non-whitespace input')
            return total

    def differential_ids(self, parts):
        with self._lock:
            text, verified, actual = self._verified_partition(parts)
            if verified is None: return self._backend.encode(text, add_special_tokens=False).ids
            return [t.id for p in actual for t in self._backend.model.tokenize(p)]

    def prepared_info(self):
        with self._lock:
            return {'enabled':self.verified_enabled,'entries':len(self._prepared),
                    'max_bytes':self._prepared_limit,'accounted_retained_bytes':self._retained,
                    'compiled_parts':self.compiled_parts,'compile_rejections':self.compile_rejections,
                    'verified_calls':self.verified_calls,'fallback_calls':self.fallback_calls,
                    'gate_rejections':self.gate_rejections}


class VerifiedBoundarySelector(PackSelector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not isinstance(self.tokenizer, VerifiedBoundaryCount):
            raise ValueError('An explicit VerifiedBoundaryCount is required')

    def _fits(self, evidence, text, budget, *, used_chars=None):
        return self.tokenizer.count_parts([e.text for e in evidence]+[text]) <= budget

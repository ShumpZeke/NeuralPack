"""Research counter: reuse BPE results after the real whole-text pre-tokenizer.

Never add independently counted source blocks. Splits are recomputed on the
actual joined text. Unsupported pipeline stages and possible added-token matches
use the ordinary encoder. This is not yet a product implementation.
"""
from collections import OrderedDict
import json
import re
import sys

from npk.pack.tokenizer import LocalTokenizer
from npk.pack.format import PackError


class PieceCount(LocalTokenizer):
    def __init__(self, path, *, cache_bytes=4*1024*1024, piece_bytes=4*1024*1024):
        super().__init__(path, cache_bytes=cache_bytes)
        if type(piece_bytes) is not int or piece_bytes < 0:
            raise ValueError('piece_bytes must be a non-negative integer')
        # Use the captured, already validated backend, not a second asset read.
        config = json.loads(self._backend.to_str())
        post = config.get('post_processor')
        self.piece_enabled = (config.get('normalizer') is None
                              and config['model']['type'] == 'BPE'
                              and config.get('pre_tokenizer') is not None
                              and (post is None or post.get('type') == 'ByteLevel'))
        added = [token['content'] for token in config.get('added_tokens', [])]
        self._added = re.compile('|'.join(re.escape(s) for s in added)) if added else None
        self._pieces = OrderedDict()
        self._piece_limit = piece_bytes
        self._piece_retained = self._piece_hits = self._piece_misses = self._fallbacks = 0

    def _needs_fallback(self, text):
        return not self.piece_enabled or self._added is not None and self._added.search(text) is not None

    def _parts(self, text):
        return self._backend.pre_tokenizer.pre_tokenize_str(text)

    def differential_ids(self, text):
        """Uncached diagnostic of the guarded decomposition, not the count API."""
        if self._needs_fallback(text):
            return self._backend.encode(text, add_special_tokens=False).ids
        return [token.id for piece, _ in self._parts(text) for token in self._backend.model.tokenize(piece)]

    def _count_uncached(self, text):
        if not text: return 0
        if self._needs_fallback(text):
            self._fallbacks += 1
            return super()._count_uncached(text)
        try:
            count = 0
            for piece, _ in self._parts(text):
                entry = self._pieces.get(piece)
                if entry is None:
                    self._piece_misses += 1
                    value = len(self._backend.model.tokenize(piece))
                    size = sys.getsizeof(piece) + 256
                    if size <= self._piece_limit:
                        while self._pieces and (self._piece_retained + size > self._piece_limit
                                                or len(self._pieces) >= 16384):
                            _, (_, released) = self._pieces.popitem(last=False)
                            self._piece_retained -= released
                        self._pieces[piece] = (value, size)
                        self._piece_retained += size
                else:
                    self._piece_hits += 1
                    self._pieces.move_to_end(piece)
                    value = entry[0]
                count += value
        except Exception:
            raise PackError('Local tokenizer could not count the supplied text') from None
        if text.strip() and count == 0:
            raise PackError('Local tokenizer discarded all non-whitespace input')
        return count

    def clear_cache(self):
        with self._lock:
            super().clear_cache()
            self._pieces.clear()
            self._piece_retained = self._piece_hits = self._piece_misses = self._fallbacks = 0

    def piece_info(self):
        with self._lock:
            return {'enabled': self.piece_enabled, 'entries': len(self._pieces),
                    'max_bytes': self._piece_limit, 'retained_bytes': self._piece_retained,
                    'hits': self._piece_hits, 'misses': self._piece_misses, 'fallbacks': self._fallbacks}

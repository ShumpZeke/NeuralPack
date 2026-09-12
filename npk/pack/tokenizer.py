"""Explicit local text tokenization; no model, downloads or provider requests."""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
import sys
import threading

from .format import PackError


class LocalTokenizer:
    """Count text with a supplied Hugging Face tokenizer JSON data file.

    Counts describe this exact asset, not an inferred model/provider. Callers
    must choose the matching tokenizer for their target. Model weights and
    remote Python code are never loaded. Padding and truncation are disabled;
    automatically added prompt tokens are excluded from raw context counts.
    """

    MAX_ASSET_BYTES = 32 * 1024 * 1024

    def __init__(self, path: str | Path, *, cache_bytes: int = 4 * 1024 * 1024):
        if type(cache_bytes) is not int or cache_bytes < 0:
            raise ValueError('cache_bytes must be a non-negative integer')
        try:
            with Path(path).open('rb') as stream:
                body = stream.read(self.MAX_ASSET_BYTES + 1)
        except OSError:
            raise PackError('Cannot read the local tokenizer JSON asset') from None
        if len(body) > self.MAX_ASSET_BYTES:
            raise PackError('Local tokenizer JSON exceeds the 32 MiB asset limit')
        try:
            # Parse a single captured body so a changed path cannot alter the
            # tokenizer after hashing but before construction.
            config = json.loads(body)
            if not isinstance(config, dict) or not isinstance(config.get('model'), dict):
                raise ValueError
            # BPE dropout samples a different segmentation on repeated calls.
            # A sampled count cannot enforce a reproducible context cap.
            if config['model'].get('dropout') not in (None, 0, 0.0):
                raise ValueError
            from tokenizers import Tokenizer
            backend = Tokenizer.from_str(body.decode('utf-8'))
            backend.no_truncation()
            backend.no_padding()
        except ImportError:
            raise PackError('Exact counting requires the optional tokenizers package; install neuralpack[tokenizers]') from None
        except Exception:
            # Rust tokenizers raises plain Exception for malformed data. Do not
            # echo asset content or parser messages, which can contain input.
            raise PackError('Invalid or unsupported local tokenizer JSON') from None
        self._backend = backend
        self.sha256 = hashlib.sha256(body).hexdigest()
        self._cache = OrderedDict()
        self._cache_bytes = cache_bytes
        self._retained_bytes = self._hits = self._misses = 0
        self._lock = threading.RLock()

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError('Tokenizer input must be text')
        # Exact text keys and a fixed tokenizer make reuse independent of the
        # query, artifact and source version. Serialize cache access while the
        # Rust encoder releases the GIL; never retain a failed count.
        with self._lock:
            cached = self._cache.get(text)
            if cached is not None:
                self._hits += 1
                self._cache.move_to_end(text)
                return cached[0]
            self._misses += 1
            count = self._count_uncached(text)
            size = sys.getsizeof(text) + 256
            if size <= self._cache_bytes:
                while self._cache and (self._retained_bytes + size > self._cache_bytes
                                       or len(self._cache) >= 4096):
                    _, (_, dropped) = self._cache.popitem(last=False)
                    self._retained_bytes -= dropped
                self._cache[text] = (count, size)
                self._retained_bytes += size
            return count

    def _count_uncached(self, text: str) -> int:
        if not text:
            return 0
        try:
            count = len(self._backend.encode(text, add_special_tokens=False).ids)
        except Exception:
            raise PackError('Local tokenizer could not count the supplied text') from None
        if text.strip() and count == 0:
            raise PackError('Local tokenizer discarded all non-whitespace input')
        return count

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._retained_bytes = self._hits = self._misses = 0

    def cache_info(self) -> dict:
        with self._lock:
            return {'max_bytes': self._cache_bytes, 'retained_bytes': self._retained_bytes,
                    'entries': len(self._cache), 'hits': self._hits, 'misses': self._misses}

    def as_dict(self) -> dict:
        return {'kind': 'local_tokenizer_json', 'asset_sha256': self.sha256,
                'truncation': False, 'padding': False, 'add_special_tokens': False,
                'model_match': 'caller must verify the asset against the target model'}

"""Research challenger: load trusted count records for encountered source text.

The whole bounded index is still captured/hashed/deserialized, not mmaped. Only
source-text hydration is lazy. A trusted build receipt is mandatory; unknown
caches must use the existing explicit full verification path before adoption.
"""
from pathlib import Path
import sqlite3
import tokenizers

from benchmarks.lean_boundary_tokenizer import LeanCompactBoundaryCount
from benchmarks.compact_boundary_tokenizer import decode_record
from benchmarks.compiled_count_index import MAX_BYTES, require_receipt, require_identity, sha
from benchmarks.boundary_selector import BoundarySelector
from npk.pack.format import PackError
from npk.pack.integrity import require_clean_cache

SUPPORTED_ENGINE = '0.22.2'


class LazyCount(LeanCompactBoundaryCount):
    def __init__(self, asset, index, *, expected_digest, cache_bytes=0, prepared_bytes=32*1024*1024):
        super().__init__(asset, cache_bytes=cache_bytes, prepared_bytes=prepared_bytes)
        self._index = None
        self.index_lookups = self.index_hits = self.index_misses = 0
        self.parent_checks = 0
        self.lazy_enabled = self.boundary_enabled and tokenizers.__version__ == SUPPORTED_ENGINE
        with Path(index).open('rb') as stream:
            body = stream.read(MAX_BYTES+1)
        if len(body) > MAX_BYTES: raise PackError('Compiled-count cache exceeds its 64 MiB limit')
        require_receipt(body, expected_digest)
        con = sqlite3.connect(':memory:', check_same_thread=False)
        try:
            con.deserialize(body)
            con.execute('PRAGMA trusted_schema=OFF')
            metadata = require_identity(con, self)
            if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise PackError('Compiled-count cache is corrupt')
            self._owners = dict(con.execute('SELECT file_id,digest FROM owners'))
            self.parent_root = metadata['parent_root']
            self.index_bytes = len(body)
            self.receipt_sha256 = sha(body)
            con.execute('PRAGMA query_only=ON')
        except BaseException as error:
            con.close()
            if isinstance(error, sqlite3.DatabaseError):
                raise PackError('Invalid compiled-count SQLite cache') from None
            raise
        self._index = con

    def require_parent(self, con, manifest):
        # Called inside the selector's existing read transaction, not through a
        # second connection that might observe a different concurrent update.
        with self._lock:
            self._require_open()
            if not con.in_transaction:
                raise PackError('Lazy counts require the selector source snapshot')
            if manifest.get('root_sha256') != self.parent_root:
                raise PackError('Compiled-count cache is stale or belongs to another pack')
            owners = require_clean_cache(con)
            if owners != self._owners: raise PackError('Compiled-count owners differ')
            self.parent_checks += 1

    def _require_open(self):
        if self._index is None: raise PackError('Compiled-count reader is closed')

    def _lookup(self, text):
        self.index_lookups += 1
        return self._index.execute(
            'SELECT chars,prefix_end,suffix_start,tokens,split FROM records WHERE text_sha=?',
            (sha(text.encode('utf-8')),)).fetchone()

    def _hydrate(self, parts):
        pending = []
        for text in dict.fromkeys(parts):
            if text in self._prepared: continue
            values = self._lookup(text)
            if values is None:
                self.index_misses += 1; record = None
            else:
                self.index_hits += 1; record = decode_record(text, values)
            pending.append((text, record))
        # A malformed retrieved record must not partially hydrate the request.
        for text, record in pending: self._admit(text, record)

    def count_parts(self, parts):
        if not isinstance(parts, (list, tuple)) or any(not isinstance(t, str) for t in parts):
            raise TypeError('Context parts must be a list/tuple of text blocks')
        with self._lock:
            self._require_open()
            if not self.lazy_enabled:
                self.fallback_calls += 1
                return self.count('\n\n'.join(parts))
            self._hydrate(parts)
            return super().count_parts(parts)

    def lazy_info(self):
        with self._lock:
            return {'enabled':self.lazy_enabled,'closed':self._index is None,
                    'snapshot_bytes':self.index_bytes,'record_lookups':self.index_lookups,
                    'record_hits':self.index_hits,'record_misses':self.index_misses,
                    'parent_checks':self.parent_checks,'prepared':self.prepared_info()}

    def close(self):
        with self._lock:
            if self._index is not None:
                self._index.close(); self._index = None
            self._prepared.clear(); self._prepared_retained = 0

    def __enter__(self): return self

    def __exit__(self, *args): self.close()


class LazyCountSelector(BoundarySelector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not isinstance(self.tokenizer, LazyCount):
            raise ValueError('An explicit LazyCount reader is required')

    def _select_once(self, con, manifest, query, budget, limit):
        self.tokenizer.require_parent(con, manifest)
        return super()._select_once(con, manifest, query, budget, limit)

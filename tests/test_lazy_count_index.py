"""Attack lazy source hydration with actual SQLite, BPE and concurrent calls."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import sqlite3
import threading
from unittest.mock import patch
import pytest

from benchmarks.lazy_count_index import LazyCount, LazyCountSelector
from benchmarks.compact_boundary_tokenizer import CompactBoundaryCount
from benchmarks.compiled_count_index import update_index
from npk.pack import compile_pack, update_pack, PackSelector, LocalTokenizer
from npk.pack.format import PackError
from tests.test_boundary_tokenizer import pipeline
from tests.test_compiled_count_index import inputs, bodies

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def test_lazy_load_hydrates_only_requested_records_without_compilation(tmp_path, pipeline, monkeypatch):
    codec,asset,_,pack,index,built = inputs(tmp_path,pipeline)
    counter = LazyCount(asset,index,expected_digest=built['receipt_sha256'])
    assert counter.prepared_info()['entries'] == 0
    queries = []; counter._index.set_trace_callback(queries.append)
    calls = []; original = counter._segment
    def tracked(text): calls.append(text); return original(text)
    monkeypatch.setattr(counter,'_segment',tracked)
    parts = bodies(pack)[:1]
    try:
        with patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')):
            assert counter.count_parts(parts) == len(codec.encode('\n\n'.join(parts),add_special_tokens=False))
            again = counter.count_parts(parts)
        assert again > 0 and calls == [] and counter.compiled_parts == 0
        assert counter.prepared_info()['entries'] == counter.index_lookups == 1
        record_queries = [q for q in queries if 'FROM RECORDS' in q.upper()]
        assert len(record_queries) == 1 and 'WHERE TEXT_SHA=' in record_queries[0].upper()
    finally: counter.close()


def test_lazy_missing_text_uses_whole_count_without_hidden_compilation(tmp_path,pipeline,monkeypatch):
    codec,asset,_,pack,index,built = inputs(tmp_path,pipeline)
    with LazyCount(asset,index,expected_digest=built['receipt_sha256']) as counter:
        calls = []; original = counter._segment
        def tracked(text): calls.append(text); return original(text)
        monkeypatch.setattr(counter,'_segment',tracked)
        parts = [bodies(pack)[0],'unknown source v2 /\n\n beta gamma']
        assert counter.count_parts(parts) == len(codec.encode('\n\n'.join(parts),add_special_tokens=False))
        assert counter.index_misses == 1 and counter.fallback_calls == 1 and calls == []


def test_lazy_source_hash_cannot_alias_same_length_text(tmp_path,pipeline):
    codec,asset = pipeline; source = tmp_path/'source'; source.mkdir()
    a,b = 'alpha beta gamma','zzzzz zzzz zzzzz'
    assert len(a) == len(b)
    assert len(codec.encode(a)) != len(codec.encode(b))
    (source/'a.txt').write_text(a); (source/'b.txt').write_text(b)
    pack = tmp_path/'source.npk'; compile_pack(source,pack); index = tmp_path/'counts.sqlite'
    built = update_index(pack,index,CompactBoundaryCount(asset),create=True)
    with LazyCount(asset,index,expected_digest=built['receipt_sha256']) as counter:
        for parts in ([a],[b],[a,b],[b,a]):
            assert counter.count_parts(parts) == len(codec.encode('\n\n'.join(parts),add_special_tokens=False))


@pytest.mark.parametrize('receipt',[None,'0'*64,'not-a-receipt'])
def test_lazy_requires_independent_receipt(tmp_path,pipeline,receipt):
    _,asset,_,_,index,_ = inputs(tmp_path,pipeline)
    rejected = False
    try: LazyCount(asset,index,expected_digest=receipt)
    except PackError: rejected = True
    assert rejected


def test_lazy_record_error_does_not_partially_hydrate(tmp_path,pipeline):
    _,asset,_,pack,index,built = inputs(tmp_path,pipeline)
    parts = bodies(pack)[:2]; assert len(set(parts)) == 2
    with sqlite3.connect(index) as con:
        con.execute('UPDATE records SET tokens=-1 WHERE text_sha=?',(hashlib.sha256(parts[1].encode()).hexdigest(),))
    # A deliberately malformed but freshly bound fixture exercises record
    # validation; recalculating an unknown file's hash is not external trust.
    with LazyCount(asset,index,expected_digest=sha(index)) as counter:
        rejected = False
        try: counter.count_parts(parts)
        except PackError: rejected = True
        assert rejected and counter.prepared_info()['entries'] == 0


def test_lazy_snapshot_ignores_external_index_writes(tmp_path,pipeline):
    codec,asset,_,pack,index,built = inputs(tmp_path,pipeline)
    with LazyCount(asset,index,expected_digest=built['receipt_sha256']) as counter:
        with sqlite3.connect(index) as con: con.execute('UPDATE records SET tokens=tokens+99 WHERE split=1')
        parts = bodies(pack)
        assert counter.count_parts(parts) == len(codec.encode('\n\n'.join(parts),add_special_tokens=False))
    rejected = False
    try: LazyCount(asset,index,expected_digest=built['receipt_sha256'])
    except PackError: rejected = True
    assert rejected


def test_lazy_selector_rejects_stale_cache_after_source_update(tmp_path,pipeline):
    _,asset,source,pack,index,built = inputs(tmp_path,pipeline)
    with LazyCount(asset,index,expected_digest=built['receipt_sha256']) as counter:
        selector = LazyCountSelector(pack,tokenizer=counter)
        assert selector.select('retry_alpha').evidence
        (source/'one.py').write_text('def retry_alpha():\n    return 99001\n')
        update_pack(pack,source)
        rejected = False
        try: selector.select('retry_alpha')
        except PackError: rejected = True
        assert rejected
    updated = update_index(pack,index,CompactBoundaryCount(asset),expected_digest=built['receipt_sha256'])
    with LazyCount(asset,index,expected_digest=updated['receipt_sha256']) as current:
        selected = LazyCountSelector(pack,tokenizer=current).select('retry_alpha')
        assert '99001' in selected.context_text()


def test_lazy_reader_checks_parent_in_same_query_snapshot(tmp_path,pipeline,monkeypatch):
    _,asset,source,pack,index,built = inputs(tmp_path,pipeline)
    module = importlib.import_module('npk.pack.select'); compiler = importlib.import_module('npk.pack.compile')
    lexical,seal = module._lexical_channel,compiler._seal
    ready = threading.Event(); done = threading.Event(); jobs = []
    def signal(con): result = seal(con); ready.set(); return result
    monkeypatch.setattr(compiler,'_seal',signal)
    with LazyCount(asset,index,expected_digest=built['receipt_sha256']) as counter:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def update():
                try: return update_pack(pack,source)
                finally: done.set()
            def interleaved(con,query,limit,*weights):
                ids = lexical(con,query,limit,*weights)
                if not jobs:
                    (source/'one.py').write_text('def retry_alpha():\n    return 99002\n')
                    jobs.append(pool.submit(update)); assert ready.wait(5); done.wait(.15)
                return ids
            monkeypatch.setattr(module,'_lexical_channel',interleaved)
            result = LazyCountSelector(pack,tokenizer=counter).select('retry_alpha',allow_escalation=False)
            jobs[0].result(timeout=5)
        assert result.evidence and '99002' not in result.context_text()
        assert counter.parent_checks == 1


def test_lazy_parallel_requests_and_close_release_cache(tmp_path,pipeline):
    codec,asset,_,pack,index,built = inputs(tmp_path,pipeline)
    counter = LazyCount(asset,index,expected_digest=built['receipt_sha256'],prepared_bytes=1800)
    options = [bodies(pack)[:2],bodies(pack)[1:3],['unknown left','unknown right']]
    expected = [len(codec.encode('\n\n'.join(p),add_special_tokens=False)) for p in options]
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(counter.count_parts,options*10))
    assert actual == expected*10
    assert counter.prepared_info()['accounted_retained_bytes'] <= 1800
    counter.close(); counter.close()
    assert counter.lazy_info()['closed'] and counter.prepared_info()['entries'] == 0
    with pytest.raises(PackError): counter.count_parts(options[0])


def test_lazy_unknown_engine_never_reuses_regions(tmp_path,pipeline,monkeypatch):
    import tokenizers
    codec,asset,_,pack,index,_ = inputs(tmp_path,pipeline)
    # Simulate a future engine identity without claiming to run that engine.
    monkeypatch.setattr(tokenizers,'__version__','0.99.synthetic')
    with sqlite3.connect(index) as con:
        con.execute('UPDATE metadata SET value=? WHERE key=?',('0.99.synthetic','tokenizers_version'))
    with LazyCount(asset,index,expected_digest=sha(index)) as counter:
        parts = bodies(pack)
        assert counter.count_parts(parts) == len(codec.encode('\n\n'.join(parts),add_special_tokens=False))
        assert not counter.lazy_enabled and counter.index_lookups == 0 and counter.fallback_calls == 1

"""Durable integrity invalidation must cover every file-local mutation."""
from contextlib import closing
import hashlib
import importlib
import sqlite3

import pytest

from npk.pack import compile_pack, update_pack, verify
from npk.pack.format import PackError, connect, compute_root_digest


@pytest.fixture
def pack(tmp_path):
    source=tmp_path/"source";source.mkdir()
    (source/"a.py").write_text("LIMIT = 7\ndef run():\n    return LIMIT\n")
    (source/"b.py").write_text("VALUE = 9\ndef other():\n    return VALUE\n")
    target=tmp_path/"project.npk";compile_pack(source,target)
    return source,target


def test_small_edit_rehashes_only_its_file_and_matches_full_verification(pack,monkeypatch):
    source,target=pack
    module=importlib.import_module("npk.pack.integrity")
    original=module.file_digest;calls=[]
    def recorded(con,file_id):calls.append(file_id);return original(con,file_id)
    monkeypatch.setattr(module,"file_digest",recorded)
    (source/"a.py").write_text("LIMIT = 8\ndef run():\n    return LIMIT\n")
    stats=update_pack(target,source)
    assert len(calls)==1 and stats.integrity_files_hashed==1 and stats.integrity_files_reused==1
    calls.clear()
    assert verify(target)["ok"]
    assert len(calls)==2, "full verifier must read every file, not trust the cache"


@pytest.mark.parametrize("sql,affected",[
    ("UPDATE files SET language='changed' WHERE path='a.py'",{"a.py"}),
    ("UPDATE provenance SET source_uri='changed' WHERE file_id=(SELECT id FROM files WHERE path='a.py')",{"a.py"}),
    ("UPDATE blocks SET name='changed' WHERE file_id=(SELECT id FROM files WHERE path='a.py')",{"a.py"}),
    ("DELETE FROM symbols WHERE block_id IN (SELECT id FROM blocks WHERE file_id=(SELECT id FROM files WHERE path='a.py'))",{"a.py"}),
    ("DELETE FROM assignments WHERE block_id IN (SELECT id FROM blocks WHERE file_id=(SELECT id FROM files WHERE path='a.py'))",{"a.py"}),
    ("INSERT INTO embeddings SELECT MIN(id),1,X'00000000' FROM blocks WHERE file_id=(SELECT id FROM files WHERE path='a.py')",{"a.py"}),
    ("UPDATE symbols SET block_id=(SELECT MIN(id) FROM blocks WHERE file_id=(SELECT id FROM files WHERE path='b.py')) WHERE block_id IN (SELECT id FROM blocks WHERE file_id=(SELECT id FROM files WHERE path='a.py'))",{"a.py","b.py"}),
    ("UPDATE blocks SET file_id=(SELECT id FROM files WHERE path='b.py') WHERE file_id=(SELECT id FROM files WHERE path='a.py')",{"a.py","b.py"}),
    ("DELETE FROM files WHERE path='a.py'",{"a.py"}),
    ("UPDATE files SET path='renamed.py' WHERE path='a.py'",{"a.py"}),
])
def test_sql_mutations_invalidate_all_affected_files(pack,sql,affected):
    _,target=pack
    compiler=importlib.import_module("npk.pack.compile")
    with closing(connect(target,readonly=False)) as con:
        original={r['path']:r['id'] for r in con.execute('SELECT id,path FROM files')}
        con.execute(sql)
        dirty={r[0] for r in con.execute('SELECT file_id FROM integrity_dirty')}
        assert {original[path] for path in affected}<=dirty
        compiler._seal(con)
        assert not con.execute('SELECT 1 FROM integrity_dirty').fetchall()
        assert compute_root_digest(con)==dict(con.execute('SELECT key,value FROM manifest'))['root_sha256']
        con.commit()
    result = verify(target)
    # Sealing proves the tracking/digest mechanism, not semantic validity.
    # These two direct SQL mutations deliberately leave metadata inconsistent.
    if sql.startswith('INSERT INTO embeddings'):
        assert not result['ok']
        assert any('incompatible embedding metadata' in e for e in result['errors'])
    elif sql.startswith('DELETE FROM files'):
        assert not result['ok']
        assert any('file_count does not match' in e for e in result['errors'])
    elif sql.startswith('UPDATE blocks SET name'):
        assert not result['ok']
        assert any('source-derived lexical fields' in e for e in result['errors'])
    elif sql.startswith('UPDATE blocks SET file_id') or sql.startswith('UPDATE files SET path'):
        assert not result['ok']
        assert any('lexical path metadata' in e for e in result['errors'])
    else:
        assert result['ok']


def test_corrupt_cache_and_external_unsealed_edits_cannot_be_used_as_an_update_base(pack):
    source,target=pack;before=target.read_bytes()
    for sql in ("UPDATE integrity_files SET digest=zeroblob(32)",
                "DELETE FROM symbols",
                "DROP TRIGGER npk_track_symbols_insert"):
        target.write_bytes(before)
        with sqlite3.connect(target) as con:con.execute(sql)
        corrupted=target.read_bytes()
        (source/'a.py').write_text('LIMIT = 19\n')
        with pytest.raises(PackError):update_pack(target,source)
        assert target.read_bytes()==corrupted
        assert not verify(target)['ok']


def test_full_verifier_does_not_trust_a_cleared_dirty_journal(pack,monkeypatch):
    _,target=pack
    integrity=importlib.import_module('npk.pack.integrity')
    full=integrity.full_file_digests
    calls=[]
    monkeypatch.setattr(integrity,'full_file_digests',
                        lambda con: calls.append(True) or full(con))
    with closing(connect(target,readonly=False)) as con:
        original=con.execute('SELECT text FROM blocks ORDER BY id LIMIT 1').fetchone()[0]
        text=original.replace('7','8')
        assert text!=original and len(text)==len(original)
        con.execute('UPDATE blocks SET text=?,sha256=? WHERE id=(SELECT MIN(id) FROM blocks)',
                    (text,hashlib.sha256(text.encode()).hexdigest()))
        con.execute('DELETE FROM integrity_dirty')
        con.commit()
    assert not verify(target)['ok']
    assert calls, 'full verification must recompute file leaves from actual rows'


def test_failure_after_cache_refresh_rolls_back_data_cache_and_journal(pack,monkeypatch):
    source,target=pack;before=target.read_bytes()
    compiler=importlib.import_module('npk.pack.compile')
    observed=[]
    def fail(con,**kwargs):
        observed.append(con.execute('SELECT COUNT(*) FROM integrity_dirty').fetchone()[0])
        raise RuntimeError('injected seal failure')
    monkeypatch.setattr(compiler,'compute_root_digest',fail)
    (source/'a.py').write_text('LIMIT = 19\n')
    with pytest.raises(RuntimeError,match='injected'):update_pack(target,source)
    assert observed==[0], 'failure must occur after the cache refresh, not before source mutation'
    assert target.read_bytes()==before and verify(target)['ok']


def test_v4_artifacts_require_explicit_recompilation(pack):
    source,target=pack
    with sqlite3.connect(target) as con:con.execute("UPDATE manifest SET value='4' WHERE key='format_version'")
    before=target.read_bytes()
    with pytest.raises(PackError,match='unsupported'):update_pack(target,source)
    assert target.read_bytes()==before


def test_unknown_tables_and_triggers_cannot_hide_unhashed_data(pack):
    _,target=pack;original=target.read_bytes()
    for sql in ('CREATE TABLE untracked(payload TEXT)',
                'CREATE TRIGGER untracked AFTER INSERT ON files BEGIN SELECT 1; END'):
        target.write_bytes(original)
        with sqlite3.connect(target) as con:con.execute(sql)
        result=verify(target)
        assert not result['ok'] and 'unsupported' in ' '.join(result['errors'])


def test_graph_policy_reuses_file_hashes_but_updates_the_global_root(pack):
    source,target=pack;old_root=verify(target)['actual_root_sha256']
    stats=update_pack(target,source,build_deps=True)
    assert stats.integrity_files_hashed==0 and stats.integrity_files_reused==2
    new=verify(target)
    assert new['ok'] and new['actual_root_sha256']!=old_root

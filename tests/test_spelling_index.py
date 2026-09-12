"""Attack research index identity, collisions, literal evidence and updates."""
import hashlib
import shutil
import sqlite3
from unittest.mock import patch
import pytest
from npk.pack import compile_pack,update_pack
from npk.pack.format import open_pack,load_blocks
from benchmarks.spelling_index import update,open_index,canonical_rank,normalized_rank,query_keys,variant_rank


def fixture(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'one.rst').write_text('Use ``retry_backoff_millis`` for the delay.\n')
    (source/'two.rst').write_text('``HTTPStatusCode`` is an enum.\n')
    pack=tmp_path/'source.npk';compile_pack(source,pack);index=tmp_path/'index.sqlite'
    update(pack,index,create=True);return source,pack,index


@pytest.mark.parametrize(('query','expected'),[('retryBackoffMillis','retry_backoff_millis'),('HTTP status code','HTTPStatusCode')])
def test_source_normalization_handles_both_directions(tmp_path,query,expected):
    source,pack,index=fixture(tmp_path)
    with patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')):
        with open_pack(pack) as parent,open_index(index,parent) as con:
            for ids in (normalized_rank(con,query),canonical_rank(con,query)[0],variant_rank(parent,query)):
                assert any(expected in block.text for block in load_blocks(parent,ids))


def test_normalized_collisions_are_exposed_as_spellings_not_identity(tmp_path):
    source,pack,index=fixture(tmp_path)
    (source/'one.rst').write_text('``foo_bar`` is distinct from foobar.\n')
    update_pack(pack,source);update(pack,index)
    with open_pack(pack) as parent,open_index(index,parent) as con:
        ids,observed=canonical_rank(con,'fooBar')
        assert ids and observed==[{'normalized':'foobar','query_views':['fooBar'],'forms':['foo_bar','foobar'],'collision':True}]


def test_stale_index_is_rejected_until_updated(tmp_path):
    source,pack,index=fixture(tmp_path)
    (source/'one.rst').write_text('Use ``new_delay_setting`` now.\n');update_pack(pack,source)
    rejected=False
    with open_pack(pack) as parent:
        try:
            with open_index(index,parent):pass
        except ValueError as error:
            rejected='stale' in str(error)
    assert rejected, 'A stale side index must be rejected before retrieval'
    stats=update(pack,index);assert stats['files_changed']==1 and stats['files_reused']==1
    fresh=tmp_path/'fresh.sqlite';update(pack,fresh,create=True)
    with sqlite3.connect(index) as a,sqlite3.connect(fresh) as b:
        for table in ('metadata','owners','spellings','locations','normalized'):
            assert sorted(a.execute('SELECT * FROM '+table))==sorted(b.execute('SELECT * FROM '+table))
    with open_pack(pack) as parent,open_index(index,parent) as con:
        assert not canonical_rank(con,'retryBackoffMillis')[0]


def test_index_cannot_be_used_with_a_different_pack(tmp_path):
    source,pack,index=fixture(tmp_path)
    (source/'three.rst').write_text('Another artifact.\n');other=tmp_path/'other.npk';compile_pack(source,other)
    with open_pack(other) as parent:
        with pytest.raises(ValueError,match='different'):
            with open_index(index,parent):pass


def test_failed_derivation_rolls_back_existing_index(tmp_path,monkeypatch):
    source,pack,index=fixture(tmp_path);before=index.read_bytes()
    (source/'one.rst').write_text('``replacement_value`` appears.\n');update_pack(pack,source)
    def fail(text):raise RuntimeError('injected failure')
    monkeypatch.setattr('benchmarks.spelling_index.derived',fail)
    with pytest.raises(RuntimeError,match='injected'):update(pack,index)
    assert index.read_bytes()==before


def test_query_views_do_not_concatenate_across_constraints():
    assert 'retrybackoff' in query_keys('retry backoff')
    assert 'retrybackoff' not in query_keys('retry; backoff')
    assert 'retrybackoff' not in query_keys('retry\nbackoff')


def test_side_index_reads_hold_one_snapshot(tmp_path):
    source,pack,index=fixture(tmp_path)
    with open_pack(pack) as parent,open_index(index,parent) as con:
        old=canonical_rank(con,'retryBackoffMillis')
        writer=sqlite3.connect(index,timeout=0)
        try:
            writer.execute("UPDATE metadata SET value='changed' WHERE key='parent_root'")
            with pytest.raises(sqlite3.OperationalError,match='locked'):writer.commit()
            writer.rollback()
        finally:writer.close()
        assert canonical_rank(con,'retryBackoffMillis')==old


def test_normalized_control_does_not_execute_a_discarded_baseline(tmp_path):
    from benchmarks.spelling_index_eval import rank_method
    source,pack,index=fixture(tmp_path)
    with open_pack(pack) as parent:
        with patch('benchmarks.spelling_index_eval._lexical_channel',side_effect=AssertionError('Unnecessary baseline search')):
            ids,signals=rank_method(index,'normalized_index',parent,'retryBackoffMillis',60)
        assert ids and not signals


def test_update_ownership_snapshot_is_taken_under_the_write_lock(tmp_path,monkeypatch):
    """A legal competing update between cache read and lock must not mix states."""
    from benchmarks.spelling_index_updates import equivalent
    source,base,index=fixture(tmp_path)
    targets={}
    for name,file,body in [('a','one.rst','``alpha_setting`` replaces the delay.\n'),
                           ('b','two.rst','``beta_setting`` replaces the enum.\n')]:
        tree=tmp_path/('source_'+name);shutil.copytree(source,tree);(tree/file).write_text(body)
        pack=tmp_path/(name+'.npk');shutil.copyfile(base,pack);update_pack(pack,tree);targets[name]=pack
    real_connect=sqlite3.connect;interleaved=False
    class Connection:
        def __init__(self,inner):self.inner=inner
        def __getattr__(self,name):return getattr(self.inner,name)
        def execute(self,sql,*args):
            nonlocal interleaved
            cursor=self.inner.execute(sql,*args)
            if sql=='SELECT file_id,digest FROM owners':
                rows=list(cursor)
                if not self.inner.in_transaction and not interleaved:
                    interleaved=True
                    update(targets['b'],index)
                return rows
            return cursor
    def connect(path,*args,**kwargs):
        con=real_connect(path,*args,**kwargs)
        return Connection(con) if str(path)==str(index) else con
    with monkeypatch.context() as context:
        context.setattr('benchmarks.spelling_index.sqlite3.connect',connect)
        update(targets['a'],index)
    fresh=tmp_path/'fresh_a.sqlite';update(targets['a'],fresh,create=True)
    equivalent(index,fresh)

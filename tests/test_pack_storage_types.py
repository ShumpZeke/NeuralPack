"""SQLite affinity and self-consistent hashes do not prove runtime value types."""
from contextlib import closing
import hashlib
import importlib
import sqlite3
import pytest
from npk.pack import compile_pack,update_pack,verify,PackSelector
from npk.pack.format import connect,PackError


@pytest.fixture
def pack(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'app.py').write_text(
        'LIMIT = 7\ndef fail():\n    raise CustomError()\n')
    path=tmp_path/'project.npk';compile_pack(source,path)
    return path


def test_blob_block_text_returns_invalid_instead_of_crashing_verification(pack):
    compiler=importlib.import_module('npk.pack.compile')
    body=b'LIMIT = 7'
    with closing(connect(pack,readonly=False)) as con:
        con.execute('UPDATE blocks SET text=?,sha256=?',(body,hashlib.sha256(body).hexdigest()))
        compiler._seal(con);con.commit()
    result=None
    try:result=verify(pack)
    except (AttributeError,TypeError):pass
    assert result is not None and result['ok'] is False,'malformed stored text crashed or passed verification'


@pytest.mark.parametrize('table,column,value',[
    ('files','path',b'app.py'),('files','language',b'python'),('files','size',b'10'),
    ('blocks','tokens',b'3'),('blocks','kind',b'module'),('blocks','name',b'Name'),
    ('symbols','name',b'LIMIT'),('symbols','is_def',b'1'),
    ('relations','kind',b'raises'),
    ('provenance','source_uri',b'app.py'),('assignments','value_hash',b'opaque'),
])
def test_incompatible_value_types_are_invalid_even_with_fresh_hashes(pack,table,column,value):
    compiler=importlib.import_module('npk.pack.compile')
    with closing(connect(pack,readonly=False)) as con:
        changed=con.execute(f'UPDATE {table} SET {column}=?',(value,)).rowcount
        assert changed>0,'fixture did not change a stored row'
        compiler._seal(con);con.commit()
    result=None
    try:result=verify(pack)
    except (AttributeError,TypeError):pass
    assert result is not None and result['ok'] is False,'incompatible stored value crashed or passed verification'


@pytest.mark.parametrize('key', ['mode', 'source_root'])
def test_blob_manifest_is_rejected_before_query_or_verification(pack, key):
    compiler=importlib.import_module('npk.pack.compile')
    with closing(connect(pack,readonly=False)) as con:
        value=con.execute('SELECT value FROM manifest WHERE key=?', (key,)).fetchone()[0]
        con.execute('UPDATE manifest SET value=? WHERE key=?', (value.encode(), key))
        compiler._seal(con);con.commit()
    assert not verify(pack)['ok'],'binary metadata was certified as a valid artifact'
    rejected=False
    try:PackSelector(pack).select('LIMIT')
    except PackError:rejected=True
    assert rejected,'query silently accepted malformed manifest metadata'
    rejected=False
    try:update_pack(pack,pack.parent/'source')
    except PackError:rejected=True
    assert rejected,'update silently accepted malformed manifest metadata'


@pytest.mark.parametrize('failed_statement',['journal_mode','foreign_keys'])
def test_writable_setup_error_closes_connection_and_returns_product_error(pack,monkeypatch,failed_statement):
    module=importlib.import_module('npk.pack.format');original=sqlite3.connect
    opened=[];before=pack.read_bytes()
    class Connection:
        def __init__(self,*args,**kwargs):self.real=original(*args,**kwargs);self.closed=False;opened.append(self)
        def execute(self,sql):
            if failed_statement in sql:raise sqlite3.OperationalError('injected setup failure')
            return self.real.execute(sql)
        def close(self):self.closed=True;self.real.close()
    monkeypatch.setattr(module.sqlite3,'connect',Connection)
    rejected=False
    try:module.connect(pack,readonly=False)
    except PackError:rejected=True
    except sqlite3.DatabaseError:pass
    finally:
        # Inspect before cleanup, then leave the test process free of handles.
        was_closed=bool(opened) and all(c.closed for c in opened)
        for c in opened:
            if not c.closed:c.close()
    assert was_closed,'connection leaked when initialization failed'
    assert rejected,'raw storage failure escaped the product boundary'
    assert pack.read_bytes()==before

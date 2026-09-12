"""An unpublished build must batch schema and tracking DDL with its writes."""
import importlib
from npk.pack import compile_pack,verify


def test_all_schema_and_tracking_creation_share_the_build_transaction(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();(source/'a.py').write_text('LIMIT = 7\n')
    pack=tmp_path/'project.npk'
    compiler=importlib.import_module('npk.pack.compile');original=compiler.connect
    ddl=[]
    def observed(*args,**kwargs):
        con=original(*args,**kwargs)
        def trace(statement):
            # SQLite emits internal FTS CREATE statements with a '-- ' prefix.
            if 'CREATE TABLE' in statement or 'CREATE TRIGGER' in statement or 'CREATE INDEX' in statement:
                ddl.append(con.in_transaction)
        con.set_trace_callback(trace)
        return con
    monkeypatch.setattr(compiler,'connect',observed)
    compile_pack(source,pack)
    assert ddl and all(ddl),'DDL ran outside the single build transaction'
    assert verify(pack)['ok']

"""Attack the experimental cache; it must not be mistaken for a full verifier."""
from contextlib import closing

from benchmarks.integrity_leaves import full_leaves, refreshed, root_digest
from npk.pack import compile_pack
from npk.pack.format import connect


def test_missing_dirty_file_invalidation_is_detected_only_by_full_recomputation(tmp_path):
    source=tmp_path/"src";source.mkdir()
    (source/"a.py").write_text("LIMIT = 7\n")
    (source/"b.py").write_text("VALUE = 9\n")
    pack=tmp_path/"project.npk";compile_pack(source,pack)
    with closing(connect(pack,readonly=False)) as con:
        leaves=full_leaves(con);baseline=root_digest(con,leaves)
        con.execute("UPDATE blocks SET text='LIMIT = 8' WHERE file_id=(SELECT id FROM files WHERE path='a.py')")
        # The live v8 triggers record this direct mutation as dirty. Remove
        # that marker here to model the historical cache failure this
        # experiment is designed to attack: a writer that forgot to invalidate
        # its affected leaf.
        con.execute("DELETE FROM integrity_dirty")
        # A stale cache hides a changed block. This is a reason not to promote
        # a cache-based verifier or incomplete invalidation into the product.
        assert root_digest(con,leaves)==baseline
        actual=root_digest(con,full_leaves(con))
        assert actual!=baseline
        assert root_digest(con,refreshed(con,leaves,{'a.py'}))==actual
        # Global schema and FTS storage must also affect the root. In v8 the
        # hardened connection rejects direct shadow-table writes, so model an
        # index corruption through the public external-content FTS insert surface.
        before=actual
        extra_id=con.execute("SELECT COALESCE(MAX(rowid),0)+1 FROM lexical").fetchone()[0]
        con.execute("INSERT INTO lexical(rowid,text,name,path) VALUES(?,?,?,?)",
                    (extra_id,"corrupted posting","",""))
        assert root_digest(con,refreshed(con,leaves,{'a.py'}))!=before
        con.rollback()


def test_experiment_closes_connections_before_cleaning_its_workspace(tmp_path,monkeypatch):
    import hashlib
    import json
    import sys
    from benchmarks import integrity_leaves as module
    source=tmp_path/"source/click-8.5.0";source.mkdir(parents=True)
    manifest=[]
    for relative in ("src/click/globals.py","src/click/core.py"):
        target=source/relative;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text("VALUE = 7\n")
        manifest.append({"path":relative,"sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
    compile_pack(source,tmp_path/"bm25_windows.npk")
    (tmp_path/"plan.json").write_text(json.dumps({"source_manifest":manifest,"available_tokens":10}))
    connections=[]
    class Tracked:
        def __init__(self,con):self.con=con;self.closed=False
        def __getattr__(self,name):return getattr(self.con,name)
        def __enter__(self):self.con.__enter__();return self
        def __exit__(self,*args):return self.con.__exit__(*args)
        def close(self):self.con.close();self.closed=True
    def tracked_connect(*args,**kwargs):
        result=Tracked(connect(*args,**kwargs));connections.append(result);return result
    monkeypatch.setattr(module,"connect",tracked_connect)
    output=tmp_path/"result.json"
    monkeypatch.setattr(sys,"argv",["experiment","--run",str(tmp_path),"--output",str(output)])
    module.main()
    assert output.exists() and len(connections)==4 and all(c.closed for c in connections)

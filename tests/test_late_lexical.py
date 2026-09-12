import importlib
from npk.pack import compile_pack,update_pack
from npk.pack.format import open_pack
from benchmarks.late_lexical import rank


def test_boundary_ties_updates_and_missing_metadata_match_native(tmp_path):
    source=tmp_path/'source';source.mkdir();pack=tmp_path/'data.npk'
    for i in range(170):(source/f'file{i:03}.py').write_text('SHARED_TOKEN = 7\n')
    (source/'unique.py').write_text('RARE_VALUE = 19\n')
    native=importlib.import_module('npk.pack.select')._lexical_channel
    compile_pack(source,pack)
    for update in (False,True):
        if update:
            (source/'file000.py').write_text('SHARED_TOKEN = 8\n');update_pack(pack,source)
        with open_pack(pack) as con:
            for query in ('SHARED_TOKEN','RARE_VALUE','SHARED_TOKEN RARE_VALUE','zzqqxx'):
                for limit in (1,60,64,65,120,240):
                    assert rank(con,query,limit)==native(con,query,limit)
    # The old join ignores orphan FTS rows. A fast path must keep looking too.
    with open_pack(pack,readonly=False) as con:
        con.execute("INSERT INTO lexical(rowid,text,name,path) VALUES(999999,'RARE_VALUE','','')")
        con.execute("INSERT INTO lexical(lexical,rank) VALUES('rank','bm25(0,100,100,100)')")
        con.commit()
    with open_pack(pack) as con:
        assert rank(con,'RARE_VALUE',1)==native(con,'RARE_VALUE',1)

from types import SimpleNamespace
from benchmarks.hierarchical_seeds import METHODS,build,rank,documents


def test_multiple_files_and_empty_queries_remain_explicit(tmp_path):
    (tmp_path/'one.py').write_text('FIRST_CODE = 7\n')
    (tmp_path/'two.py').write_text('SECOND_CODE = 9\n')
    blocks=[SimpleNamespace(id=i+1,path=name,name=name,ordinal=0,text=(tmp_path/name).read_text())
            for i,name in enumerate(['one.py','two.py'])]
    con=build(tmp_path/'search.sqlite',blocks,tmp_path)
    try:
        for method in METHODS:
            empty,info=rank(con,'zzqqvvxx',method)
            assert empty==[] and info['routed_paths']==[]
        selected,info=rank(con,'FIRST_CODE SECOND_CODE','document_balanced4')
        assert set(selected)=={1,2} and len(info['routed_paths'])==2
        selected,info=rank(con,'FIRST_CODE SECOND_CODE','document_gate1')
        assert len(selected)==1 and len(info['routed_paths'])==1
        assert len(documents(con,'FIRST_CODE SECOND_CODE'))==2
    finally:con.close()

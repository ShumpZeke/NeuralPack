"""A query and an update's integrity preflight must each see one DB snapshot."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import threading

from npk.pack import PackSelector,compile_pack,update_pack,verify


def test_query_cannot_mix_old_candidate_ids_with_a_concurrently_committed_update(tmp_path,monkeypatch):
    source=tmp_path/'src';source.mkdir()
    (source/'a.py').write_text('LIMIT = 7\n')
    (source/'b.py').write_text('OTHER = 8\n')
    pack=tmp_path/'p.npk';compile_pack(source,pack)
    selector=importlib.import_module('npk.pack.select')
    compiler=importlib.import_module('npk.pack.compile')
    lexical=selector._lexical_channel;seal=compiler._seal
    writes_ready=threading.Event();writer_finished=threading.Event();jobs=[]
    def signal_seal(con):
        result=seal(con);writes_ready.set();return result
    monkeypatch.setattr(compiler,'_seal',signal_seal)
    with ThreadPoolExecutor(max_workers=1) as pool:
        def write():
            try:return update_pack(pack,source)
            finally:writer_finished.set()
        def interleaved(con,query,limit):
            ids=lexical(con,query,limit)
            if not jobs:
                (source/'a.py').write_text('LIMIT = 19001\n')
                jobs.append(pool.submit(write))
                assert writes_ready.wait(5)
                # Without a reader transaction the writer commits here. With
                # one it waits until the selector releases its stable snapshot.
                writer_finished.wait(.2)
            return ids
        monkeypatch.setattr(selector,'_lexical_channel',interleaved)
        selection=PackSelector(pack).select('LIMIT',allow_escalation=False)
        jobs[0].result(timeout=5)
    assert not selection.seed_failed
    assert 'LIMIT = 7' in selection.context_text()
    assert '19001' not in selection.context_text()
    assert verify(pack)['ok']


def test_update_validates_its_base_inside_the_write_transaction(tmp_path,monkeypatch):
    source=tmp_path/'src';source.mkdir();path=source/'a.py';path.write_text('LIMIT = 7\n')
    pack=tmp_path/'p.npk';compile_pack(source,pack)
    module=importlib.import_module('npk.pack.compile');original=module.check_cached_base
    observed=[]
    def checked(con,root):
        observed.append(con.in_transaction)
        return original(con,root)
    monkeypatch.setattr(module,'check_cached_base',checked)
    path.write_text('LIMIT = 8\n');update_pack(pack,source)
    assert observed==[True]

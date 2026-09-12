"""An artifact filename must not become SQLite URI parameters or fragments."""
from npk.pack import PackSelector,compile_pack,update_pack,verify
import pytest


@pytest.mark.parametrize('name',['p.npk#branch.npk','p%23branch.npk','p with space.npk','資料.npk'])
def test_artifact_path_is_literal_across_compile_query_update_and_verify(tmp_path,name,monkeypatch):
    source=tmp_path/'source';source.mkdir();file=source/'a.py'
    file.write_text('LIMIT = 19001\n')
    # URI truncation/decoding must not select either plausible sibling.
    for sibling in ('p.npk','p#branch.npk'):compile_pack(source,tmp_path/sibling)
    file.write_text('LIMIT = 7\n');pack=tmp_path/name;compile_pack(source,pack)
    monkeypatch.chdir(tmp_path)
    selected=PackSelector(name).select('LIMIT')
    assert 'LIMIT = 7' in selected.context_text() and '19001' not in selected.context_text()
    assert verify(name)['ok']
    file.write_text('LIMIT = 8\n');update_pack(name,source)
    assert 'LIMIT = 8' in PackSelector(name).select('LIMIT').context_text()
    assert verify(name)['ok']

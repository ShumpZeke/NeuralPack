"""Selected source text must match literal physical source lines and spans."""
import importlib
import pytest
from npk.pack.compile import split_source
from npk.pack import PackSelector,compile_pack,update_pack,verify
from npk.pack.format import connect
from contextlib import closing


@pytest.mark.parametrize('separator',['\u2028','\u2029','\x85','\v','\f'])
def test_unicode_separators_inside_source_strings_are_not_rewritten(separator):
    source="def message():\n    return 'left"+separator+"right'\n\nEND = 7\n"
    blocks=split_source(source,'python')
    assert separator in ''.join(b.text for b in blocks),'source character was erased or rewritten'
    lines=source.split('\n')
    for block in blocks:
        assert block.text=='\n'.join(lines[block.start_line-1:block.end_line])
    function=next(b for b in blocks if b.name=='message')
    assert function.end_line==2 and "right'" in function.text


@pytest.mark.parametrize('language',['python','markdown','text'])
def test_capped_trailing_blank_lines_match_the_reported_span(language,monkeypatch):
    module=importlib.import_module('npk.pack.compile')
    monkeypatch.setattr(module,'MAX_BLOCK_TOKENS',4)
    source='\n'.join(f'VALUE_{i} = {i}' for i in range(22))+'\n\n'
    lines=source.split('\n')
    blocks=split_source(source,language)
    assert blocks
    for block in blocks:
        assert block.text=='\n'.join(lines[block.start_line-1:block.end_line]),'span contains source not present in the block'


@pytest.mark.parametrize('change',[
    'end_line=end_line+1', 'start_line=0', 'start_line=-1',
    'end_line=start_line-1',
])
def test_self_consistent_hashes_do_not_validate_an_impossible_source_span(tmp_path,change):
    source=tmp_path/'source';source.mkdir();(source/'a.py').write_text('LIMIT = 7\n')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    compiler=importlib.import_module('npk.pack.compile')
    with closing(connect(pack,readonly=False)) as con:
        con.execute('UPDATE blocks SET '+change)
        compiler._seal(con);con.commit()
    assert not verify(pack)['ok'],'valid hashes incorrectly certified impossible source spans'


def test_noninteger_source_span_is_rejected_by_artifact_verification(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'a.py').write_text('LIMIT = 7\n')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    with closing(connect(pack,readonly=False)) as con:
        con.execute('UPDATE blocks SET start_line=1.5');con.commit()
    assert not verify(pack)['ok']


def test_compile_update_and_query_preserve_unicode_source_content(tmp_path):
    source=tmp_path/'source';source.mkdir();file=source/'app.py';pack=tmp_path/'project.npk'
    for index,separator in enumerate(('\u2028','\x85')):
        text="def message():\r\n    return 'left"+separator+"right'\r\n"
        file.write_bytes(text.encode('utf-8'))
        if index==0:compile_pack(source,pack)
        else:update_pack(pack,source)
        selected=PackSelector(pack).select('message',budget_tokens=200)
        assert not selected.seed_failed and separator in selected.context_text()
        assert selected.context_text()==text.replace('\r\n','\n').rstrip('\n')
        assert selected.evidence[0].span=='app.py:1-2'
        assert verify(pack)['ok']

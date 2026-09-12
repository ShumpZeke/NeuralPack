"""A directory named build can contain authored documentation or source."""
import importlib
from pathlib import Path
import pytest
from npk.pack import compile_pack,update_pack,verify,PackSelector
from npk.pack.format import open_pack
from benchmarks.compiled_source_contract import require_compiled_sources


@pytest.mark.parametrize('relative',['doc/build/orm/session_basics.rst','build/rules.py'])
def test_build_named_source_is_indexed_updated_and_retrievable(tmp_path,relative):
    root=tmp_path/'source';path=root/relative;path.parent.mkdir(parents=True)
    text='IMPORTANT_LIMIT = 19\n';path.write_text(text)
    artifact=tmp_path/'project.npk';stats=compile_pack(root,artifact)
    assert stats.files_indexed==1 and stats.blocks>0 and verify(artifact)['ok']
    selected=PackSelector(artifact).select('IMPORTANT_LIMIT')
    assert text.strip() in selected.context_text() and selected.evidence[0].path==relative
    path.write_text(text.replace('19','23'));update_pack(artifact,root)
    assert 'IMPORTANT_LIMIT = 23' in PackSelector(artifact).select('IMPORTANT_LIMIT').context_text()
    assert verify(artifact)['ok']


@pytest.mark.parametrize('partial',[False,True])
def test_valid_artifact_cannot_substitute_for_expected_corpus(tmp_path,partial):
    import hashlib
    root=tmp_path/'source';root.mkdir();body=b'IMPORTANT = 7\n'
    if partial:(root/'included.py').write_bytes(body)
    artifact=tmp_path/'project.npk';compile_pack(root,artifact);assert verify(artifact)['ok']
    expected=[{'path':'omitted.py','sha256':hashlib.sha256(body).hexdigest()}]
    if partial:expected.append({'path':'included.py','sha256':hashlib.sha256(body).hexdigest()})
    try:require_compiled_sources(artifact,expected)
    except ValueError:pass
    else:assert False,'A valid but incomplete artifact was accepted as the intended corpus'


def test_new_scan_rules_require_recompilation_before_incremental_update(tmp_path,monkeypatch):
    module=importlib.import_module('npk.pack.compile');root=tmp_path/'source';root.mkdir()
    (root/'ordinary.py').write_text('VALUE = 1\n');artifact=tmp_path/'old.npk'
    current=module.COMPILER_VERSION
    with monkeypatch.context() as old:
        old.setattr(module,'COMPILER_VERSION','5.2');compile_pack(root,artifact)
    assert current!='5.2'
    before=artifact.read_bytes()
    from npk.pack.format import PackError
    with pytest.raises(PackError,match='recompile'):update_pack(artifact,root)
    assert artifact.read_bytes()==before

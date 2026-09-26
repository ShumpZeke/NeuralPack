"""An incomplete source scan must not publish a complete-looking artifact."""
import errno
import os
from pathlib import Path

import pytest

from npk.pack import PackSelector, compile_pack, update_pack, verify
from npk.pack.format import PackError


@pytest.fixture
def source_pack(tmp_path):
    root=tmp_path/"source"
    sub=root/"nested";sub.mkdir(parents=True)
    path=sub/"settings.py"
    path.write_text("IMPORTANT_LIMIT = 19\n",encoding="utf-8")
    (root/"other.py").write_text("OTHER = 3\n",encoding="utf-8")
    pack=tmp_path/"project.npk"
    compile_pack(root,pack)
    return root,path,pack


@pytest.mark.parametrize("operation",["compile","update"])
@pytest.mark.parametrize("failure",["read","stat","directory"])
def test_incomplete_scan_preserves_prior_artifact(source_pack,monkeypatch,operation,failure):
    root,path,pack=source_pack
    before=pack.read_bytes()
    if failure=="directory":
        original=os.scandir
        def denied(p):
            # Linux shutil.rmtree scans directory file descriptors (ints).
            if not isinstance(p,int) and Path(p)==path.parent:
                raise PermissionError(errno.EACCES,"synthetic inaccessible directory",str(p))
            return original(p)
        monkeypatch.setattr(os,"scandir",denied)
    else:
        method="read_bytes" if failure=="read" else "stat"
        original=getattr(Path,method)
        def denied(p,*args,**kwargs):
            if p==path:
                raise PermissionError(errno.EACCES,"synthetic inaccessible file",str(p))
            return original(p,*args,**kwargs)
        monkeypatch.setattr(Path,method,denied)
    try:
        if operation=="compile":
            compile_pack(root,pack)
        else:
            update_pack(pack,root)
    except PackError:
        pass
    else:
        assert False,"incomplete scan was published as a successful artifact"
    assert pack.read_bytes()==before
    assert verify(pack)["ok"]
    assert "IMPORTANT_LIMIT = 19" in PackSelector(pack).select("IMPORTANT_LIMIT").context_text()


def test_invalid_utf8_cannot_silently_change_source_meaning(source_pack):
    root,path,pack=source_pack
    before=pack.read_bytes()
    path.write_bytes(b'ACCOUNT = "adm\xffin"\n')
    try:update_pack(pack,root)
    except PackError as error:message=str(error)
    else:message=None
    assert message is not None and "UTF-8" in message,"indexed evidence was silently dropped"
    assert pack.read_bytes()==before


def test_oversized_text_cannot_look_like_a_deliberate_deletion(source_pack,monkeypatch):
    import importlib
    module=importlib.import_module("npk.pack.compile")
    root,path,pack=source_pack
    before=pack.read_bytes()
    monkeypatch.setattr(module,"MAX_FILE_BYTES",100)
    path.write_text("IMPORTANT_LIMIT = 19\n"+"# more source\n"*10,encoding="utf-8")
    with pytest.raises(PackError,match="size limit"):
        update_pack(pack,root)
    assert pack.read_bytes()==before


def test_deliberate_removal_still_removes_evidence(source_pack):
    root,path,pack=source_pack
    path.unlink()
    assert update_pack(pack,root).files_removed==1
    assert PackSelector(pack).select("IMPORTANT_LIMIT").seed_failed
    assert verify(pack)["ok"]


def test_excluded_directory_is_not_read_or_treated_as_an_error(source_pack,monkeypatch):
    root,path,pack=source_pack
    excluded=root/".git";excluded.mkdir()
    original=os.scandir
    def denied(p):
        if Path(p)==excluded:
            raise AssertionError("excluded directory was opened")
        return original(p)
    monkeypatch.setattr(os,"scandir",denied)
    before=pack.read_bytes()
    update_pack(pack,root)
    assert pack.read_bytes()==before


@pytest.mark.parametrize("failure",["encoding","size","nul"])
def test_initial_compile_reports_and_skips_unindexable_source(tmp_path,monkeypatch,failure):
    import importlib
    module=importlib.import_module("npk.pack.compile")
    root=tmp_path/"source";root.mkdir()
    body={"encoding":b'VALUE = "x\xffy"\n',"size":b"VALUE = 123\n"*30,"nul":b"VALUE = 1\x00\n"}[failure]
    (root/"settings.py").write_bytes(body)
    (root/"ok.py").write_text("GOOD = 1\n",encoding="utf-8")
    monkeypatch.setattr(module,"MAX_FILE_BYTES",100)
    reason={"encoding":"non_utf8","size":"oversize","nul":"nul"}[failure]
    # Strict mode keeps the fail-closed contract and publishes nothing.
    strict=tmp_path/"strict.npk"
    with pytest.raises(PackError):
        compile_pack(root,strict,strict=True)
    assert not strict.exists()
    # The default build indexes everything else and names what it left out.
    pack=tmp_path/"project.npk"
    try:stats=compile_pack(root,pack)
    except PackError:stats=None
    assert stats is not None,"one unindexable file aborted the whole build"
    assert stats.skipped_sources==[{"path":"settings.py","reason":reason}]
    assert stats.files_indexed==1 and verify(pack)["ok"]
    import json
    from npk.pack.format import open_pack,read_manifest
    with open_pack(pack) as con:
        assert json.loads(read_manifest(con)["skipped_sources"])==stats.skipped_sources
    assert "GOOD = 1" in PackSelector(pack).select("GOOD").context_text()
    assert list(tmp_path.glob(".npk-build-*"))==[]


def test_update_records_new_unindexable_files_without_touching_evidence(source_pack):
    root,path,pack=source_pack
    (root/"blob.txt").write_bytes(b"binary\x00payload")
    stats=update_pack(pack,root)
    assert stats.skipped_sources==[{"path":"blob.txt","reason":"nul"}]
    assert stats.files_indexed==0 and verify(pack)["ok"]
    import json
    from npk.pack.format import open_pack,read_manifest
    with open_pack(pack) as con:
        assert json.loads(read_manifest(con)["skipped_sources"])==stats.skipped_sources
    (root/"blob.txt").unlink()
    assert update_pack(pack,root).skipped_sources==[]
    with open_pack(pack) as con:
        assert read_manifest(con)["skipped_sources"]=="[]"
    assert verify(pack)["ok"]

"""Source screening must fail explicitly, without deleting or leaking content."""
from pathlib import Path
import os
import sqlite3
import pytest
from npk.pack import compile_pack,update_pack,verify
from npk.pack.format import PackError


@pytest.fixture
def existing(tmp_path):
    source=tmp_path/'source';source.mkdir()
    file=source/'app.py';file.write_text('LIMIT = 7\n')
    pack=tmp_path/'project.npk';compile_pack(source,pack)
    return source,file,pack


@pytest.mark.parametrize('operation',['compile','update'])
@pytest.mark.parametrize('kind',['nvidia','openai','aws','github','private_key'])
def test_credential_shaped_source_is_never_published(existing,kind,operation):
    source,file,pack=existing;before=pack.read_bytes()
    # Obviously synthetic runtime fixtures; never a literal credential on disk
    # in tracked source. The transient input is rejected, not silently redacted.
    values={'nvidia':'nvapi-'+'A'*64,'openai':'sk-proj-'+'B'*80,
            'aws':'AKIA'+'C'*16,'github':'ghp_'+'D'*36,
            'private_key':'-----BEGIN '+'PRIVATE KEY-----\n'+'E'*40}
    value=values[kind];file.write_text('VALUE = '+repr(value)+'\n')
    if operation=='compile':
        # A fresh build never indexed this file: it is skipped and reported,
        # and the credential never reaches the published artifact or report.
        stats=compile_pack(source,pack)
        assert stats.skipped_sources==[{'path':'app.py','reason':'credential'}]
        assert value not in repr(stats.as_dict())
        assert value.encode() not in pack.read_bytes() and verify(pack)['ok']
        with pytest.raises(PackError,match='credential') as error:
            compile_pack(source,pack.with_name('strict.npk'),strict=True)
        assert value not in str(error.value)
        assert not pack.with_name('strict.npk').exists()
    else:
        # An indexed file that becomes unindexable must not lose evidence silently.
        with pytest.raises(PackError,match='credential') as error:
            update_pack(pack,source)
        assert value not in str(error.value)
        assert pack.read_bytes()==before and verify(pack)['ok']
    assert file.read_text()=='VALUE = '+repr(value)+'\n'


@pytest.mark.parametrize('offset',[0,9000])
def test_nul_in_eligible_source_cannot_silently_remove_evidence(existing,offset):
    source,file,pack=existing;before=pack.read_bytes()
    file.write_bytes(b'# padding\n'*(offset//10)+b'LIMIT = 7\x00\n')
    with pytest.raises(PackError,match='NUL'):update_pack(pack,source)
    assert pack.read_bytes()==before


def test_file_change_during_read_cannot_publish_inconsistent_metadata(existing,monkeypatch):
    source,file,pack=existing;before=pack.read_bytes();original=Path.read_bytes
    def unstable(path):
        data=original(path)
        if path==file:file.write_text('LIMIT = 19001\n')
        return data
    monkeypatch.setattr(Path,'read_bytes',unstable)
    with pytest.raises(PackError,match='changed during'):update_pack(pack,source)
    assert pack.read_bytes()==before


def test_same_size_change_during_read_cannot_publish_stale_text(existing,monkeypatch):
    source,file,pack=existing;before=pack.read_bytes();original=Path.read_bytes
    def unstable(path):
        data=original(path)
        if path==file:
            st=file.stat();file.write_text('LIMIT = 8\n')
            os.utime(file,ns=(st.st_atime_ns,st.st_mtime_ns+1_000_000_000))
        return data
    monkeypatch.setattr(Path,'read_bytes',unstable)
    rejected=False
    try:update_pack(pack,source)
    except PackError as error:rejected='changed during' in str(error)
    assert rejected,'same-sized concurrent source edit was silently accepted'
    assert pack.read_bytes()==before


def test_missing_pack_update_must_not_create_an_empty_artifact(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'a.py').write_text('LIMIT = 7\n')
    pack=tmp_path/'absent.npk'
    rejected=False
    try:update_pack(pack,source)
    except PackError:rejected=True
    except (sqlite3.DatabaseError,OSError):pass  # Distinguish raw storage errors from an explicit product error.
    assert rejected and not pack.exists(),'missing-pack update created an empty database or gave an unclassified failure'


def test_source_symlink_cannot_read_outside_the_requested_root(existing,tmp_path):
    source,file,pack=existing;before=pack.read_bytes()
    outside=tmp_path/'outside.py';outside.write_text('OUTSIDE_LIMIT = 123\n')
    link=source/'alias.py'
    try:link.symlink_to(outside)
    except OSError:pytest.skip('host does not permit symlink creation')
    with pytest.raises(PackError,match='outside'):update_pack(pack,source,strict=True)
    assert pack.read_bytes()==before
    # Default: the link is never followed; it is skipped and reported.
    stats=update_pack(pack,source)
    assert stats.skipped_sources==[{'path':'alias.py','reason':'outside_root'}]
    assert b'OUTSIDE_LIMIT' not in pack.read_bytes() and verify(pack)['ok']


def test_mock_external_resolution_is_rejected_before_source_read(existing,tmp_path,monkeypatch):
    source,file,pack=existing;before=pack.read_bytes()
    original_resolve=Path.resolve;original_read=Path.read_bytes;reads=[]
    def resolved(path,*args,**kwargs):
        if path==file:return tmp_path/'external.py'
        return original_resolve(path,*args,**kwargs)
    def read(path):
        if path==file:reads.append(path)
        return original_read(path)
    monkeypatch.setattr(Path,'resolve',resolved);monkeypatch.setattr(Path,'read_bytes',read)
    with pytest.raises(PackError,match='outside'):update_pack(pack,source)
    assert not reads and pack.read_bytes()==before


def test_credential_shaped_path_is_not_embedded_or_echoed(existing):
    source,file,pack=existing;before=pack.read_bytes()
    value='nvapi-'+'A'*64
    (source/(value+'.py')).write_text('LIMIT = 19\n')
    with pytest.raises(PackError) as caught:update_pack(pack,source)
    assert value not in str(caught.value)
    assert pack.read_bytes()==before


def test_descriptive_placeholders_and_bearer_documentation_remain_usable(existing):
    source,file,pack=existing
    body='KEY = "not-a-credential"\n# Set an Authorization: Bearer example header\nLIMIT = 19\n'
    file.write_text(body)
    update_pack(pack,source)
    from npk.pack import PackSelector
    assert 'LIMIT = 19' in PackSelector(pack).select('LIMIT').context_text()
    assert verify(pack)['ok']

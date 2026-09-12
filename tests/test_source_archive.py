"""A recorded source file must survive archiving regardless of its suffix."""
import hashlib
import pytest
from benchmarks.source_archive import manifest_sources


def test_manifest_files_cannot_be_dropped_by_extension(tmp_path):
    bodies={'pyproject.toml':b'[project]\nname="synthetic"\n','schema.unusual':b'Synthetic source\n'}
    manifest=[]
    for name,body in bodies.items():
        (tmp_path/name).write_bytes(body);manifest.append({'path':name,'sha256':hashlib.sha256(body).hexdigest()})
    assert manifest_sources(tmp_path,manifest,'public-source')=={'public-source/'+k:v for k,v in bodies.items()}


def test_changed_source_is_rejected_before_archive_publication(tmp_path):
    (tmp_path/'file.toml').write_bytes(b'Changed synthetic source')
    with pytest.raises(ValueError):manifest_sources(tmp_path,[{'path':'file.toml','sha256':'0'*64}],'source')


@pytest.mark.parametrize('path',['../outside.toml','C:/outside.toml','folder\\outside.toml'])
def test_manifest_cannot_read_outside_its_source_root(tmp_path,path):
    with pytest.raises(ValueError):manifest_sources(tmp_path,[{'path':path,'sha256':'0'*64}],'source')


def test_duplicate_source_paths_are_rejected(tmp_path):
    body=b'Synthetic';(tmp_path/'source.txt').write_bytes(body)
    item={'path':'source.txt','sha256':hashlib.sha256(body).hexdigest()}
    with pytest.raises(ValueError):manifest_sources(tmp_path,[item,item],'source')

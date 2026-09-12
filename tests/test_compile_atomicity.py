"""Failed rebuilds must preserve a previously usable compiled artifact."""
import importlib

import pytest

from npk.pack import PackSelector, compile_pack
from npk.pack.format import PackError, verify


@pytest.fixture
def existing_pack(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "settings.py").write_text("RETRY_LIMIT = 7\n", encoding="utf-8")
    pack = tmp_path / "project.npk"
    compile_pack(root, pack)
    return root, pack, pack.read_bytes()


def test_missing_source_preserves_existing_artifact(existing_pack):
    root, pack, original = existing_pack
    with pytest.raises(PackError):
        compile_pack(root / "missing", pack)
    assert pack.exists()
    assert pack.read_bytes() == original


def test_compile_failure_preserves_existing_artifact(existing_pack, monkeypatch):
    root, pack, original = existing_pack
    module = importlib.import_module("npk.pack.compile")
    original_writer = module._write_file_blocks

    def fail_after_writing(*args):
        original_writer(*args)
        raise RuntimeError("injected compilation failure")

    monkeypatch.setattr(module, "_write_file_blocks", fail_after_writing)
    with pytest.raises(RuntimeError, match="injected"):
        compile_pack(root, pack)
    assert pack.read_bytes() == original
    assert verify(pack)["ok"]
    assert {p.name for p in pack.parent.iterdir()} == {"src", "project.npk"}


def test_successful_rebuild_replaces_existing_artifact(existing_pack):
    root, pack, original = existing_pack
    (root / "settings.py").write_text("RETRY_LIMIT = 19\n", encoding="utf-8")
    compile_pack(root, pack)
    assert pack.read_bytes() != original
    assert verify(pack)["ok"]
    result = PackSelector(pack).select("RETRY_LIMIT")
    assert "19" in result.context_text()
    assert "= 7" not in result.context_text()


def test_output_cannot_overwrite_a_source_file(existing_pack):
    root, _, _ = existing_pack
    source_file = root / "settings.py"
    original = source_file.read_bytes()
    with pytest.raises(PackError, match="source file"):
        compile_pack(root, source_file)
    assert source_file.read_bytes() == original


def test_active_sidecar_blocks_replacement_without_data_loss(existing_pack):
    root, pack, original = existing_pack
    sidecar = pack.with_name(pack.name + "-wal")
    sidecar.write_bytes(b"synthetic-active-writer")
    with pytest.raises(PackError, match="sidecars"):
        compile_pack(root, pack)
    assert pack.read_bytes() == original
    assert sidecar.read_bytes() == b"synthetic-active-writer"

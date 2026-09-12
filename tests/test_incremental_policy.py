"""Incremental updates must preserve configuration and do no work on no change."""
import importlib

import pytest

from npk.pack import compile_pack, update_pack, verify
from npk.pack.format import open_pack, read_manifest


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "config.py").write_text("RETRY_LIMIT = 7\n", encoding="utf-8")
    (root / "app.py").write_text("def run():\n    return RETRY_LIMIT\n", encoding="utf-8")
    return root


def deps(pack):
    with open_pack(pack) as con:
        return con.execute("SELECT COUNT(*) FROM deps").fetchone()[0]


def test_default_does_not_build_unused_graph(source, tmp_path, monkeypatch):
    module = importlib.import_module("npk.pack.compile")

    def forbidden(*args):
        raise AssertionError("default compiler built an unused graph")

    monkeypatch.setattr(module, "_build_deps", forbidden)
    compile_pack(source, tmp_path / "default.npk")


@pytest.mark.parametrize("enabled", [False, True])
def test_update_preserves_compiled_dependency_policy(source, tmp_path, enabled):
    pack = tmp_path / "test.npk"
    compile_pack(source, pack, build_deps=enabled)
    (source / "extra.py").write_text("def more():\n    return RETRY_LIMIT\n", encoding="utf-8")
    update_pack(pack, source)
    assert (deps(pack) > 0) is enabled
    with open_pack(pack) as con:
        assert read_manifest(con)["dependency_index"] == str(int(enabled))
    assert verify(pack)["ok"]


def test_explicit_policy_change_applies_without_source_changes(source, tmp_path):
    pack = tmp_path / "test.npk"
    compile_pack(source, pack, build_deps=False)
    update_pack(pack, source, build_deps=True)
    assert deps(pack) > 0
    update_pack(pack, source, build_deps=False)
    assert deps(pack) == 0
    assert verify(pack)["ok"]


def test_no_change_update_is_byte_identical_and_does_not_rehash(source, tmp_path, monkeypatch):
    pack = tmp_path / "test.npk"
    compile_pack(source, pack)
    before = pack.read_bytes()
    module = importlib.import_module("npk.pack.compile")

    def forbidden(*args):
        raise AssertionError("no-change update rehashed the full artifact")

    monkeypatch.setattr(module, "compute_root_digest", forbidden)
    result = update_pack(pack, source)
    assert result.files_indexed == result.files_removed == 0
    assert result.files_skipped_unchanged == 2
    assert pack.read_bytes() == before
    assert verify(pack)["ok"]

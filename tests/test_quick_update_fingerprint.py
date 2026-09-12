"""Contracts for optional stat-fingerprinted fast updates vs strict content-hash updates."""
from contextlib import closing
import importlib
from pathlib import Path
import pytest

from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import connect, open_pack


@pytest.fixture
def repo(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.py").write_text("LIMIT = 10\ndef get_limit(): return LIMIT\n", encoding="utf-8")
    (source / "b.py").write_text("TIMEOUT = 20\ndef get_timeout(): return TIMEOUT\n", encoding="utf-8")
    artifact = tmp_path / "project.npk"
    compile_pack(source, artifact)
    return source, artifact


def test_quick_update_skips_reading_untouched_files(repo, monkeypatch):
    source, artifact = repo
    # Update with quick=True without any changes
    read_calls = []
    original_read = Path.read_bytes

    def tracked_read(self):
        read_calls.append(self.name)
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    stats = update_pack(artifact, source, quick=True)
    assert stats.files_indexed == 0
    assert stats.files_skipped_unchanged == 2
    assert read_calls == [], f"quick update read untouched files from disk: {read_calls}"
    assert verify(artifact)["ok"]


def test_quick_update_detects_and_reindexes_modified_files(repo):
    source, artifact = repo
    # Modify a.py
    (source / "a.py").write_text("LIMIT = 999\ndef get_limit(): return LIMIT\n", encoding="utf-8")
    stats = update_pack(artifact, source, quick=True)
    assert stats.files_indexed == 1
    assert stats.files_skipped_unchanged == 1
    assert verify(artifact)["ok"]
    # Verify search finds the new value
    sel = PackSelector(artifact).select("LIMIT", budget_tokens=512)
    assert "999" in sel.context_text()


def test_quick_update_produces_identical_evidence_to_strict_update(repo, tmp_path):
    source, artifact = repo
    # Create twin artifact for strict update
    strict_pack = tmp_path / "strict.npk"
    import shutil
    shutil.copyfile(artifact, strict_pack)
    # Modify one file and add a new one
    (source / "a.py").write_text("LIMIT = 42\n", encoding="utf-8")
    (source / "new.py").write_text("NEW_VAL = 100\n", encoding="utf-8")

    stats_quick = update_pack(artifact, source, quick=True)
    stats_strict = update_pack(strict_pack, source, quick=False)

    assert stats_quick.files_indexed == stats_strict.files_indexed == 2
    assert stats_quick.files_skipped_unchanged == stats_strict.files_skipped_unchanged == 1
    assert verify(artifact)["actual_root_sha256"] == verify(strict_pack)["actual_root_sha256"]

    for q in ("LIMIT", "TIMEOUT", "NEW_VAL"):
        s_quick = PackSelector(artifact).select(q, budget_tokens=512)
        s_strict = PackSelector(strict_pack).select(q, budget_tokens=512)
        assert s_quick.context_text() == s_strict.context_text()
        assert [e.span for e in s_quick.evidence] == [e.span for e in s_strict.evidence]


def test_quick_parameter_type_validation(repo):
    source, artifact = repo
    with pytest.raises(ValueError, match="quick must be a boolean"):
        update_pack(artifact, source, quick="not_a_bool")

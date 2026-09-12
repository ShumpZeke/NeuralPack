"""Artifact corruption must not pass by leaving stored hash labels unchanged."""
from contextlib import closing
import sqlite3

import pytest

from npk.pack import PackSelector, compile_pack, update_pack
from npk.pack.format import PackError, connect, open_pack, load_blocks, verify
from npk.pack.compile import estimate_tokens


@pytest.fixture
def compiled(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text("from settings import RETRY_LIMIT\ndef run():\n    return RETRY_LIMIT\n", encoding="utf-8")
    (source / "settings.py").write_text("RETRY_LIMIT = 7\n", encoding="utf-8")
    pack = tmp_path / "project.npk"
    compile_pack(source, pack, build_deps=True)
    return source, pack


@pytest.mark.parametrize("mutation", [
    "UPDATE blocks SET text='RETRY_LIMIT = 9000' WHERE id=(SELECT MIN(id) FROM blocks)",
    "UPDATE files SET language='wrong'",
    "DELETE FROM symbols",
    "DELETE FROM deps",
    "DELETE FROM assignments",
    "UPDATE provenance SET source_uri='wrong.py'",
    "UPDATE lexical SET text='misleading search text', name='', path='' WHERE rowid=(SELECT MIN(rowid) FROM lexical)",
    "UPDATE lexical_data SET block=CAST(block || x'00' AS BLOB) WHERE id=(SELECT MAX(id) FROM lexical_data)",
    "UPDATE manifest SET value='999999' WHERE key='block_count'",
    "UPDATE manifest SET value='different-source' WHERE key='source_root'",
    "INSERT INTO embeddings(block_id,dim,vector) SELECT MIN(id),1,x'00000000' FROM blocks",
])
def test_modified_contents_or_indexes_fail_verification(compiled, mutation):
    _, pack = compiled
    assert verify(pack)["ok"]
    with sqlite3.connect(pack) as con:
        con.execute(mutation)
    assert verify(pack)["ok"] is False


def test_resealed_fts_postings_must_match_authoritative_blocks(compiled):
    """A self-consistent posting tree cannot replace source-derived fields."""
    _, pack = compiled
    from npk.pack.compile import _seal

    con = connect(pack, readonly=False)
    try:
        con.execute("BEGIN")
        rowid = con.execute("SELECT rowid FROM lexical ORDER BY rowid LIMIT 1").fetchone()[0]
        con.execute(
            "UPDATE lexical SET text='totally bogus posting' WHERE rowid=?",
            (rowid,),
        )
        _seal(con)
        con.commit()
    finally:
        con.close()

    result = verify(pack)
    assert result["ok"] is False
    assert any("source-derived lexical fields" in error for error in result["errors"])


def test_resealed_fts_document_lengths_must_match_authoritative_blocks(compiled):
    """BM25 document statistics are source data, not trusted shadow bytes."""
    _, pack = compiled
    from npk.pack.compile import _seal

    with closing(sqlite3.connect(pack)) as raw:
        raw.execute("UPDATE lexical_docsize SET sz=x'0001'")
        raw.commit()
    con = connect(pack, readonly=False)
    try:
        con.execute("BEGIN")
        _seal(con)
        con.commit()
    finally:
        con.close()

    result = verify(pack)
    assert result["ok"] is False
    assert any("document-length" in error for error in result["errors"])


def test_truncated_artifact_is_reported_as_invalid(compiled):
    _, pack = compiled
    pack.write_bytes(pack.read_bytes()[:1024])
    result = verify(pack)
    assert result["ok"] is False
    assert result["errors"]


def test_available_tokens_match_joined_source_after_update(compiled):
    source, pack = compiled
    for change in ("", "# unicode: 漢字 and 😺\nEXTRA_VALUE = 123\n"):
        if change:
            (source / "new.py").write_text(change, encoding="utf-8")
            update_pack(pack, source)
        with open_pack(pack) as con:
            blocks = load_blocks(con)
        expected = estimate_tokens("\n\n".join(b.text for b in blocks))
        assert PackSelector(pack).select("RETRY_LIMIT").available_tokens == expected


@pytest.mark.parametrize("version", ["0", "-1", "2", "999"])
def test_unsupported_versions_are_rejected(compiled, version):
    _, pack = compiled
    with sqlite3.connect(pack) as con:
        con.execute("UPDATE manifest SET value=? WHERE key='format_version'", (version,))
    with pytest.raises(PackError):
        PackSelector(pack).select("RETRY_LIMIT")


def test_trusted_root_detects_replaced_self_recorded_root(compiled):
    import hashlib
    from npk.pack.format import compute_root_digest
    _, pack = compiled
    trusted = verify(pack)["actual_root_sha256"]
    with sqlite3.connect(pack) as con:
        con.row_factory = sqlite3.Row
        replacement = "RETRY_LIMIT = 9000"
        con.execute("UPDATE blocks SET text=?,sha256=? WHERE id=(SELECT MIN(id) FROM blocks)",
                    (replacement, hashlib.sha256(replacement.encode()).hexdigest()))
        from npk.pack.integrity import refresh_file_digests
        refresh_file_digests(con)
        root = compute_root_digest(con)
        con.execute("UPDATE manifest SET value=? WHERE key='root_sha256'", (root,))
    # A self-recorded root is not publisher authentication. Pin a trusted root.
    result = verify(pack, expected_root=trusted)
    assert result["ok"] is False
    assert "artifact does not match trusted expected root" in result["errors"]


def test_verification_is_read_only_and_survives_vacuum(compiled):
    _, pack = compiled
    before = pack.read_bytes()
    assert verify(pack)["ok"]
    assert pack.read_bytes() == before
    with sqlite3.connect(pack) as con:
        con.execute("VACUUM")
    assert verify(pack)["ok"]


def test_failed_update_rolls_back_contents_and_integrity_together(compiled, monkeypatch):
    import importlib
    source, pack = compiled
    before = pack.read_bytes()
    (source / "settings.py").write_text("RETRY_LIMIT = 19\n", encoding="utf-8")
    module = importlib.import_module("npk.pack.compile")

    def interrupted(con,**kwargs):
        raise RuntimeError("injected digest failure")

    monkeypatch.setattr(module, "compute_root_digest", interrupted)
    with pytest.raises(RuntimeError, match="injected"):
        update_pack(pack, source)
    assert pack.read_bytes() == before
    assert verify(pack)["ok"]
    assert "RETRY_LIMIT = 7" in PackSelector(pack).select("RETRY_LIMIT").context_text()

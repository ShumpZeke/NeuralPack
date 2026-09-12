"""Contracts for separate search metadata fields in external-content FTS5.

Cycle 36: body, path, and definition names are analyzed into independent fields.
blocks.text remains the untouched source of truth for evidence emission.
"""
from contextlib import closing

import pytest

from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import connect, open_pack


@pytest.fixture
def corpus(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "utils").mkdir()
    (source / "utils" / "helpers.py").write_text(
        "def calculate_score(items):\n"
        "    return sum(i.value for i in items)\n"
        "\n"
        "MAX_RETRIES = 5\n",
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        "from utils.helpers import calculate_score\n"
        "\n"
        "def run():\n"
        "    print(calculate_score([]))\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "project.npk"
    compile_pack(source, artifact)
    return source, artifact


def test_lexical_fields_remain_separate_in_external_content_index(corpus):
    """Each indexed field remains independently searchable without source copies."""
    _, artifact = corpus
    with open_pack(artifact) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM lexical WHERE lexical MATCH ?", ('text : calculate_score',)
        ).fetchone()[0] >= 1
        assert con.execute(
            "SELECT COUNT(*) FROM lexical WHERE lexical MATCH ?", ('name : calculate_score',)
        ).fetchone()[0] >= 1
        assert con.execute(
            "SELECT COUNT(*) FROM lexical WHERE lexical MATCH ?", ('path : helpers',)
        ).fetchone()[0] >= 1


def test_blocks_text_is_clean_source(corpus):
    """blocks.text must remain the exact source text, never polluted by metadata."""
    _, artifact = corpus
    with open_pack(artifact) as con:
        for row in con.execute("SELECT text FROM blocks"):
            text = row["text"]
            assert not text.startswith("utils "), (
                "blocks.text must not contain path metadata"
            )


def test_path_based_query_finds_evidence(corpus):
    """Querying a path segment should retrieve blocks from that file."""
    _, artifact = corpus
    sel = PackSelector(str(artifact))
    result = sel.select("helpers", budget_tokens=2000)
    assert result.evidence, "path-based query 'helpers' should find evidence"
    paths = {e.path for e in result.evidence}
    assert "utils/helpers.py" in paths, (
        "path query should include utils/helpers.py"
    )


def test_definition_name_has_its_own_search_field(corpus):
    """Definition names should appear only in the dedicated name field."""
    _, artifact = corpus
    with open_pack(artifact) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM lexical WHERE lexical MATCH ?", ('name : calculate_score',)
        ).fetchone()[0] >= 1


def test_verify_passes_with_metadata_fields(corpus):
    """verify() must pass with metadata-enriched lexical fields."""
    _, artifact = corpus
    v = verify(artifact)
    assert v["ok"], f"verification failed: {v['errors']}"


def test_update_preserves_metadata_fields(corpus):
    """Incremental update should regenerate metadata fields correctly."""
    source, artifact = corpus
    (source / "main.py").write_text(
        "from utils.helpers import calculate_score\n"
        "\n"
        "def run_v2():\n"
        "    return calculate_score([])\n",
        encoding="utf-8",
    )
    update_pack(artifact, source)
    v = verify(artifact)
    assert v["ok"], f"verification failed after update: {v['errors']}"
    with open_pack(artifact) as con:
        assert con.execute("SELECT COUNT(*) FROM lexical").fetchone()[0] == con.execute(
            "SELECT COUNT(*) FROM blocks"
        ).fetchone()[0]


def test_evidence_text_does_not_contain_metadata(corpus):
    """Selected evidence text must be clean source, not metadata-enriched."""
    _, artifact = corpus
    sel = PackSelector(str(artifact))
    result = sel.select("calculate_score", budget_tokens=2000)
    assert result.evidence
    for e in result.evidence:
        assert not e.text.startswith("utils "), (
            "evidence text should not contain path metadata"
        )
        assert not e.text.startswith("main "), (
            "evidence text should not contain path metadata"
        )

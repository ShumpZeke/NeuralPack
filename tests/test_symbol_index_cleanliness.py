"""Contracts for language-aware symbol extraction and index cleanliness."""
from contextlib import closing
import keyword
import sqlite3

import pytest

from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import connect, open_pack
from npk.pack.select import STOPWORDS


@pytest.fixture
def corpus(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text(
        "import os\n"
        "MAX_RETRIES = 5\n"
        "def process_item(item):\n"
        "    for x in range(item):\n"
        "        if x > 0:\n"
        "            return x + MAX_RETRIES\n"
        "    return None\n",
        encoding="utf-8",
    )
    (source / "guide.md").write_text(
        "# User Guide\n\n"
        "This is a comprehensive explanation of how things work.\n"
        "You can configure the system for optimal retry behavior.\n\n"
        "```python\n"
        "def helper(): return 42\n"
        "```\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "project.npk"
    compile_pack(source, artifact)
    return source, artifact


def test_keywords_and_stopwords_are_not_indexed_as_references(corpus):
    _, artifact = corpus
    with open_pack(artifact) as con:
        symbols = dict(con.execute("SELECT name, max(is_def) FROM symbols GROUP BY name").fetchall())
        # Definitions must exist
        assert "process_item" in symbols and symbols["process_item"] == 1
        assert "MAX_RETRIES" in symbols and symbols["MAX_RETRIES"] == 1
        # Code keywords must NOT be indexed as references
        for kw in ("def", "return", "for", "if", "in", "None", "import"):
            assert kw not in symbols, f"Python keyword {kw!r} was indexed as a symbol"
        # Stop words must NOT be indexed as references
        for sw in ("the", "this", "and", "how", "for", "with", "you"):
            assert sw not in symbols, f"Stopword {sw!r} was indexed as a symbol"


def test_prose_files_do_not_emit_bare_word_symbol_references(corpus):
    _, artifact = corpus
    with open_pack(artifact) as con:
        prose_refs = con.execute(
            "SELECT s.name FROM symbols s JOIN blocks b ON b.id=s.block_id "
            "JOIN files f ON f.id=b.file_id WHERE s.is_def=0 AND f.language='markdown'"
        ).fetchall()
        assert prose_refs == [], f"prose file emitted bare word symbol references: {prose_refs}"


def test_code_definitions_are_strictly_preserved(corpus):
    _, artifact = corpus
    with open_pack(artifact) as con:
        defs = {r[0] for r in con.execute("SELECT name FROM symbols WHERE is_def=1").fetchall()}
        assert "process_item" in defs
        assert "MAX_RETRIES" in defs
        assert "User Guide" in defs  # Section heading definition preserved


def test_symbol_index_contains_definitions_only(corpus):
    _, artifact = corpus
    with open_pack(artifact) as con:
        assert con.execute("SELECT COUNT(*) FROM symbols WHERE is_def=0").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] >= 3


def test_incremental_update_maintains_clean_symbols(corpus):
    source, artifact = corpus
    # Update a file and verify symbols remain clean
    (source / "app.py").write_text(
        "MAX_RETRIES = 10\n"
        "def process_item(item):\n"
        "    return item * 2\n",
        encoding="utf-8",
    )
    update_pack(artifact, source)
    assert verify(artifact)["ok"]
    with open_pack(artifact) as con:
        symbols = dict(con.execute("SELECT name, max(is_def) FROM symbols GROUP BY name").fetchall())
        assert "process_item" in symbols and symbols["process_item"] == 1
        assert "MAX_RETRIES" in symbols and symbols["MAX_RETRIES"] == 1
        assert "def" not in symbols
        assert "return" not in symbols
        prose_refs = con.execute(
            "SELECT s.name FROM symbols s JOIN blocks b ON b.id=s.block_id "
            "JOIN files f ON f.id=b.file_id WHERE s.is_def=0 AND f.language='markdown'"
        ).fetchall()
        assert prose_refs == []

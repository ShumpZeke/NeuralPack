"""Contracts for batched block, index, and assignment insertion per file."""
from contextlib import closing
import importlib
import sqlite3

import pytest

from npk.pack import compile_pack, verify
from npk.pack.format import connect, open_pack


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    # Multi-block file with constants, classes, functions, and duplicate symbols
    (source / "module.py").write_text(
        "TIMEOUT = 30\n"
        "RETRIES = 3\n"
        "class Handler:\n"
        "    def handle(self):\n"
        "        TIMEOUT = 60\n"
        "        return TIMEOUT\n"
        "def helper():\n"
        "    return RETRIES\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "out.npk"
    compile_pack(source, artifact)
    return source, artifact


def test_batched_insertion_preserves_all_blocks_lexical_and_symbols(project):
    _, artifact = project
    assert verify(artifact)["ok"]
    with open_pack(artifact) as con:
        block_count = con.execute("SELECT count(*) FROM blocks").fetchone()[0]
        lexical_count = con.execute("SELECT count(*) FROM lexical").fetchone()[0]
        assert block_count == lexical_count and block_count >= 3

        # External-content FTS5 keeps postings separate from source text. The
        # rowid is the block key and
        # every source block must have exactly one indexed document.
        indexed = {row[0] for row in con.execute("SELECT rowid FROM lexical")}
        blocks = {row[0] for row in con.execute("SELECT id FROM blocks")}
        assert indexed == blocks
        assert con.execute(
            "SELECT COUNT(*) FROM lexical WHERE lexical MATCH ?", ('text : timeout',)
        ).fetchone()[0] >= 1

        # Verify symbols are mapped to correct block IDs
        syms = con.execute("SELECT s.name, s.block_id, b.name FROM symbols s JOIN blocks b ON b.id=s.block_id WHERE s.is_def=1").fetchall()
        assert len(syms) >= 3
        def_names = {r[0] for r in syms}
        assert "TIMEOUT" in def_names and "RETRIES" in def_names and "helper" in def_names


def test_executemany_called_with_batched_lists(project, monkeypatch):
    source, _ = project
    compiler = importlib.import_module("npk.pack.compile")
    executemany_calls = []
    original_connect = compiler.connect

    class ConnectionWrapper:
        def __init__(self, real):
            self._real = real
        def __getattr__(self, name):
            return getattr(self._real, name)
        def executemany(self, sql, seq_of_params):
            params = list(seq_of_params)
            executemany_calls.append((sql, len(params)))
            return self._real.executemany(sql, params)

    def tracked_connect(*args, **kwargs):
        con = original_connect(*args, **kwargs)
        return ConnectionWrapper(con)

    monkeypatch.setattr(compiler, "connect", tracked_connect)
    target = source.parent / "tracked.npk"
    compiler.compile_pack(source, target)
    assert verify(target)["ok"]
    # Verify that executemany was called with multi-item sequences rather than 1 per block
    lex_calls = [c for c in executemany_calls if "INSERT INTO lexical" in c[0]]
    sym_calls = [c for c in executemany_calls if "INSERT INTO symbols" in c[0]]
    assert len(lex_calls) == 1, "lexical insert was not batched per file"
    assert lex_calls[0][1] >= 3, "lexical insert did not batch all blocks together"
    assert len(sym_calls) == 1, "symbols insert was not batched per file"

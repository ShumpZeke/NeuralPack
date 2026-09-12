"""Security hardening, zero legacy-context drag, and query throughput contracts."""
from contextlib import closing
import importlib
import sqlite3
import sys

import pytest

from npk.pack import compile_pack, PackSelector, verify
from npk.pack.format import (SQLITE_MAX_STATEMENT_BYTES, SQLITE_MAX_VALUE_BYTES,
                             connect, open_pack)
from npk.pack.compile import _available_tokens


@pytest.fixture
def pack(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "mod.py").write_text(
        "# Unicode: 漢字 and 🚀\n"
        "def process_data(value):\n"
        "    \"\"\"Process a retry policy with special characters.\"\"\"\n"
        "    return value + 42\n",
        encoding="utf-8",
    )
    (source / "settings.py").write_text("RETRY_LIMIT = 5\n", encoding="utf-8")
    artifact = tmp_path / "test.npk"
    compile_pack(source, artifact)
    return source, artifact


def test_available_tokens_sql_aggregation_matches_python_loop_exactly(pack):
    _, artifact = pack
    with open_pack(artifact) as con:
        # Verify that SQL length and count match Python string counting
        count_py, chars_py = 0, 0
        for row in con.execute("SELECT text FROM blocks"):
            count_py += 1
            chars_py += len(row["text"])
        expected = max(1, (chars_py + max(0, count_py - 1) * 2) // 4) if count_py else 0
        actual = _available_tokens(con)
        assert actual == expected


def test_connect_enforces_query_only_and_trusted_schema_defense(pack):
    _, artifact = pack
    # Readonly connection
    con_ro = connect(artifact, readonly=True)
    try:
        assert con_ro.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        assert con_ro.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con_ro.execute("CREATE TABLE malicious(x TEXT)")
    finally:
        con_ro.close()

    # Writable connection
    con_rw = connect(artifact, readonly=False)
    try:
        assert con_rw.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        assert con_rw.execute("PRAGMA query_only").fetchone()[0] == 0
        assert con_rw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        con_rw.close()


def test_connect_bounds_untrusted_sqlite_values_and_statements(pack):
    _, artifact = pack
    con = connect(artifact, readonly=True)
    try:
        assert con.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == SQLITE_MAX_VALUE_BYTES
        assert con.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH) == SQLITE_MAX_STATEMENT_BYTES
        if hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
            assert con.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE) == 1
    finally:
        con.close()


def test_query_does_not_import_legacy_context_modules(pack):
    _, artifact = pack
    # Execute in a fresh process to verify module import boundaries strictly
    import subprocess
    code = (
        "import sys, pathlib\n"
        "from npk.pack import PackSelector\n"
        f"p = pathlib.Path({repr(str(artifact))})\n"
        "res = PackSelector(p).select('retry policy', budget_tokens=512)\n"
        "assert not res.seed_failed\n"
        "context_mods = [m for m in sys.modules if m.startswith('npk.context')]\n"
        "assert not context_mods, f'context modules imported: {context_mods}'\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, f"Subprocess failed: {proc.stderr}"


def test_pack_selector_context_manager_reuses_connection_and_releases_locks(pack, tmp_path):
    source, artifact = pack
    # Reused connection in context manager
    with PackSelector(artifact) as selector:
        q1 = selector.select("retry policy", budget_tokens=512)
        q2 = selector.select("process_data", budget_tokens=512)
        assert not q1.seed_failed and not q2.seed_failed
        # Selections must match standalone unmanaged query identically
        standalone = PackSelector(artifact).select("retry policy", budget_tokens=512)
        assert q1.context_text() == standalone.context_text()
        assert q1.total_tokens == standalone.total_tokens
        assert [e.span for e in q1.evidence] == [e.span for e in standalone.evidence]
        assert selector._con is not None

    # After context exit, connection must be closed and file lock released
    assert selector._con is None
    # Compile/replace should succeed without WinError 5
    (source / "mod.py").write_text("def new_process(): return 99\n")
    compile_pack(source, artifact)
    assert verify(artifact)["ok"]
import builtins

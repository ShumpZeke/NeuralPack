"""Adversarial updates: bounded SQL, rowid identity and atomic index changes."""
from contextlib import closing
import importlib
import sqlite3

import pytest

from benchmarks.update_batch_audit import compare_indexes
from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import connect
from npk.pack.search import analyzed_text


def assert_index_matches_blocks(path):
    with closing(connect(path)) as con:
        blocks = {r[0]: r[1] for r in con.execute("SELECT id, text FROM blocks")}
        lexical = {r[0] for r in con.execute("SELECT rowid FROM lexical")}
        assert set(blocks) == lexical, "index lost, duplicated or retained obsolete source"


@pytest.mark.parametrize("operation", ["replace_large_file", "remove_large_file", "replace_many_files"])
def test_update_does_not_require_one_sql_parameter_per_block(tmp_path, monkeypatch, operation):
    source = tmp_path / "source"
    source.mkdir()
    if operation == "replace_many_files":
        for i in range(60):
            (source / f"p{i}.py").write_text(f"OLD_{i} = {i}\n")
    else:
        (source / "large.py").write_text("\n".join(f"def old_{i}():\n    return {i}\n" for i in range(60)))
    target = tmp_path / "base.npk"
    compile_pack(source, target)
    for path in source.iterdir():
        if operation == "remove_large_file":
            path.unlink()
        else:
            path.write_text("REPLACEMENT = 73\n")
    compiler = importlib.import_module("npk.pack.compile")
    original = compiler.connect
    def limited(*args, **kwargs):
        con = original(*args, **kwargs)
        con.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 32)
        return con
    monkeypatch.setattr(compiler, "connect", limited)
    failure = None
    try:
        update_pack(target, source)
    except sqlite3.OperationalError as error:
        failure = str(error)
    assert failure is None, f"ordinary update exceeded SQLite's variable budget: {failure}"
    assert verify(target)["ok"]
    assert_index_matches_blocks(target)


def test_direct_drop_file_does_not_require_one_parameter_per_block(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.py").write_text("\n".join(f"def func_{i}():\n    return {i}\n" for i in range(100)))
    target = tmp_path / "target.npk"
    compile_pack(source, target)
    compiler = importlib.import_module("npk.pack.compile")
    with closing(connect(target, readonly=False)) as con:
        con.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 10)
        file_id = con.execute("SELECT id FROM files WHERE path='large.py'").fetchone()[0]
        compiler._drop_file(con, file_id)
        compiler._set_manifest(con, {"file_count": 0, "block_count": 0, "available_tokens": 0})
        compiler._seal(con)
        con.commit()
    assert verify(target)["ok"]
    assert_index_matches_blocks(target)


@pytest.mark.parametrize("rounds", [1, 5])
def test_mixed_updates_keep_index_identity(tmp_path, rounds):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("a", "b", "c", "empty"):
        (source / f"{name}.py").write_text("" if name == "empty" else f"{name.upper()}_OLD = 1\n")
    target = tmp_path / "base.npk"
    compile_pack(source, target)
    compiler = importlib.import_module("npk.pack.compile")
        # Format v8 uses the block ID as the external-content FTS rowid.
    with closing(connect(target, readonly=False)) as con:
        rows = list(con.execute(
            "SELECT b.id,b.text,b.name,f.path FROM blocks b JOIN files f ON f.id=b.file_id"
        ))
        con.execute("DELETE FROM lexical")
        con.executemany("INSERT INTO lexical(rowid,text,name,path) VALUES(?,?,?,?)",
                        [(row[0], analyzed_text(row[1]), analyzed_text(row[2] or ""),
                          analyzed_text(row[3].rsplit('.', 1)[0])) for row in rows])
        compiler._seal(con)
        con.commit()
    assert verify(target)["ok"]
    for i in range(rounds):
        (source / "a.py").write_text(f"A_NEW = {i}\n")
        (source / "b.py").unlink(missing_ok=True)
        (source / "empty.py").write_text(f"EMPTY_NEW = {i}\n")
        (source / f"added{i}.py").write_text(f"ADDED_NEW = {i}\n")
        update_pack(target, source)
        assert verify(target)["ok"]
        assert_index_matches_blocks(target)
        fresh = tmp_path / f"fresh{i}.npk"
        compile_pack(source, fresh)
        assert compare_indexes(target, fresh) > 0
        for query in ("A_OLD", "A_NEW", "B_OLD", "C_OLD", "EMPTY_NEW", "ADDED_NEW"):
            a, b = [PackSelector(p).select(query, budget_tokens=512) for p in (target, fresh)]
            assert a.context_text() == b.context_text()
            assert [x.span for x in a.evidence] == [x.span for x in b.evidence]


def test_failure_after_lexical_removal_rolls_back_every_byte(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text("BEFORE_VALUE = 1\n")
    target = tmp_path / "base.npk"
    compile_pack(source, target)
    before = target.read_bytes()
    (source / "a.py").write_text("AFTER_VALUE = 2\n")
    compiler = importlib.import_module("npk.pack.compile")
    observed = []
    def fail(con, *args, **kwargs):
        observed.append(con.execute("SELECT count(*) FROM lexical").fetchone()[0])
        raise RuntimeError("injected after index removal")
    monkeypatch.setattr(compiler, "_write_file_blocks", fail)
    with pytest.raises(RuntimeError, match="injected after index removal"):
        update_pack(target, source)
    assert observed == [0]
    assert target.read_bytes() == before and verify(target)["ok"]

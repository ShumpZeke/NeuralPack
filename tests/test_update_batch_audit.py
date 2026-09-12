"""Index acceptance must inspect postings, not only the stored content column."""
from contextlib import closing
import shutil
import sqlite3

import pytest

from benchmarks.update_batch_audit import compare_indexes
from benchmarks.update_batch_eval import logical_digest
from npk.pack import compile_pack
from npk.pack.compile import _drop_lexical
from npk.pack.format import connect


@pytest.fixture
def pair(tmp_path):
    source = tmp_path/"source"
    source.mkdir()
    (source/"a.py").write_text("ORIGINAL_TERM = 'alpha beta gamma'\n")
    actual = tmp_path/"actual.npk"
    expected = tmp_path/"expected.npk"
    compile_pack(source, actual)
    shutil.copyfile(actual, expected)
    return actual, expected


def test_index_audit_accepts_distinct_rowids_with_identical_search_content(pair):
    actual, expected = pair
    with closing(sqlite3.connect(actual)) as con:
        con.execute("DELETE FROM lexical")
        # Rebuild from the source blocks using the same normalized fields as
        # the external-content compiler path.
        from npk.pack.search import analyzed_text
        source_rows = list(con.execute(
            "SELECT b.id,b.text,b.name,f.path FROM blocks b JOIN files f ON f.id=b.file_id"
        ))
        con.executemany(
            "INSERT INTO lexical(rowid,text,name,path) VALUES(?,?,?,?)",
            [(row[0], analyzed_text(row[1]), analyzed_text(row[2] or ""),
              analyzed_text(row[3].rsplit('.', 1)[0])) for row in source_rows],
        )
        con.commit()
    assert compare_indexes(actual, expected) > 0


def test_index_audit_rejects_changed_postings(pair):
    actual, expected = pair
    with closing(sqlite3.connect(actual)) as con:
        # External-content FTS5 permits a complete-row update. The source
        # blocks remain unchanged, so the independent posting audit must catch
        # the index-only mutation.
        con.execute(
            "UPDATE lexical SET text='unrelated replacement words', name='', path='' "
            "WHERE rowid=(SELECT MIN(rowid) FROM lexical)"
        )
        con.commit()
    with pytest.raises(AssertionError, match="posting|positions|count"):
        compare_indexes(actual, expected)


def test_index_audit_rejects_changed_document_lengths(pair):
    actual, expected = pair
    with closing(sqlite3.connect(actual)) as con:
        con.execute("UPDATE lexical_docsize SET sz=x'0001'")
        con.commit()
    with pytest.raises(AssertionError, match="lengths"):
        compare_indexes(actual, expected)


def test_empty_deleted_index_and_new_empty_index_have_equivalent_totals(pair, tmp_path):
    actual, _ = pair
    source = tmp_path/"empty_source"
    source.mkdir()
    expected = tmp_path/"empty.npk"
    compile_pack(source, expected)
    with closing(connect(actual, readonly=False)) as con:
        file_ids = [row[0] for row in con.execute("SELECT id FROM files")]
        _drop_lexical(con, file_ids)
        con.execute("DELETE FROM blocks")
        con.commit()
    assert compare_indexes(actual, expected) == 0


def test_logical_audit_has_a_linear_scale_work_budget(tmp_path):
    source = tmp_path/"source"
    source.mkdir()
    (source/"many.py").write_text("\n".join(f"def f_{i}():\n    return {i}\n" for i in range(1000)))
    path = tmp_path/"many.npk"
    compile_pack(source, path)
    with closing(sqlite3.connect(path)) as con:
        ticks = 0
        def bounded():
            nonlocal ticks
            ticks += 1
            return ticks > 1000
        # A generous million-opcode envelope. A per-block FTS scan needs
        # several million even on this small fixture; wall time is not asserted.
        con.set_progress_handler(bounded, 1000)
        failure = None
        try:
            result = logical_digest(con)
        except sqlite3.OperationalError as error:
            failure = str(error)
        assert failure is None, f"index acceptance exhausted its SQL work budget: {failure}"
        assert len(result) == 6

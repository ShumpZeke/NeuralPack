"""Format-v8 contracts for external-content fielded retrieval and raise seeds."""
from contextlib import closing
import sqlite3
from unittest.mock import patch

import pytest

from npk.pack import PACK_FORMAT_VERSION, PackSelector, compile_pack, update_pack, verify
from npk.pack.format import connect, open_pack
from npk.pack.search import analyzed_text
from npk.pack.select import _lexical_terms


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "handlers").mkdir()
    (source / "handlers" / "retry_policy.py").write_text(
        "class RetryPolicy:\n"
        "    def validate(self, value):\n"
        "        if value < 0:\n"
        "            raise RetryLimitError(value)\n"
        "        return value\n",
        encoding="utf-8",
    )
    for index in range(80):
        (source / f"filler_{index}.py").write_text(
            f"FILLER_{index} = {index}\n", encoding="utf-8"
        )
    artifact = tmp_path / "project.npk"
    compile_pack(source, artifact, python_members=True)
    return source, artifact


def test_format_eight_uses_external_content_separate_search_fields(project):
    _, artifact = project
    assert PACK_FORMAT_VERSION == 8
    with open_pack(artifact) as con:
        columns = [row[1] for row in con.execute("PRAGMA table_info(lexical)")]
        assert columns == ["text", "name", "path"]
        sql = con.execute("SELECT sql FROM sqlite_schema WHERE name='lexical'").fetchone()[0]
        assert "content='blocks'" in sql and "content_rowid='id'" in sql
        row = con.execute(
            "SELECT rowid FROM lexical WHERE lexical MATCH ?",
            ('name : retrypolicy AND name : validate AND path : handlers',),
        ).fetchone()
        assert row is not None
        assert con.execute(
            "SELECT name FROM blocks WHERE id=?", (row[0],)
        ).fetchone()[0] == "RetryPolicy.validate"


def test_fielded_index_never_pollutes_emitted_source(project):
    _, artifact = project
    result = PackSelector(artifact).select("RetryPolicy validate", budget_tokens=300)
    assert result.evidence
    assert all("handlers retry policy" not in item.text for item in result.evidence)
    assert "class RetryPolicy:" in result.context_text()


def test_path_and_absent_camel_alias_are_locally_searchable(project):
    _, artifact = project
    with patch("socket.socket.connect", side_effect=AssertionError("unexpected network")):
        path_result = PackSelector(artifact).select("handlers retry policy", budget_tokens=300)
        alias_result = PackSelector(artifact).select("retryLimitError", budget_tokens=300)
    assert path_result.evidence[0].path == "handlers/retry_policy.py"
    assert "raise RetryLimitError" in alias_result.context_text()
    assert not path_result.used_generative_llm and not alias_result.used_generative_llm


def test_explicit_raise_intent_adds_a_relation_channel(project):
    _, artifact = project
    result = PackSelector(artifact).select(
        "Under what conditions is RetryLimitError raised?", budget_tokens=300
    )
    assert result.evidence
    assert "relation" in result.channels_used
    assert "raise RetryLimitError" in result.context_text()
    assert any("relation" in item.channels for item in result.evidence)


@pytest.mark.parametrize("query", [
    "Where is RetryLimitError caught?",
    "Where is RetryLimitError not raised?",
    "Mention the literal string RetryLimitError without raising it.",
    "What does BaseException mean for exc_type?",
])
def test_ambiguous_or_negative_language_suppresses_relation_seed(project, query):
    _, artifact = project
    result = PackSelector(artifact).select(query, budget_tokens=300)
    assert "relation" not in result.channels_used


def test_update_removes_obsolete_relation_and_matches_fresh_build(project, tmp_path):
    source, artifact = project
    path = source / "handlers" / "retry_policy.py"
    path.write_text(
        "class RetryPolicy:\n"
        "    def validate(self, value):\n"
        "        if value < 0:\n"
        "            raise ValueError(value)\n"
        "        return value\n",
        encoding="utf-8",
    )
    update_pack(artifact, source)
    fresh = tmp_path / "fresh.npk"
    compile_pack(source, fresh, python_members=True)
    assert verify(artifact)["ok"] and verify(fresh)["ok"]
    with open_pack(artifact) as con:
        rows = [tuple(row) for row in con.execute(
            "SELECT f.path,b.ordinal,r.kind,r.name FROM relations r "
            "JOIN blocks b ON b.id=r.block_id JOIN files f ON f.id=b.file_id "
            "ORDER BY f.path,b.ordinal,r.kind,r.name"
        )]
    with open_pack(fresh) as con:
        expected = [tuple(row) for row in con.execute(
            "SELECT f.path,b.ordinal,r.kind,r.name FROM relations r "
            "JOIN blocks b ON b.id=r.block_id JOIN files f ON f.id=b.file_id "
            "ORDER BY f.path,b.ordinal,r.kind,r.name"
        )]
    assert rows == expected
    assert not any(row[-1] == "retrylimiterror" for row in rows)
    assert any(row[-1] == "valueerror" for row in rows)


def test_incremental_bm25_scores_match_a_clean_rebuild(project, tmp_path):
    """External-content FTS keeps normalization stable after block replacement."""
    source, artifact = project
    (source / "filler_0.py").write_text(
        "FILLER_0 = 900\n# unrelated update changes the FTS corpus statistics\n",
        encoding="utf-8",
    )
    update_pack(artifact, source)
    fresh = tmp_path / "fresh.npk"
    compile_pack(source, fresh, python_members=True)

    def scores(path, query):
        with open_pack(path) as con:
            terms = _lexical_terms(con, query)
            match = " OR ".join(f'"{term}"' for term in terms)
            return [
                (row["path"], row["ordinal"], row["score"])
                for row in con.execute(
                    "SELECT f.path,b.ordinal,bm25(lexical,1.0,1.0,1.0) score "
                    "FROM lexical JOIN blocks b ON b.id=lexical.rowid "
                    "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
                    "ORDER BY bm25(lexical,1.0,1.0,1.0),f.path COLLATE BINARY,b.ordinal",
                    (match,),
                )
            ]

    for query in ("retry validate", "raise exception", "filler"):
        assert scores(artifact, query) == scores(fresh, query)


def test_relation_rows_are_covered_by_full_verification(project):
    _, artifact = project
    assert verify(artifact)["ok"]
    with closing(connect(artifact, readonly=False)) as con:
        con.execute("UPDATE relations SET name=zeroblob(4)")
        con.commit()
    result = verify(artifact)
    assert not result["ok"]
    assert result["errors"]


def test_nonselective_raise_name_is_not_a_relation_channel(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(4):
        (source / f"module_{index}.py").write_text(
            f"def run_{index}():\n    raise ValueError({index})\n", encoding="utf-8"
        )
    artifact = tmp_path / "project.npk"
    compile_pack(source, artifact)
    result = PackSelector(artifact).select("Where is ValueError raised?", budget_tokens=300)
    assert result.evidence
    assert "relation" not in result.channels_used


def test_fts_rowid_is_the_verified_block_identity(project):
    source, artifact = project
    with closing(connect(artifact, readonly=False)) as con:
        rows = list(con.execute(
            "SELECT b.id,b.text,b.name,f.path FROM blocks b JOIN files f ON f.id=b.file_id"
        ))
        con.execute("DELETE FROM lexical")
        con.executemany(
            "INSERT INTO lexical(rowid,text,name,path) VALUES(?,?,?,?)",
            [(row[0], analyzed_text(row[1]), analyzed_text(row[2] or ""),
              analyzed_text(row[3].rsplit(".", 1)[0])) for row in rows],
        )
        from npk.pack.compile import _seal
        _seal(con)
        con.commit()
    (source / "filler_0.py").write_text("FILLER_0 = 900\n", encoding="utf-8")
    update_pack(artifact, source)
    assert verify(artifact)["ok"]
    assert "900" in PackSelector(artifact).select("FILLER_0", budget_tokens=100).context_text()

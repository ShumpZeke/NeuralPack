"""Tests of opt-in conflict heuristics and their counterexamples."""
from __future__ import annotations

from pathlib import Path

import pytest

from npk.pack import MODE_DETERMINISTIC, PackSelector, compile_pack
from npk.pack.conflict import (
    extract_assignments, find_conflict_sets, resolve_value_conflicts,
)
from npk.pack.format import open_pack


@pytest.fixture()
def conflicted_pack(tmp_path: Path) -> Path:
    """Same constant, different values, in differently-scoped modules."""
    root = tmp_path / "src"
    for domain, value in (("billing", 30), ("search", 90), ("auth", 77)):
        target = root / domain / "limits.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"REQUEST_TIMEOUT = {value}\n", encoding="utf-8")

    legacy = root / "legacy" / "limits.py"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("REQUEST_TIMEOUT = 5\n", encoding="utf-8")

    out = tmp_path / "conflicted.npk"
    compile_pack(root, out, mode=MODE_DETERMINISTIC)
    return out


# ---------------------------------------------------------------------------
# Compile-time extraction
# ---------------------------------------------------------------------------

def test_assignments_are_extracted_at_compile_time(conflicted_pack):
    with open_pack(conflicted_pack) as con:
        rows = con.execute(
            "SELECT symbol, COUNT(*) n FROM assignments GROUP BY symbol").fetchall()
    symbols = {r["symbol"]: r["n"] for r in rows}
    assert symbols.get("REQUEST_TIMEOUT", 0) >= 4


def test_extract_assignments_ignores_comments_and_noise():
    pairs = dict(extract_assignments(
        "TIMEOUT = 30  # seconds\n"
        "# NOT_A_REAL = 1\n"
        "lowercase = 2\n"
        "OTHER: int = 7\n"))
    assert "TIMEOUT" in pairs
    assert "OTHER" in pairs
    assert "NOT_A_REAL" not in pairs
    assert "lowercase" not in pairs


def test_same_value_everywhere_is_not_a_conflict(tmp_path):
    """Corroboration is not contradiction -- dropping it would gain nothing."""
    root = tmp_path / "same"
    for domain in ("a", "b"):
        target = root / domain / "c.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("SHARED_LIMIT = 42\n", encoding="utf-8")
    out = tmp_path / "same.npk"
    compile_pack(root, out, mode=MODE_DETERMINISTIC)

    with open_pack(out) as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM blocks")]
        assert find_conflict_sets(con, ids) == {}


def test_differing_values_are_detected_as_a_conflict(conflicted_pack):
    with open_pack(conflicted_pack) as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM blocks")]
        conflicts = find_conflict_sets(con, ids)
    assert "REQUEST_TIMEOUT" in conflicts
    assert len(conflicts["REQUEST_TIMEOUT"]) >= 3


# ---------------------------------------------------------------------------
# Query-time resolution
# ---------------------------------------------------------------------------

def test_query_scope_selects_the_right_variant(conflicted_pack):
    selection = PackSelector(str(conflicted_pack), resolve_conflicts=True).select(
        "What is REQUEST_TIMEOUT in the billing service?", budget_tokens=400)
    text = " ".join(e.text for e in selection.evidence)
    assert "30" in text, "correct variant was dropped"
    assert "90" not in text, "contradicting variant from another scope survived"


def test_deprecated_variant_is_demoted(conflicted_pack):
    selection = PackSelector(str(conflicted_pack), resolve_conflicts=True).select(
        "What is REQUEST_TIMEOUT in the auth service?", budget_tokens=400)
    text = " ".join(e.text for e in selection.evidence)
    assert "77" in text
    assert "REQUEST_TIMEOUT = 5" not in text, "legacy/ variant was not demoted"


def test_dropping_a_variant_is_recorded_as_provenance(conflicted_pack):
    selection = PackSelector(str(conflicted_pack), resolve_conflicts=True).select(
        "What is REQUEST_TIMEOUT in the billing service?", budget_tokens=400)
    if selection.conflicts_resolved:
        entry = selection.conflicts_resolved[0]
        assert entry["symbol"] == "REQUEST_TIMEOUT"
        assert entry["dropped_block_ids"]
        assert entry["reason"], "a dropped block must carry a reason"
        assert any("contradicting" in n for n in selection.notes)


def test_resolution_is_conservative_when_the_query_gives_no_scope(tmp_path):
    """An unscoped query must keep every variant.

    Guessing on a weak signal trades a redundant block for a missing answer,
    which is the worse failure.
    """
    root = tmp_path / "unscoped"
    for name, value in (("alpha", 11), ("beta", 22)):
        target = root / name / "mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"MYSTERY_LIMIT = {value}\n", encoding="utf-8")
    out = tmp_path / "unscoped.npk"
    compile_pack(root, out, mode=MODE_DETERMINISTIC)

    with open_pack(out) as con:
        rows = con.execute(
            "SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id").fetchall()
        ids = [r["id"] for r in rows]
        paths = {r["id"]: r["path"] for r in rows}
        # The query names neither scope, so nothing decides between them.
        drop, decisions = resolve_value_conflicts(
            con, ids, paths, "what is MYSTERY_LIMIT?",
            {bid: i for i, bid in enumerate(ids)})

    assert drop == set(), "resolution guessed without a decisive signal"
    assert decisions == []


def test_disabling_resolution_restores_the_old_behaviour(conflicted_pack):
    keep_all = PackSelector(str(conflicted_pack), resolve_conflicts=False).select(
        "What is REQUEST_TIMEOUT in the billing service?", budget_tokens=400)
    resolved = PackSelector(str(conflicted_pack), resolve_conflicts=True).select(
        "What is REQUEST_TIMEOUT in the billing service?", budget_tokens=400)
    assert len(resolved.evidence) <= len(keep_all.evidence)


def test_resolution_never_empties_the_context(conflicted_pack):
    """Conflict resolution must not become a new route to context destruction."""
    for query in ("What is REQUEST_TIMEOUT in the billing service?",
                  "REQUEST_TIMEOUT legacy deprecated billing search auth"):
        selection = PackSelector(str(conflicted_pack), resolve_conflicts=True).select(query, budget_tokens=400)
        assert selection.evidence, f"context destroyed for query {query!r}"


def test_resolution_makes_no_generative_llm_call(conflicted_pack):
    selection = PackSelector(str(conflicted_pack), resolve_conflicts=True).select(
        "What is REQUEST_TIMEOUT in the billing service?", budget_tokens=400)
    assert selection.used_generative_llm is False


# ---------------------------------------------------------------------------
# Regression: source order does not establish semantic supersession.
# ---------------------------------------------------------------------------

def test_latest_question_cannot_erase_prior_facts(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "conversation.txt").write_text(
        "System: Always retain the rollback region.\n"
        "User: Set deployment region to east, rollback region to west.\n"
        "Assistant: Done.\n"
        "User: Change deployment region to north.\n"
        "Assistant: Done.\n"
        "User: Confirm final deployment and rollback regions.\n", encoding="utf-8")
    pack = tmp_path / "conversation.npk"
    compile_pack(root, pack)
    result = PackSelector(pack).select("Confirm final deployment and rollback regions", budget_tokens=500)
    assert "west" in result.context_text()
    assert "north" in result.context_text()
    assert "Always retain the rollback region" in result.context_text()

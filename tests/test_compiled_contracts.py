"""Public compiler/runtime counterexamples independent of the tuning fixtures."""
from pathlib import Path

import pytest

from npk.pack import PackSelector, compile_pack
from npk.pack.compile import split_source
from npk.pack.format import PackError


def make_pack(tmp_path: Path, sources: dict[str, str]) -> Path:
    root = tmp_path / "src"
    for name, text in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    output = tmp_path / "test.npk"
    compile_pack(root, output, build_deps=False)
    return output


def test_comparison_keeps_old_and_new_variants(tmp_path):
    pack = make_pack(tmp_path, {
        "legacy/settings.py": "REQUEST_TIMEOUT = 5\n",
        "current/settings.py": "REQUEST_TIMEOUT = 30\n",
    })
    result = PackSelector(pack, resolve_conflicts=True).select(
        "Compare REQUEST_TIMEOUT before and after the migration", budget_tokens=200)
    assert {e.path for e in result.evidence} == {"legacy/settings.py", "current/settings.py"}


def test_historical_query_does_not_prefer_current_file(tmp_path):
    pack = make_pack(tmp_path, {
        "legacy/settings.py": "REQUEST_TIMEOUT = 5\n",
        "current/settings.py": "REQUEST_TIMEOUT = 30\n",
    })
    result = PackSelector(pack, resolve_conflicts=True).select("What was the original REQUEST_TIMEOUT?", budget_tokens=200)
    assert "REQUEST_TIMEOUT = 5" in result.context_text()


def test_one_conflict_cannot_delete_a_different_required_fact(tmp_path):
    pack = make_pack(tmp_path, {
        "billing/settings.py": "REQUEST_TIMEOUT = 30\n",
        "search/settings.py": "REQUEST_TIMEOUT = 90\nMAX_SEARCH_JOBS = 77\n",
    })
    result = PackSelector(pack, resolve_conflicts=True).select(
        "What is billing REQUEST_TIMEOUT and MAX_SEARCH_JOBS?", budget_tokens=200)
    assert "MAX_SEARCH_JOBS = 77" in result.context_text()
    assert "REQUEST_TIMEOUT = 30" in result.context_text()


def test_failed_selection_is_not_a_savings_success(tmp_path):
    pack = make_pack(tmp_path, {"settings.py": "REQUEST_TIMEOUT = 30\n"})
    result = PackSelector(pack).select("zzqqmmwwqqzz", budget_tokens=20)
    assert result.seed_failed
    assert result.as_dict()["reduction_pct"] is None
    assert result.as_dict()["status"] == "fallback_required"


def test_escalation_does_not_override_explicit_budget(tmp_path):
    pack = make_pack(tmp_path, {"settings.py": "REQUEST_TIMEOUT = 30\n"})
    result = PackSelector(pack).select("REQUEST_TIMEOUT", budget_tokens=3)
    assert result.total_tokens <= 3
    assert result.budget_tokens == 3
    assert result.seed_failed


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_budget_is_rejected(tmp_path, budget):
    pack = make_pack(tmp_path, {"settings.py": "REQUEST_TIMEOUT = 30\n"})
    with pytest.raises(ValueError):
        PackSelector(pack).select("REQUEST_TIMEOUT", budget_tokens=budget)


def test_joined_evidence_fits_the_same_token_estimator(tmp_path):
    from npk.pack.compile import estimate_tokens
    pack = make_pack(tmp_path, {f"p{i}.py": f"LIMIT_{i} = {i}\n" for i in range(12)})
    result = PackSelector(pack).select(" ".join(f"LIMIT_{i}" for i in range(12)), budget_tokens=32)
    assert estimate_tokens(result.context_text()) <= 32
    assert result.total_tokens == estimate_tokens(result.context_text())


def test_dialogue_preamble_and_multiline_turns_are_preserved():
    text = ("Never output XML. Keep identifiers unchanged.\n\n"
            "User: Set region to zone-a.\nUse JSON.\n"
            "Assistant: Acknowledged.\n"
            "User: Set retries to 7.\nAssistant: Done.")
    blocks = split_source(text, "text")
    assert blocks[0].start_line == 1
    assert "Never output XML" in "\n".join(b.text for b in blocks)
    assert any("Use JSON." in b.text and "zone-a" in b.text for b in blocks)
    for block in blocks:
        assert block.text == "\n".join(text.splitlines()[block.start_line-1:block.end_line])


def test_python_dialogue_example_is_not_a_conversation():
    text = ('TRANSCRIPT = """\nUser: hi\nAssistant: hi\n'
            'User: example\nAssistant: example\n"""\n'
            'def run():\n    return TRANSCRIPT\n')
    blocks = split_source(text, "python")
    assert not any(b.kind == "turn" for b in blocks)
    assert any(b.name == "run" and b.kind == "function" for b in blocks)


def test_markdown_fenced_transcript_does_not_retype_document():
    text = ('# Examples\n```text\nUser: hi\nAssistant: hi\n'
            'User: example\nAssistant: example\n```\n# Rules\nPreserve this section.')
    assert all(b.kind != "turn" for b in split_source(text, "markdown"))


def test_splitter_change_requires_recompile_before_incremental_update(tmp_path):
    from npk.pack import update_pack
    from npk.pack.format import connect
    pack = make_pack(tmp_path, {"settings.py": "REQUEST_TIMEOUT = 30\n"})
    con = connect(pack, readonly=False)
    try:
        con.execute("UPDATE manifest SET value='2.0' WHERE key='compiler_version'")
        con.commit()
    finally:
        con.close()
    before = pack.read_bytes()
    with pytest.raises(PackError, match="recompile"):
        update_pack(pack, tmp_path / "src")
    assert pack.read_bytes() == before


def test_default_query_never_loads_optional_channels(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("npk.pack.select")
    pack = make_pack(tmp_path, {"settings.py": "REQUEST_TIMEOUT = 30\n"})

    def forbidden(*args, **kwargs):
        raise AssertionError("optional channel entered the default runtime")

    for name in ("_symbol_channel", "_embedding_channel", "_expand_dependencies"):
        monkeypatch.setattr(module, name, forbidden)
    result = PackSelector(pack).select("REQUEST_TIMEOUT")
    assert "30" in result.context_text()
    assert result.channels_used == ["lexical"]


def test_default_keeps_conflicting_variants(tmp_path):
    pack = make_pack(tmp_path, {
        "billing/settings.py": "REQUEST_TIMEOUT = 30\n",
        "search/settings.py": "REQUEST_TIMEOUT = 90\n",
    })
    result = PackSelector(pack).select("billing REQUEST_TIMEOUT", budget_tokens=200)
    assert len(result.evidence) == 2
    assert not result.conflicts_resolved


def test_hybrid_flag_enters_optional_channels(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("npk.pack.select")
    pack = make_pack(tmp_path, {"settings.py": "REQUEST_TIMEOUT = 30\n"})
    calls = []

    def symbol(*args):
        calls.append("symbol")
        return []

    def embedding(*args):
        calls.append("embedding")
        return [], None

    monkeypatch.setattr(module, "_symbol_channel", symbol)
    monkeypatch.setattr(module, "_embedding_channel", embedding)
    result = PackSelector(pack, retrieval="hybrid").select("REQUEST_TIMEOUT")
    assert result.evidence
    assert calls == ["symbol", "embedding"]

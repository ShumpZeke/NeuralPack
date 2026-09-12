"""The architectural invariant: the .npk fast path makes ZERO generative LLM calls.

NeuralPack is an LLM-independent context compiler and runtime. ChatGPT, Codex or
Claude Code may be used to *develop* it; none of them may be required to *run*
it. These tests enforce that at three levels:

1. **Network**: sockets are blocked outright during compile and select. Any
   remote call -- to a frontier provider or anything else -- raises.
2. **Provider surface**: every provider ``chat_completion`` is replaced with a
   tripwire that fails the test if called.
3. **Static**: the ``npk.pack`` package must not import provider modules at all,
   so a generative call cannot be added later without this failing.

A local sentence encoder is permitted and is NOT a generative model: it emits
vectors, never tokens, and runs on this machine.
"""
from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from npk.pack import (
    MODE_DETERMINISTIC, PackSelector, compile_pack, pack_stats, update_pack, verify,
)

FIXTURE = {
    "billing/limits.py": (
        "from config import BASE_TIMEOUT\n\n"
        "CONNECTION_POOL_SIZE = 7742\n\n"
        "def resolve_pool():\n"
        "    return CONNECTION_POOL_SIZE\n"
    ),
    "config.py": "BASE_TIMEOUT = 30\nRETRY_LIMIT = 918\n",
    "docs/guide.md": "# Overview\n\nThe service retries failed calls.\n\n## Limits\n\nPool size is configured per region.\n",
    "noise/unrelated.py": "\n".join(f"def helper_{i}():\n    return {i}\n" for i in range(40)),
}


@pytest.fixture()
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    for rel, body in FIXTURE.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


@pytest.fixture()
def pack(source_tree: Path, tmp_path: Path) -> Path:
    out = tmp_path / "project.npk"
    compile_pack(source_tree, out, mode=MODE_DETERMINISTIC)
    return out


class _BlockedSocket:
    """Any attempt to open a socket fails loudly."""

    def __init__(self, *a, **k):
        raise AssertionError(
            "network access attempted on the NeuralPack fast path; "
            "the runtime must not contact any remote model or service"
        )


@pytest.fixture()
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _BlockedSocket)
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("network access attempted on the fast path")))
    return True


@pytest.fixture()
def no_generative_calls(monkeypatch):
    """Trip if any provider's chat_completion is invoked."""
    from npk.providers import anthropic, gemini, mock, nvidia, openai, openai_compatible

    def tripwire(*_a, **_k):
        raise AssertionError(
            "a generative LLM call was made on the NeuralPack fast path")

    for module in (anthropic, gemini, mock, nvidia, openai, openai_compatible):
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and hasattr(obj, "chat_completion"):
                monkeypatch.setattr(obj, "chat_completion", tripwire, raising=False)
    return True


# ---------------------------------------------------------------------------
# 1. Network and provider tripwires
# ---------------------------------------------------------------------------

def test_compile_makes_no_network_or_generative_calls(source_tree, tmp_path, no_network, no_generative_calls):
    out = tmp_path / "offline.npk"
    stats = compile_pack(source_tree, out, mode=MODE_DETERMINISTIC)
    assert stats.blocks > 0
    assert stats.embedded == 0, "deterministic mode must not embed anything"
    assert verify(out)["ok"]


def test_select_makes_no_network_or_generative_calls(pack, no_network, no_generative_calls):
    selection = PackSelector(str(pack)).select("What is CONNECTION_POOL_SIZE?", budget_tokens=500)
    assert selection.evidence, "selection returned nothing"
    assert selection.used_generative_llm is False
    assert any("7742" in e.text for e in selection.evidence)


def test_incremental_update_makes_no_network_calls(pack, source_tree, no_network, no_generative_calls):
    (source_tree / "config.py").write_text("BASE_TIMEOUT = 45\nRETRY_LIMIT = 919\n", encoding="utf-8")
    stats = update_pack(pack, source_tree)
    assert stats.files_indexed == 1
    assert stats.files_skipped_unchanged == len(FIXTURE) - 1


# ---------------------------------------------------------------------------
# 2. Static guarantee -- no provider imports in the pack package
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORT_FRAGMENTS = (
    "npk.providers", "openai", "anthropic", "google.generativeai",
    "httpx", "requests", "urllib.request", "http.client",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.add(("." * node.level) + node.module)
    return names


def test_pack_package_never_imports_a_model_provider():
    pack_dir = Path(__file__).resolve().parents[1] / "npk" / "pack"
    offenders: list[str] = []
    for module in sorted(pack_dir.glob("*.py")):
        for name in _imported_modules(module):
            for bad in FORBIDDEN_IMPORT_FRAGMENTS:
                if name == bad or name.startswith(bad + "."):
                    offenders.append(f"{module.name} imports {name}")
    assert not offenders, (
        "the .npk runtime must stay provider-independent: " + "; ".join(offenders))


def test_pack_package_has_no_provider_relative_imports():
    pack_dir = Path(__file__).resolve().parents[1] / "npk" / "pack"
    for module in sorted(pack_dir.glob("*.py")):
        src = module.read_text(encoding="utf-8")
        assert "from ..providers" not in src, f"{module.name} reaches into npk.providers"
        assert "from ..runtime" not in src, f"{module.name} reaches into the LLM runtime"


# ---------------------------------------------------------------------------
# 3. Deterministic mode is genuinely CPU-only
# ---------------------------------------------------------------------------

def test_deterministic_mode_works_with_embeddings_disabled(source_tree, tmp_path, monkeypatch):
    monkeypatch.setenv("NPK_ENABLE_EMBEDDINGS", "0")
    out = tmp_path / "cpu_only.npk"
    compile_pack(source_tree, out, mode=MODE_DETERMINISTIC)
    assert pack_stats(out)["embedding_model"] is None

    selection = PackSelector(str(out)).select("What is RETRY_LIMIT?", budget_tokens=400)
    assert selection.evidence
    assert any("918" in e.text for e in selection.evidence)
    assert "embedding" not in selection.channels_used


def test_semantic_mode_degrades_to_deterministic_without_a_model(source_tree, tmp_path, monkeypatch):
    """Requesting semantic mode with no encoder available must still produce a
    usable artifact, not an error and not a silent remote call."""
    monkeypatch.setenv("NPK_ENABLE_EMBEDDINGS", "0")
    out = tmp_path / "degraded.npk"
    stats = compile_pack(source_tree, out, mode="semantic")
    assert stats.embedded == 0
    assert verify(out)["ok"]
    assert PackSelector(str(out)).select("What is RETRY_LIMIT?", budget_tokens=400).evidence


# ---------------------------------------------------------------------------
# 4. Selection safety
# ---------------------------------------------------------------------------

def test_unanswerable_query_reports_failure_not_a_fake_win(pack):
    selection = PackSelector(str(pack)).select(
        "zzqqxx_no_such_symbol_anywhere_98765", budget_tokens=500)
    if not selection.evidence:
        assert selection.seed_failed is True
        assert "raw_fallback" in selection.escalations
        assert selection.risk_band == "uncalibrated:maximum"
        assert any("full context" in n for n in selection.notes)


def test_selection_never_exceeds_its_budget(pack):
    for budget in (100, 300, 900):
        selection = PackSelector(str(pack)).select("pool size and retry limit",
                                                   budget_tokens=budget)
        assert selection.total_tokens <= budget


def test_evidence_carries_provenance(pack):
    selection = PackSelector(str(pack)).select("What is CONNECTION_POOL_SIZE?", budget_tokens=600)
    assert selection.evidence
    for item in selection.evidence:
        assert item.path
        assert ":" in item.span and "-" in item.span
        assert item.channels


# ---------------------------------------------------------------------------
# 5. Provider independence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target_model", [
    None, "gpt-4o-mini", "claude-3-5-sonnet-20241022",
    "gemini-1.5-pro", "meta/llama-3.2-11b-vision-instruct", "some-future-model",
])
def test_same_pack_serves_every_provider_identically(pack, target_model):
    selection = PackSelector(str(pack)).select(
        "What is CONNECTION_POOL_SIZE?", budget_tokens=600, target_model=target_model)
    assert selection.evidence
    assert [e.block_id for e in selection.evidence] == [
        e.block_id for e in PackSelector(str(pack)).select(
            "What is CONNECTION_POOL_SIZE?", budget_tokens=600).evidence
    ], "target model changed the selected evidence; the artifact is not provider-independent"


def test_pack_contains_no_provider_specific_state(pack):
    from npk.pack.format import open_pack, read_manifest

    with open_pack(pack) as con:
        manifest = read_manifest(con)
    blob = " ".join(f"{k}={v}" for k, v in manifest.items()).lower()
    for vendor in ("openai", "anthropic", "gemini", "nvidia", "api_key", "nvapi", "sk-"):
        assert vendor not in blob, f"manifest leaked provider-specific state: {vendor}"


# ---------------------------------------------------------------------------
# 6. Incremental compilation correctness
# ---------------------------------------------------------------------------

def test_unchanged_source_reindexes_nothing(pack, source_tree):
    stats = update_pack(pack, source_tree)
    assert stats.files_indexed == 0
    assert stats.files_skipped_unchanged == len(FIXTURE)


def test_changed_file_updates_only_itself(pack, source_tree):
    (source_tree / "config.py").write_text("BASE_TIMEOUT = 60\nRETRY_LIMIT = 4242\n", encoding="utf-8")
    stats = update_pack(pack, source_tree)
    assert stats.files_indexed == 1

    selection = PackSelector(str(pack)).select("What is RETRY_LIMIT?", budget_tokens=400)
    joined = " ".join(e.text for e in selection.evidence)
    assert "4242" in joined, "incremental update did not refresh the index"
    assert "918" not in joined, "stale block survived the update"


def test_deleted_file_is_removed_from_the_pack(pack, source_tree):
    (source_tree / "noise" / "unrelated.py").unlink()
    stats = update_pack(pack, source_tree)
    assert stats.files_removed == 1
    assert pack_stats(pack)["files"] == len(FIXTURE) - 1


def test_added_file_appears_without_full_recompile(pack, source_tree):
    (source_tree / "billing" / "surcharge.py").write_text(
        "SURCHARGE_CENTS = 3311\n", encoding="utf-8")
    stats = update_pack(pack, source_tree)
    assert stats.files_indexed == 1
    assert stats.files_skipped_unchanged == len(FIXTURE)

    selection = PackSelector(str(pack)).select("What is SURCHARGE_CENTS?", budget_tokens=400)
    assert any("3311" in e.text for e in selection.evidence)


def test_integrity_digest_changes_with_content(pack, source_tree):
    before = verify(pack)["actual_root_sha256"]
    (source_tree / "config.py").write_text("BASE_TIMEOUT = 99\n", encoding="utf-8")
    update_pack(pack, source_tree)
    after = verify(pack)
    assert after["ok"]
    assert after["actual_root_sha256"] != before


# ---------------------------------------------------------------------------
# 7. Secrets never enter an artifact
# ---------------------------------------------------------------------------

def test_credential_files_are_never_compiled(tmp_path):
    root = tmp_path / "withsecrets"
    (root / "sub").mkdir(parents=True)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".env").write_text("NVIDIA_API_KEY=nvapi-" + "Z" * 60 + "\n", encoding="utf-8")
    (root / "secrets.json").write_text('{"token": "' + "Y" * 40 + '"}', encoding="utf-8")
    (root / "sub" / "id_rsa").write_text("PRIVATE KEY", encoding="utf-8")

    out = tmp_path / "clean.npk"
    compile_pack(root, out, mode=MODE_DETERMINISTIC)

    from npk.pack.format import open_pack
    with open_pack(out) as con:
        paths = {r["path"] for r in con.execute("SELECT path FROM files")}
        blob = " ".join(r["text"] for r in con.execute("SELECT text FROM blocks"))

    assert paths == {"app.py"}
    assert "nvapi-" not in blob
    assert "PRIVATE KEY" not in blob

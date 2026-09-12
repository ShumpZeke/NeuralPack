"""Opt-in local encoder, rank equivalence and flag-wiring regressions.

Cycle 1/2 headline statistics are withdrawn; see EVOLUTION_LOG.md cycle 3.
These fixtures test capabilities, not general answer-quality improvements.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from npk.pack import MODE_DETERMINISTIC, MODE_SEMANTIC, PackSelector, compile_pack, pack_stats
from npk.pack.format import open_pack, read_manifest


def _embeddings_available() -> bool:
    from npk.context.embedding import embeddings_available
    return embeddings_available()


needs_model = pytest.mark.skipif(
    not _embeddings_available(), reason="local embedding model unavailable")


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    # A semantic gap: the query will say "jobs at the same time", the code says
    # MAX_PARALLEL_WORKERS. No lexical channel can bridge that.
    (root / "billing").mkdir(parents=True)
    (root / "billing" / "worker_limits.py").write_text(
        "MAX_PARALLEL_WORKERS = 3742\n", encoding="utf-8")
    for i in range(30):
        (root / f"noise_{i}.py").write_text(
            f"def helper_{i}():\n    return {i}\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Semantic mode
# ---------------------------------------------------------------------------

@needs_model
def test_semantic_mode_builds_an_embedding_index(source, tmp_path):
    out = tmp_path / "sem.npk"
    stats = compile_pack(source, out, mode=MODE_SEMANTIC)
    assert stats.embedded > 0
    assert pack_stats(out)["embedding_model"]
    with open_pack(out) as con:
        assert int(read_manifest(con)["embedding_dim"]) > 0


@needs_model
def test_embeddings_bridge_a_semantic_gap_that_lexical_cannot(source, tmp_path):
    """An opt-in local encoder can retrieve this vocabulary-gap counterexample."""
    det = tmp_path / "det.npk"
    sem = tmp_path / "sem.npk"
    compile_pack(source, det, mode=MODE_DETERMINISTIC)
    compile_pack(source, sem, mode=MODE_SEMANTIC)

    query = "How many jobs can the billing pipeline run at the same time?"
    sem_sel = PackSelector(str(sem), retrieval="hybrid").select(query, budget_tokens=300)
    assert "embedding" in sem_sel.channels_used
    assert any("3742" in e.text for e in sem_sel.evidence), (
        "embedding channel failed to bridge the semantic gap")


def test_deterministic_pack_never_uses_an_embedding_channel(source, tmp_path):
    out = tmp_path / "det.npk"
    compile_pack(source, out, mode=MODE_DETERMINISTIC)
    selection = PackSelector(str(out)).select(
        "How many jobs can run at the same time?", budget_tokens=300)
    assert "embedding" not in selection.channels_used
    assert selection.used_generative_llm is False


# ---------------------------------------------------------------------------
# Mode-aware dependency expansion
# ---------------------------------------------------------------------------

def test_deterministic_artifact_has_no_embedding_index(source, tmp_path):
    det = tmp_path / "det.npk"
    compile_pack(source, det, mode=MODE_DETERMINISTIC)
    with open_pack(det) as con:
        assert int(read_manifest(con).get("embedding_dim") or 0) == 0


@needs_model
def test_expansion_requires_explicit_opt_in(source, tmp_path, monkeypatch):
    sem = tmp_path / "sem.npk"
    compile_pack(source, sem, mode=MODE_SEMANTIC)
    with open_pack(sem) as con:
        assert int(read_manifest(con)["embedding_dim"]) > 0

    import importlib
    module = importlib.import_module("npk.pack.select")
    calls = []

    def expansion(*args, **kwargs):
        calls.append(True)
        return []

    monkeypatch.setattr(module, "_expand_dependencies", expansion)
    auto = PackSelector(str(sem), retrieval="hybrid")
    forced = PackSelector(str(sem), retrieval="hybrid", enable_dependency_expansion=True)
    q = "How many jobs can the billing pipeline run at the same time?"
    assert auto.select(q, budget_tokens=300).evidence
    assert calls == []
    assert forced.select(q, budget_tokens=300).evidence
    assert calls == [True]


def test_expansion_can_still_be_forced_off(source, tmp_path):
    out = tmp_path / "det.npk"
    compile_pack(source, out, mode=MODE_DETERMINISTIC)
    sel = PackSelector(str(out), enable_dependency_expansion=False).select(
        "What is MAX_PARALLEL_WORKERS?", budget_tokens=300)
    assert "expand_dependencies" not in sel.escalations


# ---------------------------------------------------------------------------
# Vectorized embedding scan
# ---------------------------------------------------------------------------

@needs_model
def test_vectorized_scan_matches_the_scalar_reference(source, tmp_path):
    """The numpy path must agree with the pure-Python fallback.

    A 7x speedup is worthless if it changes the ranking.
    """
    import numpy as np

    from npk.pack.compile import unpack_vector

    out = tmp_path / "sem.npk"
    compile_pack(source, out, mode=MODE_SEMANTIC)

    from npk.context.embedding import get_backend
    qvec = get_backend().embed_query("how many jobs run at once")
    assert qvec is not None

    with open_pack(out) as con:
        rows = con.execute(
            "SELECT block_id, vector FROM embeddings WHERE dim = ?", (len(qvec),)).fetchall()

        scalar = sorted(
            ((sum(a * b for a, b in zip(unpack_vector(r["vector"], len(qvec)), qvec)),
              r["block_id"]) for r in rows), reverse=True)

        matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32)
        matrix = matrix.reshape(len(rows), len(qvec))
        sims = matrix @ np.asarray(qvec, dtype=np.float32)
        ids = [r["block_id"] for r in rows]
        vector_ranked = sorted(zip(sims.tolist(), ids), reverse=True)

    assert [b for _s, b in scalar[:5]] == [b for _s, b in vector_ranked[:5]], (
        "vectorized scan changed the ranking")


@needs_model
def test_embedding_channel_latency_is_bounded(source, tmp_path):
    """Guard against regressing to the O(N) Python scan.

    The row-at-a-time version measured 81.7 ms on 1,587 blocks. This corpus is
    far smaller, so a generous ceiling still catches a return to that algorithm.
    """
    import time

    out = tmp_path / "sem.npk"
    compile_pack(source, out, mode=MODE_SEMANTIC)
    selector = PackSelector(str(out), retrieval="hybrid")
    selector.select("warm up the encoder", budget_tokens=200)

    t0 = time.perf_counter()
    selector.select("how many jobs run at once", budget_tokens=300)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 2000, f"selection took {elapsed_ms:.0f} ms"


# ---------------------------------------------------------------------------
# Safety is preserved by every cycle-2 change
# ---------------------------------------------------------------------------

@needs_model
def test_semantic_mode_still_makes_no_generative_call(source, tmp_path):
    out = tmp_path / "sem.npk"
    compile_pack(source, out, mode=MODE_SEMANTIC)
    selection = PackSelector(str(out), retrieval="hybrid").select("anything at all", budget_tokens=300)
    assert selection.used_generative_llm is False


@needs_model
def test_semantic_pack_carries_no_provider_state(source, tmp_path):
    out = tmp_path / "sem.npk"
    compile_pack(source, out, mode=MODE_SEMANTIC)
    with open_pack(out) as con:
        manifest = read_manifest(con)
    blob = " ".join(f"{k}={v}" for k, v in manifest.items()).lower()
    for vendor in ("openai", "anthropic", "gemini", "nvidia", "api_key", "nvapi", "sk-"):
        assert vendor not in blob


@needs_model
def test_real_cached_encoder_loads_with_network_connections_blocked(monkeypatch):
    from npk.context.embedding import LocalEmbeddingBackend, DEFAULT_MODEL_REVISION
    def denied(*args,**kwargs):
        raise AssertionError("offline encoder attempted network")
    monkeypatch.setattr("socket.socket.connect",denied)
    monkeypatch.setattr("socket.create_connection",denied)
    backend=LocalEmbeddingBackend()
    assert backend.available()
    assert backend.identity()["revision"]==DEFAULT_MODEL_REVISION
    assert len(backend.embed_query("local retrieval check"))==384

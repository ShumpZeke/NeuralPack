"""Contracts for query result caching and canonical prompt ordering."""
import pytest

from npk.pack import compile_pack, update_pack, verify, PackSelector


@pytest.fixture
def pack(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "b_file.py").write_text("B_TOKEN = 20\ndef get_b(): return B_TOKEN\n", encoding="utf-8")
    (source / "a_file.py").write_text("A_TOKEN = 10\ndef get_a(): return A_TOKEN\n", encoding="utf-8")
    artifact = tmp_path / "project.npk"
    compile_pack(source, artifact)
    return source, artifact


def test_repeated_query_cache_hit_and_identity(pack):
    _, artifact = pack
    selector = PackSelector(artifact, enable_cache=True)
    computed = []
    original = selector._select_once
    selector._select_once = lambda *args, **kwargs: computed.append(1) or original(*args, **kwargs)
    # First query (miss)
    q1 = selector.select("get_a", budget_tokens=512)
    assert len(selector._cache) == 1 and computed
    # Second query (hit): served from the cache without recomputing the selection.
    # (Comparing wall-clock latencies here was flaky under machine load.)
    computed.clear()
    q2 = selector.select("get_a", budget_tokens=512)
    assert not computed
    assert q1.context_text() == q2.context_text()
    assert q1.total_tokens == q2.total_tokens
    assert [e.span for e in q1.evidence] == [e.span for e in q2.evidence]


def test_update_invalidates_query_cache(pack):
    source, artifact = pack
    selector = PackSelector(artifact, enable_cache=True)
    q1 = selector.select("A_TOKEN", budget_tokens=512)
    assert "10" in q1.context_text()
    assert len(selector._cache) == 1

    # Update a_file.py
    (source / "a_file.py").write_text("A_TOKEN = 9999\ndef get_a(): return A_TOKEN\n", encoding="utf-8")
    update_pack(artifact, source)

    # Querying again must see the updated value because root_sha256 changed
    q2 = selector.select("A_TOKEN", budget_tokens=512)
    assert "9999" in q2.context_text()
    # A new cache entry was created for the new root_sha256
    assert len(selector._cache) == 2


def test_clear_cache_and_disable_cache(pack):
    _, artifact = pack
    selector = PackSelector(artifact, enable_cache=True)
    selector.select("get_a", budget_tokens=512)
    assert len(selector._cache) == 1
    selector.clear_cache()
    assert len(selector._cache) == 0

    # Disabled cache
    uncached = PackSelector(artifact, enable_cache=False)
    uncached.select("get_a", budget_tokens=512)
    assert len(uncached._cache) == 0


def test_selection_context_text_supports_canonical_ordering(pack):
    _, artifact = pack
    selector = PackSelector(artifact)
    # Query where relevance order ranks b_file first due to stronger term matches
    sel = selector.select("get_b get_b B_TOKEN get_a", budget_tokens=2048)
    assert len(sel.evidence) >= 2
    assert sel.evidence[0].path == "b_file.py", "relevance order must put b_file first"

    # Default relevance order
    rel_text = sel.context_text(order="relevance")
    assert rel_text == sel.context_text()

    # Canonical corpus order: sorted by (path, span) must put a_file first
    can_text = sel.context_text(order="canonical")
    can_evidence = sorted(sel.evidence, key=lambda e: (e.path, e.span))
    assert can_evidence[0].path == "a_file.py", "canonical order must put a_file first"
    expected_can_text = "\n\n".join(e.text for e in can_evidence)
    assert can_text == expected_can_text
    assert rel_text != can_text, "relevance and canonical order must differ when ranking disagrees with path order"

    # Invalid order raises ValueError
    with pytest.raises(ValueError, match="unknown order"):
        sel.context_text(order="random_order")


def test_cache_size_limit_evicts_lru(pack):
    _, artifact = pack
    selector = PackSelector(artifact, max_cache_entries=2)
    selector.select("query 1", budget_tokens=512)
    selector.select("query 2", budget_tokens=512)
    assert len(selector._cache) == 2
    selector.select("query 3", budget_tokens=512)
    assert len(selector._cache) == 2
    # query 1 should have been evicted
    keys = [k[1] for k in selector._cache.keys()]
    assert "query 1" not in keys
    assert "query 2" in keys and "query 3" in keys

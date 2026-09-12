"""Adversarial cache use must preserve fresh, independently owned evidence."""
from contextlib import nullcontext
import copy
import importlib
from types import SimpleNamespace

import pytest

from npk.pack import Evidence, PackSelector, Selection, compile_pack, update_pack
from npk.pack.format import PackError, connect
from npk.pack.tokenizer import LocalTokenizer


@pytest.fixture
def corpus(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "values.py").write_text("ANSWER = 'old'\n", encoding="utf-8")
    artifact = tmp_path / "values.npk"
    compile_pack(source, artifact)
    return source, artifact


def stable(result):
    row = result.as_dict()
    row.pop("latency_ms")
    return row


@pytest.mark.parametrize("cached", [True, False])
def test_managed_query_refreshes_content_and_manifest(corpus, cached):
    source, artifact = corpus
    with PackSelector(artifact, enable_cache=cached) as selector:
        selector.select("ANSWER")
        (source / "values.py").write_text("ANSWER = 'a much longer new value'\n", encoding="utf-8")
        update_pack(artifact, source)
        actual = selector.select("ANSWER")
        expected = PackSelector(artifact, enable_cache=False).select("ANSWER")
        assert stable(actual) == stable(expected)
        assert "new value" in actual.context_text()


@pytest.mark.parametrize("managed", [True, False])
@pytest.mark.parametrize("mutate_hit", [True, False])
def test_caller_cannot_poison_cached_evidence(corpus, managed, mutate_hit):
    _, artifact = corpus
    selector = PackSelector(artifact)
    with selector if managed else nullcontext(selector):
        first = selector.select("ANSWER")
        expected = copy.deepcopy(stable(first))
        result = selector.select("ANSWER") if mutate_hit else first
        result.evidence[0].text = "FORGED EVIDENCE"
        result.evidence[0].path = "forged.py"
        result.evidence[0].channels.append("forged")
        result.notes.append("forged")
        result.escalations.append("forged")
        result.channels_used.append("forged")
        result.conflicts_resolved.append({"nested": ["forged"]})
        result.evidence.clear()
        assert stable(selector.select("ANSWER")) == expected


def test_cache_preserves_exact_query_bytes(corpus):
    _, artifact = corpus
    selector = PackSelector(artifact)
    selector.select("ANSWER")
    query = " \tANSWER\n"
    assert selector.select(query).query == query


def test_changing_tokenizer_rechecks_budget(corpus, tmp_path):
    tokenizers = pytest.importorskip("tokenizers")
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.Split("", behavior="isolated")
    asset = tmp_path / "chars.json"
    backend.save(str(asset))
    counter = LocalTokenizer(asset)
    _, artifact = corpus
    selector = PackSelector(artifact)
    initial = selector.select("ANSWER", budget_tokens=6)
    assert initial.evidence
    selector.tokenizer = counter
    actual = selector.select("ANSWER", budget_tokens=6)
    expected = PackSelector(artifact, tokenizer=counter, enable_cache=False).select("ANSWER", budget_tokens=6)
    assert stable(actual) == stable(expected)
    assert counter.count(actual.context_text()) <= 6


def test_hybrid_cache_cannot_hide_encoder_unavailability(corpus, monkeypatch):
    _, artifact = corpus
    module = importlib.import_module("npk.pack.select")
    calls = []
    def encoding(*args):
        calls.append(True)
        if len(calls) > 1:
            raise PackError("encoder changed")
        return [], None
    monkeypatch.setattr(module, "_embedding_channel", encoding)
    selector = PackSelector(artifact, retrieval="hybrid")
    selector.select("ANSWER")
    rejected = False
    try:
        selector.select("ANSWER")
    except PackError:
        rejected = True
    assert rejected, "hybrid result cache hid an encoder contract change"


def test_managed_query_revalidates_manifest(corpus):
    _, artifact = corpus
    with PackSelector(artifact) as selector:
        selector.select("ANSWER")
        con = connect(artifact, readonly=False)
        try:
            con.execute("UPDATE manifest SET value='999' WHERE key='format_version'")
            con.commit()
        finally:
            con.close()
        rejected = False
        try:
            selector.select("ANSWER")
        except PackError:
            rejected = True
        assert rejected, "cache served a now-unsupported artifact"


def test_canonical_order_uses_numeric_source_lines():
    evidence = [
        Evidence(1, "same.py", "same.py:10-10", "chunk", None, 1, "ten", 1.0),
        Evidence(2, "same.py", "same.py:2-2", "chunk", None, 1, "two", 0.5),
    ]
    selection = Selection("q", evidence, 2, 20, 2, [], [], "uncalibrated:high", False, 0.0)
    assert selection.context_text(order="canonical") == "two\n\nten"


def test_canonical_exact_order_is_recounted(tmp_path):
    tokenizers = pytest.importorskip("tokenizers")
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    asset = tmp_path / "order.json"
    backend.save(str(asset))
    counter = LocalTokenizer(asset)
    prices = {"late\n\nearly": 2, "early\n\nlate": 9}
    counter._backend = SimpleNamespace(
        encode=lambda text, **kwargs: SimpleNamespace(ids=[0] * prices[text]))
    evidence = [
        Evidence(1, "z.py", "z.py:1-1", "chunk", None, 1, "late", 1.0),
        Evidence(2, "a.py", "a.py:1-1", "chunk", None, 1, "early", 0.5),
    ]
    selection = Selection(
        "q", evidence, 2, 5, None, [], [], "uncalibrated:high", False, 0.0,
        tokenizer=counter.as_dict())
    with pytest.raises(ValueError, match="matching local tokenizer"):
        selection.context_text(order="canonical")
    with pytest.raises(PackError, match="exceeds token budget"):
        selection.context_text(order="canonical", tokenizer=counter)

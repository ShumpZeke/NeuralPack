"""Identifiers named by a query resolve to their defining blocks (E002)."""
import pytest

from npk.pack import PackSelector, compile_pack
from npk.pack.select import MAX_DEFINITION_AMBIGUITY, _query_entities


def test_query_entities_keep_code_names_and_ignore_prose():
    query = ("Signal.send_robust() swallows errors raised by `connect` receivers; "
             "see django.core.exceptions.ValidationError and HTTPServerV2, e.g. in "
             "handle_request. The value is wrong.")
    names = _query_entities(query)
    for expected in ("Signal", "send_robust", "connect", "ValidationError",
                     "exceptions", "HTTPServerV2", "handle_request"):
        assert expected in names
    for prose in ("swallows", "errors", "wrong", "value", "e", "g"):
        assert prose not in names
    assert names.index("Signal") < names.index("handle_request")


def _corpus(tmp_path):
    root = tmp_path / "src"
    (root / "pkg").mkdir(parents=True)
    (root / "docs").mkdir()
    # Filler modules give BM25 realistic document frequencies.
    for i in range(30):
        (root / "pkg" / f"filler{i}.py").write_text(
            f"def helper_{i}(items):\n    total = 0\n    for item in items:\n"
            f"        total += item * {i}\n    return total\n", encoding="utf-8")
    # The definition shares only its identifier with the query.
    (root / "pkg" / "dispatch.py").write_text(
        "class Signal:\n"
        "    def send_robust(self, sender, **named):\n"
        "        responses = []\n"
        "        for hook in self._live_hooks(sender):\n"
        "            try:\n"
        "                value = hook(signal=self, sender=sender, **named)\n"
        "            except Exception as err:\n"
        "                responses.append((hook, err))\n"
        "        return responses\n", encoding="utf-8")
    # Documentation repeats the issue's prose vocabulary.
    prose = ("A receiver can fail. Receiver exceptions are handled silently and never logged; "
             "handled receiver exceptions should be logged so failures are visible. ")
    (root / "docs" / "receivers.md").write_text("# Receivers\n\n" + prose * 3, encoding="utf-8")
    (root / "docs" / "logging.md").write_text("# Logging\n\n" + prose * 2, encoding="utf-8")
    pack = tmp_path / "p.npk"
    compile_pack(root, pack)
    return root, pack


QUERY = ("Why doesn't send_robust() log receiver exceptions? Receiver exceptions are handled "
         "silently; exceptions from a receiver should be logged.")


def test_named_definition_outranks_documentation_that_repeats_the_prose(tmp_path):
    _root, pack = _corpus(tmp_path)
    without = PackSelector(pack, enable_definitions=False).select(QUERY, budget_tokens=4000)
    assert without.evidence[0].path.startswith("docs/")
    selection = PackSelector(pack).select(QUERY, budget_tokens=4000)
    assert selection.evidence[0].path == "pkg/dispatch.py"
    assert "definition" in selection.evidence[0].channels
    assert "definition" in selection.channels_used


def test_prose_only_query_is_unchanged_by_the_channel(tmp_path):
    _root, pack = _corpus(tmp_path)
    query = "why are receiver exceptions handled silently"
    on = PackSelector(pack).select(query, budget_tokens=4000)
    off = PackSelector(pack, enable_definitions=False).select(query, budget_tokens=4000)
    assert [e.span for e in on.evidence] == [e.span for e in off.evidence]
    assert "definition" not in on.channels_used


def test_ambiguous_names_cast_no_vote(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    for i in range(MAX_DEFINITION_AMBIGUITY + 1):
        (root / f"m{i}.py").write_text(f"def shared_name():\n    return {i}\n", encoding="utf-8")
    pack = tmp_path / "p.npk"
    compile_pack(root, pack)
    selection = PackSelector(pack).select("call shared_name()", budget_tokens=4000)
    assert "definition" not in selection.channels_used


def test_definition_flag_is_validated_and_part_of_the_cache_key(tmp_path):
    _root, pack = _corpus(tmp_path)
    with pytest.raises(ValueError):
        PackSelector(pack, enable_definitions="yes")
    selector = PackSelector(pack)
    first = selector.select(QUERY, budget_tokens=4000)
    selector.enable_definitions = False
    second = selector.select(QUERY, budget_tokens=4000)
    assert first.evidence[0].path != second.evidence[0].path

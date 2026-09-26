"""An oversized top-ranked block degrades to its best member spans (E005c)."""
from npk.pack import PackSelector, compile_pack
from npk.pack.compile import MAX_BLOCK_TOKENS


def _method(name, body_words, lines=30):
    body = "\n".join(f"        value_{i} = '{body_words} {i}'" for i in range(lines))
    return f"    def {name}(self):\n{body}\n        return value_0\n"


def _corpus(tmp_path, methods=6, lines=30):
    root = tmp_path / "src"
    root.mkdir()
    parts = ["class Engine:\n    '''Coordinates the steps.'''\n"]
    for i in range(methods):
        words = "retry backoff jitter schedule" if i == 3 else f"filler text number {i}"
        parts.append(_method(f"step_{i}", words, lines))
    (root / "engine.py").write_text("\n".join(parts), encoding="utf-8")
    for i in range(20):
        (root / f"other_{i}.py").write_text(f"def helper_{i}():\n    return {i}\n", encoding="utf-8")
    (root / "notes.md").write_text("# Notes\n\n" + "unrelated words here. " * 400, encoding="utf-8")
    pack = tmp_path / "p.npk"
    compile_pack(root, pack)
    return pack


QUERY = "why does the retry backoff jitter schedule misbehave in Engine"


def test_top_block_that_cannot_fit_emits_its_best_member(tmp_path):
    pack = _corpus(tmp_path, lines=15)  # one unchunked class block
    selection = PackSelector(pack).select(QUERY, budget_tokens=400)
    assert selection.evidence, selection.notes
    first = selection.evidence[0]
    assert first.path == "engine.py" and "trimmed" in first.channels
    assert first.name == "Engine.step_3" and "retry backoff jitter" in first.text
    lo, hi = map(int, first.span.rsplit(":", 1)[1].split("-"))
    source = (tmp_path / "src" / "engine.py").read_text().split("\n")
    assert "\n".join(source[lo - 1:hi]) == first.text  # exact, addressable source lines
    assert any("exceeds the budget" in note for note in selection.notes)
    assert selection.total_tokens <= 400


def test_trimming_is_optional_and_part_of_the_cache_key(tmp_path):
    pack = _corpus(tmp_path, lines=15)
    selector = PackSelector(pack)
    trimmed = selector.select(QUERY, budget_tokens=400)
    selector.enable_trim = False
    plain = selector.select(QUERY, budget_tokens=400)
    assert not any("trimmed" in e.channels for e in plain.evidence)
    assert [e.span for e in trimmed.evidence] != [e.span for e in plain.evidence]


def test_block_that_fits_is_never_trimmed(tmp_path):
    pack = _corpus(tmp_path, lines=15)
    selection = PackSelector(pack).select(QUERY, budget_tokens=MAX_BLOCK_TOKENS * 4)
    engine = [e for e in selection.evidence if e.path == "engine.py"]
    assert engine and not any("trimmed" in e.channels for e in engine)


def test_chunked_class_members_are_still_found(tmp_path):
    # The class exceeds the block cap and is cut into line-window chunks; the
    # relevant method straddles a chunk boundary and must stay eligible.
    pack = _corpus(tmp_path, methods=6, lines=30)
    selection = PackSelector(pack).select(QUERY, budget_tokens=500)
    first = selection.evidence[0]
    assert "trimmed" in first.channels and first.name == "Engine.step_3"
    assert "retry backoff jitter" in first.text


def test_non_python_blocks_are_not_trimmed(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "guide.md").write_text("# Guide\n\n" + "retry backoff jitter schedule. " * 300, encoding="utf-8")
    pack = tmp_path / "p.npk"
    compile_pack(root, pack)
    selection = PackSelector(pack).select(QUERY, budget_tokens=200)
    assert not any("trimmed" in e.channels for e in selection.evidence)

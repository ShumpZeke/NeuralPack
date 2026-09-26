"""The test block mirroring the top implementation file follows it (E016b)."""
from npk.pack import PackSelector, compile_pack
from npk.pack.select import _mate_score


def _corpus(root):
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "throttle.py").write_text(
        "def backoff_delay(attempt, base):\n    '''Exponential backoff delay for a retry attempt.'''\n"
        "    return base * 2 ** attempt\n")
    (root / "tests" / "test_throttle.py").write_text(
        "from pkg.throttle import backoff_delay\n\n\n"
        "def test_backoff_delay_grows():\n    assert backoff_delay(2, 1) == 4\n")
    for i in range(20):
        (root / "pkg" / f"other{i}.py").write_text(
            f"def unrelated_{i}(value):\n    '''retry and delay words, but not backoff.'''\n    return value\n")


def test_mate_score_prefers_the_mirroring_test_file():
    assert _mate_score("pkg/throttle.py", "tests/test_throttle.py") >= 2.0
    assert _mate_score("pkg/throttle.py", "tests/test_other.py") < 1.0


def test_mate_follows_top_implementation_block(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _corpus(src)
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    query = "backoff_delay() grows too fast for a retry attempt"
    with PackSelector(str(pack), enable_cache=False) as selector:
        chosen = selector.select(query, budget_tokens=10**6, allow_escalation=False).evidence
    assert chosen[0].path == "pkg/throttle.py"
    assert chosen[1].path == "tests/test_throttle.py" and "test_mate" in chosen[1].channels
    with PackSelector(str(pack), enable_cache=False, enable_test_mate=False) as selector:
        plain = selector.select(query, budget_tokens=10**6, allow_escalation=False).evidence
    assert all("test_mate" not in e.channels for e in plain)

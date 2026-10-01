"""Historical release notes rank behind every other candidate (E054)."""
import pytest

from npk.pack import PackSelector, compile_pack
from npk.pack.select import _release_notes

QUERY = "Parser drops the trailing comma in call arguments"


def _pack(tmp_path, notes_path="CHANGELOG.md"):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "parser.py").write_text(
        "def parse_call_arguments(tokens):\n"
        "    '''Parse call arguments; keep a trailing comma after the last argument.'''\n"
        "    return [token for token in tokens if token != ',']\n")
    notes = src / notes_path
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text("# Changelog\n\n## 1.2.0\n\n- Parser: the trailing comma in call arguments is no longer "
                     "dropped by the parser (call arguments with a trailing comma).\n"
                     "- Parser drops the trailing comma in call arguments: fixed.\n")
    for i in range(10):
        (src / "pkg" / f"mod{i}.py").write_text(f"def helper_{i}(value):\n    return value + {i}\n")
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    return pack


def _paths(pack, **options):
    with PackSelector(str(pack), enable_cache=False, **options) as selector:
        return [e.path for e in selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence]


def test_release_notes_go_after_code(tmp_path):
    pack = _pack(tmp_path)
    in_rank = _paths(pack, demote_release_notes=False)
    assert in_rank[0] == "CHANGELOG.md"          # the historical entry matches the issue best
    demoted = _paths(pack)
    assert demoted[0] == "pkg/parser.py" and demoted[-1] == "CHANGELOG.md"


def test_reordering_keeps_the_selection_notes(tmp_path):
    pack = _pack(tmp_path)
    with PackSelector(str(pack), enable_cache=False) as selector:
        result = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False)
    assert result.evidence[-1].path == "CHANGELOG.md"
    assert all(isinstance(note, str) for note in result.notes), result.notes


def test_code_named_like_release_notes_keeps_its_rank(tmp_path):
    assert _release_notes("docs/releases/4.1.txt") and _release_notes("website/blog/2020-01-01-2.0.md")
    assert _release_notes("doc/source/whatsnew/v1.5.0.rst") and _release_notes("NEWS")
    for path in ("src/history.js", "pkg/releases/api.py", "src/changes.py", "README.md", "docs/index.html"):
        assert not _release_notes(path), path


def test_option_is_validated(tmp_path):
    pack = _pack(tmp_path)
    with pytest.raises(ValueError):
        PackSelector(str(pack), demote_release_notes="yes")

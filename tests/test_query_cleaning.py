"""Issue-form scaffolding is removed from the query before retrieval (E031)."""
import json
import subprocess
import sys

import pytest

from npk.pack import PackSelector, compile_pack
from npk.pack.select import _strip_issue_template

QUERY = """Cache keeps expired entries
### Steps to reproduce
Expired entries stay in the cache after their deadline passed.
### Expected behavior
### Actual behavior
### Environment
- [x] I searched the existing issues and read the contributing guide
<!-- Please describe the bug clearly, with steps to reproduce and the expected behavior. -->
"""


def _corpus(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "cache.py").write_text(
        "def evict_expired(entries, now):\n"
        "    '''Remove cache entries whose deadline passed.'''\n"
        "    return {key: entry for key, entry in entries.items() if entry.deadline > now}\n")
    (root / "CONTRIBUTING.md").write_text(
        "# Contributing\n\nBefore opening an issue, please search the existing issues.\n"
        "Describe the bug clearly: the steps to reproduce, the expected behavior, the actual\n"
        "behavior and your environment. Read this contributing guide before you describe a bug.\n")
    for i in range(20):
        (root / "pkg" / f"mod{i}.py").write_text(
            f"def helper_{i}(value):\n    '''Unrelated helper {i}.'''\n    return value + {i}\n")


@pytest.fixture()
def pack(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _corpus(src)
    out = tmp_path / "p.npk"
    compile_pack(src, out)
    return out


def test_scaffolding_is_removed_and_content_kept():
    cleaned = _strip_issue_template(QUERY)
    assert cleaned.split("\n") == [
        "Cache keeps expired entries",
        "Expired entries stay in the cache after their deadline passed.",
        " ",
        "",
    ]


def test_first_line_and_long_headings_are_kept():
    query = ("## Crash on save\n**Steps**\n"
             "## Saving a model twice raises an IntegrityError from the database\nsave() twice")
    assert _strip_issue_template(query).split("\n") == [
        "## Crash on save",
        "## Saving a model twice raises an IntegrityError from the database",
        "save() twice",
    ]


def test_unterminated_comment_and_bold_headings_are_removed():
    query = "Title\n**Expected behavior**:\nbody text\n<!-- instructions that never close"
    assert _strip_issue_template(query) == "Title\nbody text\n "


def test_query_that_would_become_empty_is_used_unchanged():
    assert _strip_issue_template("<!-- only a comment -->") == "<!-- only a comment -->"


def test_template_words_no_longer_pull_the_contributing_guide(pack):
    # Title and term-frequency weighting (E039) also demote the guide here; isolate cleaning.
    flat = {"title_weight": 1, "tf_cap": 1}
    with PackSelector(str(pack), enable_cache=False, **flat) as selector:
        cleaned = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence
    with PackSelector(str(pack), enable_cache=False, enable_query_cleaning=False, **flat) as selector:
        raw = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence
    assert raw[0].path == "CONTRIBUTING.md"
    assert cleaned[0].path == "pkg/cache.py"


def test_selection_reports_the_callers_query(pack):
    with PackSelector(str(pack), enable_cache=False) as selector:
        selection = selector.select(QUERY, budget_tokens=500)
    assert selection.query == QUERY


def test_cleaning_flag_must_be_boolean(pack):
    with pytest.raises(ValueError, match="enable_query_cleaning"):
        PackSelector(str(pack), enable_query_cleaning="yes")


def test_cli_raw_query_matches_the_selector(pack):
    def cli(*extra):
        out = subprocess.run([sys.executable, "-m", "npk.cli", "query", str(pack), QUERY, "--budget", "200",
                              *extra], capture_output=True, text=True, check=True).stdout
        return [item["span"] for item in json.loads(out)["evidence"]]

    with PackSelector(str(pack), enable_cache=False, enable_query_cleaning=False) as selector:
        raw = [e.span for e in selector.select(QUERY, budget_tokens=200).evidence]
    with PackSelector(str(pack), enable_cache=False) as selector:
        cleaned = [e.span for e in selector.select(QUERY, budget_tokens=200).evidence]
    assert raw != cleaned
    assert cli("--raw-query") == raw
    assert cli() == cleaned

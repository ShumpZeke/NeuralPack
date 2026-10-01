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


# --- E052: environment dumps ------------------------------------------------------------

ENV_QUERY = """Interval merge drops the closed side
Merging two intervals loses the closed flag of the right interval.

INSTALLED VERSIONS
------------------
commit           : 37ea63d540fd27274cad6585082c91b1283f963d
python           : 3.10.6.final.0
python-bits      : 64
OS               : Linux
LC_ALL           : None

pandas           : 1.5.0
numpy            : 1.23.3
pytz             : 2022.2.1
dateutil         : 2.8.2
setuptools       : 65.3.0
"""


def test_environment_dump_is_removed():
    cleaned = _strip_issue_template(ENV_QUERY)
    assert cleaned.split("\n")[:2] == ["Interval merge drops the closed side",
                                       "Merging two intervals loses the closed flag of the right interval."]
    # The key-value block goes; a header line before it (INSTALLED VERSIONS) stays, as evaluated.
    for word in ("numpy", "pytz", "setuptools", "python-bits", "LC_ALL", "commit"):
        assert word not in cleaned


def test_configuration_and_code_are_kept():
    config = ("Enum member flagged twice\n[mypy]\npython_version = 3.7\nshow_error_codes = True\n"
              "warn_return_any = True\nwarn_unused_configs = True\n")
    assert _strip_issue_template(config) == config
    code = ('Locale grouping ignored\n    fmt::print("X = {:19.3Lf}", -119.921);\n'
            '    fmt::print("Y = {:19.3Lf}", 2.1);\n    fmt::print("Z = {:19.3Lf}", 3.2);\n')
    assert _strip_issue_template(code) == code


DUMPED = ["pandas", "numpy", "pytz", "dateutil", "setuptools", "pip", "Cython", "pytest", "hypothesis",
          "sphinx", "blosc", "feather", "xlsxwriter", "lxml", "html5lib", "pymysql", "psycopg2", "jinja2",
          "IPython", "bottleneck", "fsspec", "matplotlib", "numba", "numexpr", "openpyxl", "pyarrow",
          "scipy", "sqlalchemy", "tables", "tabulate", "xarray", "xlrd", "zstandard", "tzdata"]


def test_version_listing_no_longer_pulls_the_version_module(tmp_path):
    query = ("Merge loses the closed flag\nMerging two intervals loses the closed flag.\n\n"
             "INSTALLED VERSIONS\n------------------\n"
             + "".join(f"{name:<17}: {i % 3 + 1}.{i}.{i % 5}\n" for i, name in enumerate(DUMPED)))
    src = tmp_path / "src"
    (src / "pkg" / "util").mkdir(parents=True)
    (src / "pkg" / "interval.py").write_text(
        "def merge(left, right):\n    '''Merge two intervals; keep the closed flag.'''\n"
        "    return (left, right)\n")
    (src / "pkg" / "util" / "print_versions.py").write_text(
        "DEPENDENCIES = [\n" + "".join(f"    '{name}',\n" for name in DUMPED) + "]\n\n\n"
        "def show_versions():\n    '''Print installed versions.'''\n"
        "    return {name: None for name in DEPENDENCIES}\n")
    for i in range(10):
        (src / "pkg" / f"mod{i}.py").write_text(f"def helper_{i}(value):\n    return value + {i}\n")
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    with PackSelector(str(pack), enable_cache=False) as selector:
        top = selector.select(query, budget_tokens=10**6, allow_escalation=False).evidence[0]
    assert top.path == "pkg/interval.py"   # without E052 the version module ranks first


URL_QUERY = """Tooltip flickers on hover
The tooltip flickers, see ![recording](https://user-images.githubusercontent.com/1/2.gif) and
https://github.com/acme/widgets/issues/12, as in https://github.com/acme/widgets/blob/main/src/tooltip/position.js#L40.
Docs: https://widgets.acme.dev/components/tooltip?tab=api#placement
"""


def test_urls_keep_only_their_informative_parts():
    cleaned = _strip_issue_template(URL_QUERY)
    assert cleaned.split("\n")[0] == "Tooltip flickers on hover"
    for scaffolding in ("https", "github", "githubusercontent", "recording", "issues", "acme.dev", "tab=api"):
        assert scaffolding not in cleaned, scaffolding
    assert " src/tooltip/position.js " in cleaned     # a source link keeps its repository path
    assert "components tooltip" in cleaned and "placement" in cleaned


def test_a_url_in_the_title_is_kept():
    query = "Crash on https://example.com/page\nThe page crashes."
    assert _strip_issue_template(query).split("\n")[0] == "Crash on https://example.com/page"


def test_link_scaffolding_no_longer_pulls_the_readme(tmp_path):
    links = "".join(f"See https://github.com/acme/widgets/issues/{n} and https://github.com/acme/widgets/pull/{n + 1}.\n"
                    for n in range(10, 16))
    query = "Tooltip flickers on hover\nThe tooltip position flickers on hover.\n" + links
    src = tmp_path / "src"
    (src / "widgets").mkdir(parents=True)
    (src / "widgets" / "tooltip.py").write_text(
        "def position_tooltip(anchor):\n    '''Place the tooltip next to its anchor on hover.'''\n"
        "    return anchor\n")
    (src / "README.md").write_text("# Widgets\n\n" + "".join(
        f"- https://github.com/acme/widgets/issues/{n} and https://github.com/acme/widgets/pull/{n}\n"
        for n in range(40)))
    for i in range(10):
        (src / "widgets" / f"mod{i}.py").write_text(f"def helper_{i}(value):\n    return value + {i}\n")
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    with PackSelector(str(pack), enable_cache=False) as selector:
        top = selector.select(query, budget_tokens=10**6, allow_escalation=False).evidence[0]
    assert top.path == "widgets/tooltip.py"   # without E053 the README's links rank first


def test_unterminated_markup_is_scanned_in_linear_time():
    import time
    for chunk in ("![a](", "<img ", "!["):
        query = "Pasted log\n" + chunk * 20000
        started = time.perf_counter()
        _strip_issue_template(query)
        # The unbounded patterns searched to the end of the line from every start: 0.5-1.4 s here.
        assert time.perf_counter() - started < 0.25, chunk


def test_inline_base64_images_are_removed_whole():
    blob = "A" * 60000
    query = (f"Broken icon\nSee ![icon](data:image/png;base64,{blob}) and "
             f"<img src=\"data:image/gif;base64,{blob}\"> here.")
    cleaned = _strip_issue_template(query)
    assert "base64" not in cleaned and "AAAA" not in cleaned
    assert "See" in cleaned and "here." in cleaned

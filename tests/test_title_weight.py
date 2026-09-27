"""Issue-style queries weight title terms and repeated terms (E034/E039)."""
import json
import subprocess
import sys

import pytest

from npk.pack import PackSelector, compile_pack

TITLE = "Legend loses its draggable state after pickling"
BODY = """I set up a figure and saved it, then loaded it in a new session.

Environment: Python 3.11 on Linux, installed with pip in a virtual environment.
Steps: create a figure, save the figure, load the figure, show the figure.
"""
QUERY = TITLE + "\n" + BODY
# "ledger" is repeated in the body; "journal", "replay" and "crash" appear once each.
TF_QUERY = ("Totals are wrong\n"
            "The ledger drops rows. After a flush the ledger is empty, and the ledger then "
            "rebuilds the ledger.\nA crash replay of the journal happened earlier.\n")


def _corpus(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "legend.py").write_text(
        "class Legend:\n"
        "    '''A legend; its draggable state must survive pickling.'''\n"
        "    def set_draggable(self, state):\n"
        "        self._draggable = state\n")
    (root / "pkg" / "session.py").write_text(
        "def load_figure(path):\n"
        "    '''Load a saved figure in a new session: set up the figure, show the figure.'''\n"
        "    figure = open(path).read()\n"
        "    return figure\n")
    (root / "INSTALL.md").write_text(
        "# Install\n\nCreate a virtual environment on Linux, then install with pip.\n"
        "Python 3.11 is supported.\n")
    (root / "pkg" / "books.py").write_text(
        "def flush_ledger(ledger):\n    '''Flush the ledger.'''\n    ledger.flush()\n")
    (root / "pkg" / "recovery.py").write_text(
        "def replay_journal(journal):\n    '''Replay the journal after a crash.'''\n"
        "    return journal.replay()\n")
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


def _top(pack, query, **options):
    with PackSelector(str(pack), enable_cache=False, **options) as selector:
        return [e.path for e in selector.select(query, budget_tokens=10**6, allow_escalation=False).evidence]


def test_title_terms_outweigh_the_body(pack):
    assert _top(pack, QUERY, title_weight=1, tf_cap=1)[0] != "pkg/legend.py"
    assert _top(pack, QUERY, tf_cap=1)[0] == "pkg/legend.py"
    assert _top(pack, QUERY)[0] == "pkg/legend.py"


def test_repeated_terms_count_more(pack):
    assert _top(pack, TF_QUERY, title_weight=1, tf_cap=1)[0] == "pkg/recovery.py"
    assert _top(pack, TF_QUERY, title_weight=1)[0] == "pkg/books.py"


def test_single_line_query_is_unweighted(pack):
    one_line = "ledger ledger ledger ledger journal replay"
    flat = _top(pack, one_line, title_weight=1, tf_cap=1)
    assert flat[0] == "pkg/recovery.py"
    # The same words over two lines are weighted: the repeated term then decides.
    assert _top(pack, "Totals\n" + one_line, title_weight=1)[0] == "pkg/books.py"
    assert _top(pack, one_line, title_weight=1) == flat
    for query in (TITLE, TITLE + "\n\n   \n", one_line):
        assert _top(pack, query) == _top(pack, query, title_weight=1, tf_cap=1)


@pytest.mark.parametrize("name", ["title_weight", "tf_cap"])
@pytest.mark.parametrize("value", [0, -1, 2.0, "3", True])
def test_weights_must_be_positive_integers(pack, name, value):
    with pytest.raises(ValueError, match=name):
        PackSelector(str(pack), **{name: value})


def test_cli_weights(pack):
    def cli(query, *extra):
        out = subprocess.run([sys.executable, "-m", "npk.cli", "query", str(pack), query, "--budget", "120",
                              *extra], capture_output=True, text=True, check=True).stdout
        return [item["span"] for item in json.loads(out)["evidence"]]

    def api(query, **options):
        with PackSelector(str(pack), enable_cache=False, **options) as selector:
            return [e.span for e in selector.select(query, budget_tokens=120).evidence]

    assert cli(QUERY) == api(QUERY)
    assert cli(QUERY, "--title-weight", "1", "--tf-cap", "1") == api(QUERY, title_weight=1, tf_cap=1)
    assert api(QUERY) != api(QUERY, title_weight=1, tf_cap=1)
    assert cli(TF_QUERY, "--title-weight", "1") == api(TF_QUERY, title_weight=1)
    assert cli(TF_QUERY, "--title-weight", "1", "--tf-cap", "1") == api(TF_QUERY, title_weight=1, tf_cap=1)

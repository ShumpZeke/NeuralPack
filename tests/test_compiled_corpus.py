import ast
from types import SimpleNamespace

import pytest

from benchmarks.compiled_corpus import build_corpus, context_files


def test_source_envelopes_preserve_ast_and_folder_scope(tmp_path):
    source = 'VALUE = 7\n\ndef run():\n    return VALUE\n'
    task = SimpleNamespace(id="case_1", context=f"```File: billing/limits.py\n{source}```\n")
    root = build_corpus(tmp_path, [task])
    actual = (root / "case_1/billing/limits.py").read_text(encoding="utf-8")
    assert actual == source
    assert isinstance(ast.parse(actual).body[-1], ast.FunctionDef)


def test_plain_conversation_does_not_become_fake_python(tmp_path):
    text = "User: hello\nAssistant: hi\n"
    root = build_corpus(tmp_path, [SimpleNamespace(id="dialogue", context=text)])
    assert (root / "dialogue/context.txt").read_text() == text


def test_conflicting_duplicate_paths_fail_instead_of_overwriting():
    with pytest.raises(ValueError, match="conflicting"):
        context_files("```File: x.py\nA = 1\n```\n```File: x.py\nA = 2\n```\n")


@pytest.mark.parametrize("name", ["../escape.py", "C:/outside.py", "/root.py", "..\\escape.py"])
def test_unsafe_fixture_paths_are_rejected(name):
    with pytest.raises(ValueError, match="unsafe"):
        context_files(f"```File: {name}\nX = 1\n```\n")

"""NPK-Bench gold extraction and scoring must be exact; decisions depend on it."""
import math

from benchmarks.npkbench.data import (Hunk, Task, _changed_lines, _distinctive, _nonblank_anchor,
                                      parse_patch, topical_doc)
from benchmarks.npkbench.metrics import bootstrap_diff, score, tokens_to_find

PATCH = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,3 +1,4 @@
+import logging
 import os
 import sys

@@ -10,7 +11,7 @@ def f():
     a = 1
     b = 2
     c = 3
-    return a + b
+    return a + b + c
     # tail


@@ -40,2 +41,3 @@ def g():
     x = 1
     y = 2
+    z = 3
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1,2 @@
+A = 1
+B = 2
"""


def test_patch_hunks_use_original_coordinates():
    hunks, new_files = parse_patch(PATCH)
    assert new_files == ["pkg/new.py"]
    assert hunks == [
        Hunk("pkg/mod.py", (), ((0, 1),)),     # insertion before line 1
        Hunk("pkg/mod.py", (13,), ()),          # the rewritten return line
        Hunk("pkg/mod.py", (), ((41, 42),)),   # append after original line 41
    ]


def test_hunk_lines_that_look_like_headers_are_content():
    patch = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -5,3 +5,3 @@\n"
             " keep\n---- a/looks_like_a_header\n++++ b/looks_like_a_header\n keep\n")
    hunks, _ = parse_patch(patch)
    assert hunks == [Hunk("x.py", (6,), ())]


def test_insertion_anchor_skips_blank_separator_lines():
    lines = ["class A:", "    x = 1", "", "", "class B:", "    y = 2"]
    # Inserting between the two blank lines resolves to the classes around them.
    assert _nonblank_anchor(lines, 3, 4) == (2, 5)
    assert _nonblank_anchor(lines, 0, 1) == (0, 1)
    assert _nonblank_anchor(["a", ""], 2, 3) == (1, 0)


def test_found_requires_same_path_and_overlap():
    hunk = Hunk("a.py", (10, 11), ())
    assert hunk.found_by([("a.py", 11, 20)])
    assert not hunk.found_by([("a.py", 12, 20)])
    assert not hunk.found_by([("b.py", 1, 100)])
    insert = Hunk("a.py", (), ((5, 9),))
    assert insert.found_by([("a.py", 9, 12)]) and insert.found_by([("a.py", 1, 5)])
    assert not insert.found_by([("a.py", 6, 8)])


def test_score_and_tokens_to_find():
    task = Task("t", "o/r", "c", "q", [Hunk("a.py", (10,), ()), Hunk("b.py", (3,), ())])
    s = score(task, [("a.py", 1, 20)])
    assert s["hunk_recall"] == 0.5 and s["file_recall"] == 0.5 and s["all_found"] == 0.0
    ranking = [("c.py", 1, 9, 100), ("a.py", 1, 20, 50), ("b.py", 1, 5, 25)]
    found = tokens_to_find(task, ranking)
    assert found == {"first_rank": 1, "tokens_to_first": 150, "tokens_to_all": 175}
    assert tokens_to_find(task, ranking[:2])["tokens_to_all"] is None


def test_bootstrap_is_deterministic_and_centered():
    a = [0.0, 1.0, 0.0, 1.0]
    b = [1.0, 1.0, 0.0, 1.0]
    mean, lo, hi = bootstrap_diff(a, b)
    assert mean == 0.25 and lo <= mean <= hi
    assert bootstrap_diff(a, b) == (mean, lo, hi)
    assert all(math.isnan(x) for x in bootstrap_diff([], []))


def test_docs_target_counts_only_topical_prose_pages():
    for path in ["docs/ref/settings.txt", "doc/usage/configuration.rst", "README.rst",
                 "docs/topics/http/urls.txt", "doc/extdev/deprecated.rst"]:
        assert topical_doc(path), path
    for path in ["CONTRIBUTORS.txt", "AUTHORS", "doc/whats-new.rst", "docs/releases/4.0.txt",
                 "doc/users/prev_whats_new/whats_new_3.0.rst", "CHANGES.rst", "doc/changelog.rst",
                 "doc/en/example/conftest.py", "requirements.txt", "docs/conf.py",
                 "doc/api/next_api_changes/behavior/123-XX.rst", "tests/docs/page.rst"]:
        assert not topical_doc(path), path


def test_fix_commit_matching_ignores_trivial_lines():
    added, removed = _changed_lines(PATCH)
    assert "import logging" in added and "return a + b" in removed
    assert "+++ b/pkg/mod.py" not in added and "b/pkg/mod.py" not in added
    assert _distinctive({")", "else:", "return a + b + c"}) == {"return a + b + c"}
    assert _distinctive({")", "x"}) == {")", "x"}  # nothing distinctive: keep all


def test_judge_applies_the_declared_rule(tmp_path):
    import json
    from benchmarks.npkbench.report import judge
    rows = []
    for i in range(40):
        for budget in (1024, 2048):
            base_fix, base_tests = 0.2, 0.1
            rows.append({"arm": "base", "instance_id": f"t{i}", "budget": budget, "hunk_recall": base_fix})
            rows.append({"arm": "base@tests", "instance_id": f"t{i}", "budget": budget, "hunk_recall": base_tests})
            # candidate: +1 fix site on every issue at 2K, a tests loss on one issue at 1K
            rows.append({"arm": "cand", "instance_id": f"t{i}", "budget": budget,
                         "hunk_recall": base_fix + (0.5 if budget == 2048 else 0.0)})
            rows.append({"arm": "cand@tests", "instance_id": f"t{i}", "budget": budget,
                         "hunk_recall": base_tests - (0.1 if (budget == 1024 and i == 0) else 0.0)})
    (tmp_path / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    result = judge(tmp_path, "base", "cand", ("", "@tests"))
    assert result["budgets"]["2048"]["fix"]["significant"] == "gain"
    assert result["significant_gain"] and result["no_significant_loss"]
    assert not result["utility_nonnegative"] and not result["passes"]   # U < 0 at 1K
    same = judge(tmp_path, "base", "base", ("", "@tests"))
    assert same["utility_nonnegative"] and not same["significant_gain"] and not same["passes"]

"""The test block mirroring the top implementation file follows it (E016b)."""
import importlib

from npk.pack import PackSelector, compile_pack, update_pack
from npk.pack.format import open_pack
from npk.pack.select import _mate_score

select_module = importlib.import_module("npk.pack.select")
QUERY = "backoff_delay() grows too fast for a retry attempt"


def _corpus(root, with_tests=True):
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "pkg" / "throttle.py").write_text(
        "def backoff_delay(attempt, base):\n    '''Exponential backoff delay for a retry attempt.'''\n"
        "    return base * 2 ** attempt\n")
    if with_tests:
        _tests(root)
    for i in range(20):
        (root / "pkg" / f"other{i}.py").write_text(
            f"def unrelated_{i}(value):\n    '''retry and delay words, but not backoff.'''\n    return value\n")


def _tests(root):
    (root / "tests" / "test_throttle.py").write_text(
        "from pkg.throttle import backoff_delay\n\n\n"
        "def test_backoff_delay_grows():\n    assert backoff_delay(2, 1) == 4\n\n\n"
        "def test_retry_attempt_zero():\n    '''retry attempt zero has no backoff delay growth'''\n"
        "    assert backoff_delay(0, 3) == 3\n\n\n"
        "def test_unrelated_value():\n    assert 1 + 1 == 2\n")


def _pack(tmp_path, with_tests=True):
    src = tmp_path / "src"
    src.mkdir()
    _corpus(src, with_tests)
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    return src, pack


def test_mate_score_prefers_the_mirroring_test_file():
    assert _mate_score("pkg/throttle.py", "tests/test_throttle.py") >= 2.0
    assert _mate_score("pkg/throttle.py", "tests/test_other.py") < 1.0


def test_mate_follows_top_implementation_block(tmp_path):
    _src, pack = _pack(tmp_path)
    with PackSelector(str(pack), enable_cache=False, enable_test_mate=True) as selector:
        chosen = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence
    assert chosen[0].path == "pkg/throttle.py"
    assert chosen[1].path == "tests/test_throttle.py" and "test_mate" in chosen[1].channels
    with PackSelector(str(pack), enable_cache=False, enable_test_mate=False) as selector:
        plain = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence
    assert all("test_mate" not in e.channels for e in plain)


def test_default_mate_is_budget_gated(tmp_path):
    _src, pack = _pack(tmp_path)
    with PackSelector(str(pack), enable_cache=False) as selector:  # enable_test_mate=None
        small = selector.select(QUERY, budget_tokens=select_module.TEST_MATE_MIN_BUDGET - 1).evidence
        large = selector.select(QUERY, budget_tokens=select_module.TEST_MATE_MIN_BUDGET).evidence
    assert all("test_mate" not in e.channels for e in small)
    assert any("test_mate" in e.channels for e in large)


def test_reused_ranking_matches_a_dedicated_query(tmp_path):
    _src, pack = _pack(tmp_path)
    with open_pack(pack) as con:
        paths = select_module._test_paths(con)
        deep = select_module._lexical_channel(con, QUERY, select_module.TEST_MATE_DEPTH)
        for exclude in (set(), {deep[0]}):
            reused = select_module._test_mate(con, QUERY, "pkg/throttle.py", exclude, paths, deep)
            dedicated = select_module._test_mate(con, QUERY, "pkg/throttle.py", exclude, paths, None)
            assert reused == dedicated is not None


def test_mate_sees_test_files_added_by_an_update(tmp_path):
    src, pack = _pack(tmp_path, with_tests=False)
    with PackSelector(str(pack), enable_cache=False, enable_test_mate=True) as selector:
        before = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence
        assert all("test_mate" not in e.channels for e in before)
        _tests(src)
        update_pack(pack, src)
        after = selector.select(QUERY, budget_tokens=10**6, allow_escalation=False).evidence
    assert any("test_mate" in e.channels and e.path == "tests/test_throttle.py" for e in after)


# --- E047: test-file conventions beyond Python ---------------------------------------

def test_test_paths_follow_each_languages_conventions():
    tests = ["packages/ui/src/Button/Button.test.js", "src/utils/__tests__/format.ts", "lib/x.spec.tsx",
             "core/src/test/java/io/x/TestFoo.java", "api/src/main/java/org/x/FooTest.java",
             "it/src/main/java/org/x/FooIT.java", "app/FooTests.cs", "tests/FooTest.php",
             "pkg/server_test.go", "src/format_unittest.cc", "spec/models/user_spec.rb",
             "tests/test_mod.py", "pkg/mod_test.py", "conftest.py"]
    code = ["src/Button/Button.js", "src/latest.js", "src/contest.ts", "api/src/main/java/org/x/Contest.java",
            "api/src/main/java/org/x/EDIT.java", "core/src/main/java/io/x/TestingFoo.java",
            "src/Testimonial.tsx", "pkg/server.go", "pkg/mod.py", "lib/protest.rb"]
    assert [p for p in tests if not select_module.TEST_PATH.search(p)] == []
    assert [p for p in code if select_module.TEST_PATH.search(p)] == []


def test_java_test_class_mirrors_its_subject():
    impl = "dubbo-config/src/main/java/org/apache/dubbo/config/ServiceConfig.java"
    own = "dubbo-config/src/test/java/org/apache/dubbo/config/ServiceConfigTest.java"
    sibling = "dubbo-config/src/test/java/org/apache/dubbo/config/AbstractConfigTest.java"
    assert _mate_score(impl, own) >= _mate_score(impl, sibling) + 2.0
    assert _mate_score("core/src/main/java/io/x/Foo.java", "core/src/test/java/io/x/TestFoo.java") >= 3.0
    assert _mate_score("core/src/main/java/io/x/Foo.java", "core/src/it/java/io/x/FooIT.java") >= 3.0


def test_shared_generic_parts_are_no_mirror():
    impl = "dubbo-config/src/main/java/org/apache/dubbo/config/ServiceConfig.java"
    assert _mate_score(impl, "dubbo-rpc/src/test/java/org/apache/dubbo/rpc/RpcContextTest.java") == 0.0


def test_colocated_js_test_is_the_mate(tmp_path):
    src = tmp_path / "src"
    for name in ("Button", "Card", "Menu"):
        (src / "src" / name).mkdir(parents=True)
    (src / "src" / "Button" / "Button.js").write_text(
        "export function Button(props) {\n  // the focus ripple starts on keyboard focus\n"
        "  return startRipple(props.focusRipple, props.disabled);\n}\n")
    (src / "src" / "Button" / "Button.test.js").write_text(
        "import { Button } from './Button';\n\ndescribe('Button', () => {\n"
        "  it('shows the focus ripple', () => {\n    expect(render(Button)).toBeTruthy();\n  });\n});\n")
    for name in ("Card", "Menu"):
        (src / "src" / name / f"{name}.js").write_text(
            f"export function {name}(props) {{\n  return props.children;\n}}\n")
        (src / "src" / name / f"{name}.test.js").write_text(
            f"describe('{name}', () => {{\n  it('renders', () => {{}});\n}});\n")
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    query = "Button focus ripple does not start on keyboard focus"
    with PackSelector(str(pack), enable_cache=False, enable_test_mate=True) as selector:
        chosen = selector.select(query, budget_tokens=10**6, allow_escalation=False).evidence
    assert chosen[0].path == "src/Button/Button.js"
    assert chosen[1].path == "src/Button/Button.test.js" and "test_mate" in chosen[1].channels

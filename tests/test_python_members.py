"""Counterexamples for the experimental method-boundary compiler."""
from npk.pack import PackSelector, compile_pack, update_pack, verify
from npk.pack.compile import split_source
from npk.pack.format import open_pack, load_blocks, read_manifest


def test_small_method_can_fit_without_unrelated_class_methods(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    source = "class Worker:\n" + "".join(
        f"    def helper_{i}(self):\n        return '{'x' * 300}'\n" for i in range(30))
    source += "    def target_value(self):\n        return 4242\n"
    (root / "worker.py").write_text(source, encoding="utf-8")
    old, new = tmp_path / "old.npk", tmp_path / "new.npk"
    compile_pack(root, old)
    compile_pack(root, new, python_members=True)
    assert PackSelector(old).select("target_value", budget_tokens=40).seed_failed
    result = PackSelector(new).select("target_value", budget_tokens=40)
    assert "return 4242" in result.context_text()
    assert "helper_" not in result.context_text()
    assert result.total_tokens <= 40
    assert verify(new)["ok"]


def test_nested_classes_decorators_and_context_keep_exact_source_spans():
    source = ("@decorate\nclass Outer(Base):\n    LIMIT = 7\n"
              "    @classmethod\n    def get(cls):\n        return cls.LIMIT\n"
              "    class Inner:\n        VALUE = 9\n"
              "        async def load(self):\n            return self.VALUE\n"
              "    # Dynamic class-body behavior must remain represented.\n"
              "    if FEATURE:\n        ALIAS = get\n")
    blocks = split_source(source,"python",python_members=True)
    names = {b.name for b in blocks}
    assert "Outer.get" in names and "Outer.Inner.load" in names
    lines = source.splitlines()
    covered = []
    for block in blocks:
        assert block.text == "\n".join(lines[block.start_line-1:block.end_line])
        covered.extend(range(block.start_line,block.end_line+1))
    for i,line in enumerate(lines,1):
        if line.strip():
            assert covered.count(i) == 1


def test_incremental_update_preserves_member_chunking(tmp_path):
    root=tmp_path/"src"; root.mkdir()
    path=root/"worker.py"
    path.write_text("class Worker:\n    def value(self):\n        return 7\n",encoding="utf-8")
    pack=tmp_path/"test.npk"
    compile_pack(root,pack,python_members=True)
    path.write_text("class Worker:\n    def value(self):\n        return 19\n",encoding="utf-8")
    update_pack(pack,root)
    with open_pack(pack) as con:
        assert read_manifest(con)["python_members"] == "1"
        methods = [b for b in load_blocks(con) if b.kind=="method"]
    assert len(methods)==1 and methods[0].name=="Worker.value"
    assert "return 19" in methods[0].text
    assert verify(pack)["ok"]

"""Language structure must become searchable metadata without changing evidence bytes."""
import sqlite3

import pytest

from npk.pack import PackSelector, compile_pack, update_pack, verify
from npk.pack.compile import split_source


def assert_exact_spans(source, blocks):
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    assert blocks
    for block in blocks:
        assert block.text == "\n".join(lines[block.start_line - 1:block.end_line])
    for left, right in zip(blocks, blocks[1:]):
        assert left.end_line < right.start_line


def test_rst_heading_paths_and_directives_are_named_without_false_code_headings():
    source = '''================
Connections
================

General engine material.

Engine Disposal
---------------

Dispose an engine after use.

.. class:: Engine

   Class-specific details.

Examples
~~~~~~~~

.. code-block:: python

   Fake Heading
   ------------
   print("still code")

More examples.
'''
    blocks = split_source(source, "rst")
    assert_exact_spans(source, blocks)
    names = [block.name for block in blocks]
    assert "Connections" in names
    assert "Connections > Engine Disposal" in names
    assert "Connections > Engine Disposal > class Engine" in names
    assert "Connections > Engine Disposal > Examples" in names
    assert "Connections > Engine Disposal > Examples > code-block python" in names
    assert not any(name and "Fake Heading" in name for name in names)


def test_rst_transition_and_short_adornment_are_not_headings():
    source = "Paragraph longer than the rule\n---\n\n----\n\nAfter the transition.\n"
    blocks = split_source(source, "rst")
    assert_exact_spans(source, blocks)
    assert all(block.name is None for block in blocks)


@pytest.mark.parametrize(
    ("language", "source", "leaf_names"),
    [
        ("javascript", '''const PRELUDE = 1;
export async function connect() {
  const closing = "}";
}
class Pool {
  close() { return "done"; }
}
''', {"connect", "Pool", "close"}),
        ("typescript", '''interface Options {
  timeout: number;
}
export class Pool {
  async close(): Promise<void> { return; }
}
''', {"Options", "Pool", "close"}),
        ("go", '''package pool
type Pool struct { size int }
func connect() { println("{") }
func (pool *Pool) Close() { println("}") }
''', {"Pool", "connect", "Close"}),
        ("rust", '''pub struct Pool { size: usize }
impl Pool {
    pub fn close(&self) { println!("}}"); }
}
''', {"Pool", "close"}),
        ("java", '''package demo;
public class Pool {
    public void close() { System.out.println("}"); }
}
''', {"Pool", "close"}),
        ("c", '''#include <stdio.h>
int connect(void) {
    puts("}"); /* } does not close the function */
    return 0;
}
''', {"connect"}),
        ("cpp", '''class Pool {
public:
    void close() { const char *value = "}"; }
};
int connect() { return 0; }
''', {"Pool", "close", "connect"}),
        ("csharp", '''namespace Demo {
public class Pool {
    public void Close() { var value = "}"; }
}
}
''', {"Demo", "Pool", "Close"}),
        ("php", '''<?php
class Pool {
    public function close() { return "}"; }
}
function connect() { return true; }
''', {"Pool", "close", "connect"}),
    ],
)
def test_brace_languages_have_exact_disjoint_named_definitions(language, source, leaf_names):
    blocks = split_source(source, language)
    assert_exact_spans(source, blocks)
    actual = {name.rsplit(".", 1)[-1] for name in (block.name for block in blocks) if name}
    assert leaf_names <= actual


def test_braces_in_multiline_comments_do_not_consume_the_next_function():
    source = '''int first(void) {
    /* misleading }
       and another { */
    return 1;
}
int second(void) {
    return 2;
}
'''
    blocks = split_source(source, "c")
    assert_exact_spans(source, blocks)
    named = {block.name: block for block in blocks if block.name}
    assert named["first"].end_line == 5
    assert named["second"].start_line == 6


def test_unclosed_brace_falls_back_to_unnamed_source_instead_of_dropping_it():
    source = "int incomplete(void) {\n    return 1;\n"
    blocks = split_source(source, "c")
    assert_exact_spans(source, blocks)
    assert "return 1" in "\n".join(block.text for block in blocks)
    assert all(block.name is None for block in blocks)


def test_rst_name_field_is_replaced_on_incremental_update(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manual = source / "manual.rst"
    manual.write_text("Connections\n===========\n\nEngine Disposal\n---------------\n\nDispose safely.\n")
    pack = tmp_path / "manual.npk"
    compile_pack(source, pack)
    selected = PackSelector(pack).select("Engine Disposal", budget_tokens=200)
    assert selected.evidence[0].name == "Connections > Engine Disposal"

    manual.write_text("Connections\n===========\n\nEngine Shutdown\n---------------\n\nShut down safely.\n")
    update_pack(pack, source)
    selected = PackSelector(pack).select("Engine Shutdown", budget_tokens=200)
    assert selected.evidence[0].name == "Connections > Engine Shutdown"
    with sqlite3.connect(pack) as con:
        assert con.execute(
            "SELECT 1 FROM lexical WHERE lexical MATCH ? LIMIT 1", ("name : disposal",)
        ).fetchone() is None
    assert verify(pack)["ok"]

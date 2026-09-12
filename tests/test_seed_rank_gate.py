"""The provenance guard must inspect a module, not a same-named public API."""
from pathlib import Path
from npk.pack import select
from benchmarks.seed_rank_gate import selector_module_path


def test_selector_source_is_found_when_package_exports_a_select_function():
    assert callable(select)
    source=selector_module_path()
    assert source==Path(__file__).resolve().parents[1]/'npk/pack/select.py'
    assert source.is_file()

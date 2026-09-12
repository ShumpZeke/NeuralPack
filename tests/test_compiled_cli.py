"""CLI results and exit codes must agree for automation callers."""
import json
import sqlite3

import pytest

from npk.cli import main


@pytest.fixture
def cli_pack(tmp_path, capsys):
    root = tmp_path / "src"
    root.mkdir()
    (root / "app.py").write_text("def run():\n    return RETRY_LIMIT\n", encoding="utf-8")
    (root / "settings.py").write_text("RETRY_LIMIT = 7\n", encoding="utf-8")
    pack = tmp_path / "project.npk"
    assert main(["compile", str(root), str(pack)]) == 0
    assert json.loads(capsys.readouterr().out)["dependency_index"] is False
    return root, pack


def test_cli_preserves_and_explicitly_changes_dependency_policy(cli_pack, capsys):
    root, pack = cli_pack
    for flags, expected in (([], False), (["--deps"], True), ([], True), (["--no-deps"], False)):
        assert main(["update", str(pack), str(root), *flags]) == 0
        assert json.loads(capsys.readouterr().out)["dependency_index"] is expected


def test_cli_update_supports_quick_flag(cli_pack, capsys):
    root, pack = cli_pack
    assert main(["update", str(pack), str(root), "--quick"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["files_indexed"] == 0
    assert res["files_skipped_unchanged"] == 2


def test_cli_failed_retrieval_returns_failure_exit_code(cli_pack, capsys):
    _, pack = cli_pack
    code = main(["query", str(pack), "zzqqwwmmzzqq"])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "fallback_required"
    assert code != 0


def test_cli_failed_verification_returns_failure_exit_code(cli_pack, capsys):
    _, pack = cli_pack
    with sqlite3.connect(pack) as con:
        con.execute("DELETE FROM symbols")
    code = main(["verify", str(pack)])
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert code != 0

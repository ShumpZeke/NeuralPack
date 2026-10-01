"""The scan keeps real source directories called env or venv and still skips virtualenvs (E059)."""
import pytest

from npk.pack import compile_pack, update_pack
from npk.pack.format import open_pack


def _write(root, files):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def _indexed(pack):
    with open_pack(pack) as con:
        return {row[0] for row in con.execute("SELECT path FROM files")}


def test_source_directories_named_env_are_kept_but_virtualenvs_are_not(tmp_path):
    _write(tmp_path / "src", {
        "keep.py": "x = 1\n",
        "src/uu/env/src/env.rs": "fn main() {}\n",            # a real source directory called env
        "plain_venv/venv/tool.py": "y = 1\n",                  # no virtualenv marker
        "cfg_venv/venv/pyvenv.cfg": "home = /usr\n", "cfg_venv/venv/lib/site.py": "z = 1\n",
        "bin_env/env/bin/activate": "#!/bin/sh\n", "bin_env/env/bin/tool.py": "z = 2\n",
        "win_env/env/Scripts/activate": "rem\n", "win_env/env/Scripts/tool.py": "z = 3\n",
        "node_modules/pkg/index.js": "x = 1\n", ".hidden/a.py": "x = 1\n", "dist/out.js": "x = 1\n",
    })
    pack = tmp_path / "p.npk"
    compile_pack(tmp_path / "src", pack)
    assert _indexed(pack) == {"keep.py", "src/uu/env/src/env.rs", "plain_venv/venv/tool.py"}


@pytest.mark.parametrize("name", ["env", "venv"])
def test_a_directory_with_only_a_marker_name_is_not_a_virtualenv(tmp_path, name):
    _write(tmp_path / "src", {f"{name}/module.py": "x = 1\n"})
    pack = tmp_path / "p.npk"
    compile_pack(tmp_path / "src", pack)
    assert _indexed(pack) == {f"{name}/module.py"}


def test_other_excluded_directories_stay_excluded_whatever_they_hold(tmp_path):
    _write(tmp_path / "src", {"keep.py": "x = 1\n", "dist/pyvenv.cfg": "home = /usr\n", "dist/a.py": "x = 1\n",
                              "secrets/bin/activate": "#!/bin/sh\n", "secrets/a.py": "x = 1\n",
                              ".venv/lib/a.py": "x = 1\n", "node_modules/a/index.js": "x = 1\n"})
    pack = tmp_path / "p.npk"
    compile_pack(tmp_path / "src", pack)
    assert _indexed(pack) == {"keep.py"}


def test_credential_names_are_still_excluded_inside_env_directories(tmp_path):
    _write(tmp_path / "src", {"keep.py": "x = 1\n", "credentials.json": "{}\n", "env/secret_key.py": "k = 1\n",
                              "env/.env": "A=1\n", "env/settings.py": "ok = 1\n"})
    pack = tmp_path / "p.npk"
    compile_pack(tmp_path / "src", pack)
    assert _indexed(pack) == {"keep.py", "env/settings.py"}


def test_update_adds_an_env_package_created_after_the_build(tmp_path):
    src = tmp_path / "src"
    _write(src, {"a.py": "x = 1\n"})
    pack = tmp_path / "p.npk"
    compile_pack(src, pack)
    _write(src, {"tools/env/new.py": "def f():\n    return 1\n"})
    update_pack(pack, src)
    assert _indexed(pack) == {"a.py", "tools/env/new.py"}

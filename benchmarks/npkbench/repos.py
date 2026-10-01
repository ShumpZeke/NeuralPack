"""Pinned source trees: blobless clones plus ``git archive`` exports per commit."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import Dict, List

from .data import HOME

REPOS = HOME / "repos"
TREES = HOME / "trees"


def clone_dir(repo: str) -> Path:
    return REPOS / repo.split("/", 1)[1]


def ensure_clone(repo: str) -> Path:
    import fcntl

    path = clone_dir(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Parallel workers may reach an absent clone together; serialize creation.
    with open(REPOS / f".{path.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (path / ".git").exists() and not (path / "HEAD").exists():
            tmp = path.with_name(path.name + ".partial")
            shutil.rmtree(tmp, ignore_errors=True)
            subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
                            f"https://github.com/{repo}.git", str(tmp)], check=True)
            tmp.rename(path)
    return path


def export_tree(repo: str, commit: str, dest: Path) -> Path:
    """Materialize the exact commit tree (no .git, no working-copy state)."""
    clone = ensure_clone(repo)
    dest.mkdir(parents=True, exist_ok=False)
    proc = subprocess.Popen(["git", "-C", str(clone), "archive", "--format=tar", commit],
                            stdout=subprocess.PIPE)
    assert proc.stdout is not None
    with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
        archive.extractall(dest, filter="tar")
    if proc.wait() != 0:
        raise RuntimeError(f"git archive failed for {repo}@{commit}")
    return dest


def remove_compile_blockers(root: Path) -> Dict[str, List[str]]:
    """Delete files the v8 compiler would reject, and report them.

    The v8 compiler aborts an entire build on one NUL-containing, non-UTF-8,
    oversized or credential-pattern file. A baseline run removes those files
    first so the rest of the repository can be measured; the removal list is
    part of every result row, so the accommodation is never silent.
    """
    from npk.pack.compile import EXCLUDED_DIRS, EXCLUDED_FILE_RE, MAX_FILE_BYTES, TEXT_SUFFIXES
    from npk.pack.source_policy import PATTERNS

    removed: Dict[str, List[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for name in filenames:
            if EXCLUDED_FILE_RE.search(name) or Path(name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            raw = path.read_bytes()
            reason = None
            if len(raw) > MAX_FILE_BYTES:
                reason = "oversize"
            elif b"\x00" in raw:
                reason = "nul"
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    reason = "non_utf8"
                else:
                    for label, pattern in PATTERNS:
                        if pattern.search(text):
                            reason = "credential_" + label
                            break
            if reason:
                removed.setdefault(reason, []).append(path.relative_to(root).as_posix())
                path.unlink()
    return removed


def scratch_tree(repo: str, commit: str) -> Path:
    TREES.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix=f"{repo.split('/')[1]}-{commit[:10]}-", dir=TREES))
    return export_tree(repo, commit, base / "src")


def drop_tree(tree: Path) -> None:
    shutil.rmtree(tree.parent, ignore_errors=True)

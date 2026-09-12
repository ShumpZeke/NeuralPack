"""Automated secret scanning and credential protection tests.

Design notes (post-audit hardening):

* Fixtures are CONSTRUCTED AT RUNTIME from repeated characters so that no
  credential-shaped literal ever appears in a tracked file. This lets the
  scanners below run with zero allowlists -- an allowlist is exactly how the
  previous leak survived.
* Scanners collect violations into a list and assert ONCE at the end. They never
  wrap an ``assert`` in ``try/except Exception``: ``AssertionError`` is an
  ``Exception``, so that pattern silently discards findings (the original bug).
* Unreadable or non-UTF-8 tracked text makes the scan incomplete, never clean.
  Error reports contain paths and exception classes, not file values.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess

import pytest

from npk.telemetry import redact_secrets

REPO_ROOT = Path(__file__).resolve().parents[1]

# Credential-shaped fixtures assembled at runtime; no literal key in the source.
SYNTHETIC_NVIDIA_KEY = "nvapi-" + ("A" * 64)
SYNTHETIC_OPENAI_KEY = "sk-" + ("B" * 32)

# Patterns for real credentials. Kept deliberately strict so synthetic fixtures
# (all-identical character runs) are still matched -- we do NOT exempt them from
# the scanners; instead they simply never appear as literals on disk.
CREDENTIAL_PATTERNS = {
    "nvidia": re.compile(r"nvapi-[A-Za-z0-9_\-]{30,}"),
    "openai": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "aws": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
}

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".jsonl", ".txt", ".toml", ".yml", ".yaml",
    ".cfg", ".ini", ".env", ".sh", ".ps1",
}


def _scan_text(text: str) -> list[str]:
    """Return the names of credential patterns found in *text*."""
    return [name for name, pat in CREDENTIAL_PATTERNS.items() if pat.search(text)]


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

def test_redact_secrets_masks_keys():
    raw = f"API call with Authorization: Bearer {SYNTHETIC_NVIDIA_KEY}"
    redacted = redact_secrets(raw)
    assert "nvapi-" not in redacted
    assert SYNTHETIC_NVIDIA_KEY not in redacted
    assert "[REDACTED_" in redacted

    d = {
        "user": "alice",
        "api_key": "secret123",
        "info": f"key is {SYNTHETIC_OPENAI_KEY}",
    }
    red_d = redact_secrets(d)
    assert "secret123" not in str(red_d)
    assert SYNTHETIC_OPENAI_KEY not in str(red_d)


def test_redact_secrets_handles_nested_structures():
    payload = {"outer": [{"inner": f"Bearer {SYNTHETIC_NVIDIA_KEY}"}]}
    assert SYNTHETIC_NVIDIA_KEY not in str(redact_secrets(payload))


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def test_gitignore_covers_env_files():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert ".env.*" in gitignore


def test_env_file_is_not_tracked():
    res = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert res.returncode != 0, ".env must never be tracked by git"


# --------------------------------------------------------------------------
# Working-tree scan
# --------------------------------------------------------------------------

def test_no_secrets_in_tracked_files():
    """Scan every git-tracked file. Assertion is OUTSIDE the read guard."""
    res = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    )

    violations: list[str] = []
    incomplete: list[str] = []
    for rel in res.stdout.splitlines():
        if not rel.strip():
            continue
        full = REPO_ROOT / rel
        if full.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            incomplete.append(f"{rel} ({type(error).__name__})")
            continue
        for kind in _scan_text(content):
            violations.append(f"{rel} ({kind})")

    problems=[]
    if incomplete:problems.append('Incomplete tracked-text scan: '+', '.join(incomplete))
    if violations:problems.append('Credential-shaped strings in tracked files: '+', '.join(violations))
    assert not problems, '; '.join(problems)


def test_scanner_actually_detects_a_planted_secret(tmp_path):
    """Guard against the scanner regressing into a no-op.

    The original scanner wrapped its assertion in ``except Exception: continue``,
    so it could never fail. This test proves the detection path works.
    """
    planted = tmp_path / "leaked.py"
    planted.write_text(f'KEY = "{SYNTHETIC_NVIDIA_KEY}"\n', encoding="utf-8")
    assert _scan_text(planted.read_text(encoding="utf-8")) == ["nvidia"]

    clean = tmp_path / "clean.py"
    clean.write_text('KEY = "not-a-credential"\n', encoding="utf-8")
    assert _scan_text(clean.read_text(encoding="utf-8")) == []


def test_assertion_is_not_swallowed_by_read_guard():
    """Regression: no broad exception handler may wrap credential assertions.

    The original scanner caught the base Exception class, which silently
    discarded the AssertionError that reported the leak. This parses the AST
    (so prose in docstrings is irrelevant) and rejects any handler that is bare
    or catches Exception/BaseException.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        caught = node.type
        if caught is None:
            offenders.append(f"bare except at line {node.lineno}")
        elif isinstance(caught, ast.Name) and caught.id in {"Exception", "BaseException"}:
            offenders.append(f"except {caught.id} at line {node.lineno}")

    assert not offenders, (
        "Overly broad exception handlers in the secret scanner can swallow "
        "AssertionError and silently discard findings: " + ", ".join(offenders)
    )


# --------------------------------------------------------------------------
# Git-history scan
# --------------------------------------------------------------------------

def test_no_secrets_in_git_history():
    """Scan every blob in the object store, including unreachable ones.

    A key removed from the working tree but left in history is still leaked the
    moment a remote is added.

    Implementation note: the obvious version (``git ls-tree`` per commit, then
    ``git show`` per file) re-reads identical blobs once per commit and spawns
    thousands of subprocesses -- it measured **439 seconds** here and dominated
    the whole test suite. Streaming every *unique* object through a single
    ``git cat-file --batch`` is equivalent, strictly more thorough (it also sees
    dangling objects that no commit references). Its current cost grows with the
    object store; historical timing is not a present-day latency guarantee.
    """
    listing = subprocess.run(
        ["git", "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    blob_ids = [
        line.split()[0] for line in listing.stdout.splitlines()
        if line.strip() and line.split()[1] == "blob"
    ]
    assert blob_ids, "no git objects found; is this a repository?"

    stream = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=REPO_ROOT,
        input="\n".join(blob_ids) + "\n",
        capture_output=True, text=True, errors="ignore", check=True,
    )

    violations: list[str] = []
    for chunk in stream.stdout.split("\n"):
        for kind in _scan_text(chunk):
            violations.append(kind)

    unique = sorted(set(violations))
    assert not unique, (
        f"Credential-shaped strings ({', '.join(unique)}) found in the git object "
        "store. History must be purged before adding a remote."
    )

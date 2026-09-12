"""Materialize benchmark file envelopes as source, without changing paths/code."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re


FILE_ENVELOPE = re.compile(r"^```File:[ \t]*([^\r\n]+)\r?\n(.*?)^```[ \t]*(?:\r?\n|$)",
                           re.MULTILINE | re.DOTALL)


def context_files(context: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in FILE_ENVELOPE.finditer(context):
        name, body = match.group(1).strip(), match.group(2)
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
            raise ValueError("unsafe fixture path")
        if name in files and files[name] != body:
            raise ValueError(f"fixture contains conflicting definitions for {name}")
        files[name] = body
    if "```File:" in context and not files:
        raise ValueError("malformed file envelope in fixture")
    return files or {"context.txt": context}


def build_corpus(tmp: Path, tasks) -> Path:
    root = tmp / "corpus"
    root.mkdir(parents=True, exist_ok=True)
    seen = set()
    for task in tasks:
        if task.id in seen or not re.fullmatch(r"[A-Za-z0-9_-]+", task.id):
            raise ValueError("duplicate or unsafe task id")
        seen.add(task.id)
        for name, body in context_files(task.context).items():
            target = root / task.id / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8", newline="")
    return root

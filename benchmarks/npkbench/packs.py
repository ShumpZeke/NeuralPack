"""Build and cache one compiled pack per (task, compiler fingerprint, options)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any, Dict, Optional

from .data import HOME, Task
from . import repos

PACKS = HOME / "packs"
ROOT = Path(__file__).resolve().parents[2]
# Every module that can change stored artifact contents. A change to any of
# them yields a new fingerprint, so a stale pack can never be reused silently.
COMPILER_SOURCES = ("compile.py", "search.py", "conflict.py", "source_policy.py",
                    "format.py", "integrity.py")


def compiler_fingerprint(options: Optional[Dict[str, Any]] = None) -> str:
    digest = hashlib.sha256()
    for name in COMPILER_SOURCES:
        digest.update(name.encode() + b"\0")
        digest.update((ROOT / "npk" / "pack" / name).read_bytes())
    digest.update(json.dumps(options or {}, sort_keys=True).encode())
    return digest.hexdigest()[:16]


def pack_path(task: Task, options: Optional[Dict[str, Any]] = None) -> Path:
    return PACKS / compiler_fingerprint(options) / f"{task.instance_id}.npk"


def ensure_pack(task: Task, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return build metadata; compile only when this exact pack is absent."""
    from npk.pack import compile_pack

    path = pack_path(task, options)
    meta_path = path.with_suffix(".json")
    if path.exists() and meta_path.exists():
        return json.loads(meta_path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    tree = repos.scratch_tree(task.repo, task.base_commit)
    try:
        export_s = time.perf_counter() - started
        removed = repos.remove_compile_blockers(tree)
        t0 = time.perf_counter()
        stats = compile_pack(tree, path, **(options or {}))
        compile_s = time.perf_counter() - t0
    finally:
        repos.drop_tree(tree)
    meta = {
        "instance_id": task.instance_id, "fingerprint": compiler_fingerprint(options),
        "options": options or {}, "export_s": round(export_s, 3),
        "compile_s": round(compile_s, 3), "pack_bytes": path.stat().st_size,
        "blockers_removed": removed, "stats": stats.as_dict(),
    }
    tmp = meta_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=1, sort_keys=True))
    tmp.replace(meta_path)
    return meta

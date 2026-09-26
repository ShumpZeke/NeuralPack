"""Pinned SWE-bench task data and gold edit locations derived from reference patches."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Sequence, Tuple
import urllib.request

HOME = Path(os.environ.get("NPK_BENCH_HOME", Path.home() / "npk-data"))

# Exact files, revisions and digests. A changed upstream dataset cannot silently
# change the benchmark: download() rejects any byte difference.
SOURCES = {
    "swe_lite_test": (
        "princeton-nlp/SWE-bench_Lite", "6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2",
        "data/test-00000-of-00001.parquet",
        "7a21f37b8bc179c7db5beeb14e88ac538ba283455c776e6b2535bbfb6e3551b4"),
    "swe_lite_dev": (
        "princeton-nlp/SWE-bench_Lite", "6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2",
        "data/dev-00000-of-00001.parquet",
        "8312f321838051849d2fa7c6ca071244733a3e90bb517ff6ca8186f722199b5c"),
    "swe_verified_test": (
        "princeton-nlp/SWE-bench_Verified", "c104f840cc67f8b6eec6f759ebc8b2693d585d4a",
        "data/test-00000-of-00001.parquet",
        "a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd"),
}

# 1.1: insertion anchors resolve to the nearest non-blank original lines, so
# a method appended at the end of a class is located by the class itself.
BENCH_VERSION = "npkbench-1.1"


def download(name: str) -> Path:
    repo, revision, path, digest = SOURCES[name]
    target = HOME / "datasets" / f"{name}-{digest[:12]}.parquet"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}"
        with urllib.request.urlopen(url, timeout=120) as response:
            body = response.read()
        if hashlib.sha256(body).hexdigest() != digest:
            raise RuntimeError(f"{name}: downloaded bytes do not match pinned digest")
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"{name}: cached bytes do not match pinned digest")
    return target


@dataclass(frozen=True)
class Hunk:
    """Edit location in ORIGINAL (base commit) line coordinates.

    ``removed`` lists original lines the fix deletes or rewrites. ``anchors``
    lists (before, after) original-line neighbours of pure insertions; either
    neighbour being visible is enough to see where the insertion goes.
    """
    path: str
    removed: Tuple[int, ...]
    anchors: Tuple[Tuple[int, int], ...]

    def found_by(self, spans: Sequence[Tuple[str, int, int]]) -> bool:
        mine = [(lo, hi) for path, lo, hi in spans if path == self.path]
        if not mine:
            return False
        def seen(line: int) -> bool:
            return any(lo <= line <= hi for lo, hi in mine)
        return (any(seen(x) for x in self.removed)
                or any(seen(a) or seen(b) for a, b in self.anchors))

    def lines(self) -> Tuple[int, ...]:
        """Representative gold lines: removals, else each insertion's left anchor."""
        if self.removed:
            return self.removed
        return tuple(a if a > 0 else b for a, b in self.anchors)


@dataclass
class Task:
    instance_id: str
    repo: str
    base_commit: str
    query: str
    hunks: List[Hunk]
    created_at: str = ""
    source: str = ""
    new_files: List[str] = field(default_factory=list)

    @property
    def files(self) -> List[str]:
        return sorted({h.path for h in self.hunks})


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(patch: str) -> Tuple[List[Hunk], List[str]]:
    """Parse a unified git diff into original-coordinate edit locations."""
    hunks: List[Hunk] = []
    new_files: List[str] = []
    path: Optional[str] = None
    is_new = False
    lines = patch.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            path, is_new = None, False
        elif line.startswith("--- "):
            is_new = line.strip() == "--- /dev/null"
            if not is_new:
                path = line[4:].strip()
                path = path[2:] if path.startswith("a/") else path
        elif line.startswith("+++ ") and is_new:
            added = line[4:].strip()
            new_files.append(added[2:] if added.startswith("b/") else added)
        elif line.startswith("@@") and path is not None and not is_new:
            match = HUNK_RE.match(line)
            if match is None:
                raise ValueError(f"bad hunk header: {line!r}")
            orig = int(match.group(1))
            old_left = int(match.group(2) or 1)
            new_left = int(match.group(4) or 1)
            removed: List[int] = []
            anchors: List[Tuple[int, int]] = []
            pending_insert = False
            i += 1
            # Header counts bound the hunk, so body lines that happen to look
            # like diff headers are still read as content.
            while i < len(lines) and (old_left > 0 or new_left > 0):
                body = lines[i]
                if body.startswith("\\"):
                    i += 1
                    continue
                tag = body[:1]
                if tag == "-":
                    removed.append(orig)
                    orig += 1
                    old_left -= 1
                    pending_insert = False
                elif tag == "+":
                    if not pending_insert:
                        anchors.append((orig - 1, orig))
                        pending_insert = True
                    new_left -= 1
                else:
                    # ' ' context, or an empty line whose single space was stripped.
                    orig += 1
                    old_left -= 1
                    new_left -= 1
                    pending_insert = False
                i += 1
            # Insertions adjacent to removed lines are already located by them.
            if removed:
                anchors = []
            hunks.append(Hunk(path, tuple(removed), tuple(anchors)))
            continue
        i += 1
    return hunks, new_files


def _nonblank_anchor(lines: Sequence[str], before: int, after: int) -> Tuple[int, int]:
    """Nearest non-blank original lines around an insertion point (0 = none)."""
    lo = before
    while lo >= 1 and not lines[lo - 1].strip():
        lo -= 1
    hi = after
    while 1 <= hi <= len(lines) and not lines[hi - 1].strip():
        hi += 1
    return (max(lo, 0), hi if 1 <= hi <= len(lines) else 0)


def _refine(tasks: List[Task], name: str) -> None:
    """Resolve insertion anchors against base-commit file text (cached)."""
    import json
    import subprocess

    cache_path = HOME / "gold" / f"{name}-{BENCH_VERSION}.json"
    cache: Dict[str, list] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    changed = False
    for task in tasks:
        if task.instance_id not in cache:
            from .repos import ensure_clone
            refined = []
            texts: Dict[str, List[str]] = {}
            for hunk in task.hunks:
                anchors = list(hunk.anchors)
                if anchors:
                    if hunk.path not in texts:
                        clone = ensure_clone(task.repo)
                        body = subprocess.run(
                            ["git", "-C", str(clone), "show", f"{task.base_commit}:{hunk.path}"],
                            capture_output=True, check=True).stdout.decode("utf-8", "replace")
                        texts[hunk.path] = body.split("\n")
                    anchors = [list(_nonblank_anchor(texts[hunk.path], a, b)) for a, b in anchors]
                refined.append([hunk.path, list(hunk.removed), anchors])
            cache[task.instance_id] = refined
            changed = True
        task.hunks = [Hunk(path, tuple(removed), tuple(tuple(a) for a in anchors))
                      for path, removed, anchors in cache[task.instance_id]]
    if changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, sort_keys=True))
        tmp.replace(cache_path)


def load(name: str) -> List[Task]:
    import pyarrow.parquet as pq

    rows = pq.read_table(download(name)).to_pylist()
    tasks = []
    for row in rows:
        hunks, new_files = parse_patch(row["patch"])
        tasks.append(Task(
            instance_id=row["instance_id"], repo=row["repo"], base_commit=row["base_commit"],
            query=row["problem_statement"], hunks=hunks, created_at=row["created_at"],
            source=name, new_files=new_files,
        ))
    _refine(tasks, name)
    return tasks


def _stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def split(name: str) -> List[Task]:
    """Return a named split. Membership rules are fixed; see package docstring."""
    if name == "dev":
        return load("swe_lite_test")
    if name == "dev-fast":
        tasks = load("swe_lite_test")
        by_repo: Dict[str, List[Task]] = {}
        for task in tasks:
            by_repo.setdefault(task.repo, []).append(task)
        chosen: List[Task] = []
        # Proportional allocation with at least two tasks per repository.
        for repo, items in sorted(by_repo.items()):
            items.sort(key=lambda t: _stable_hash("dev-fast:" + t.instance_id))
            quota = max(2, round(100 * len(items) / len(tasks)))
            chosen.extend(items[:quota])
        return sorted(chosen, key=lambda t: t.instance_id)
    if name == "heldout":
        lite = {t.instance_id for t in load("swe_lite_test")}
        return [t for t in load("swe_verified_test") if t.instance_id not in lite]
    if name == "ood":
        return load("swe_lite_dev")
    raise ValueError(f"unknown split {name!r}")

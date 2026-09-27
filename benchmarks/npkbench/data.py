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
    # Added 2026-09-26: non-Python repositories (C/C++, Go, Java, JS/TS, PHP, Ruby,
    # Rust), MIT licensed. Measurement only (ood-multi*); never tuned on.
    "swe_multi_test": (
        "SWE-bench/SWE-bench_Multilingual", "846e647b9f33c0b51b739d005d13d85493c9af09",
        "data/test-00000-of-00001.parquet",
        "92abca7cb527b41a9f66d03a26ce441ff7319e3a49f985998fd56be4bb9b08b2"),
    # Added 2026-09-27 for non-Python development at scale (MIT licence): the verified
    # 500-issue subset of SWE-PolyBench, 125 each of Java, JavaScript, TypeScript and Python.
    "polybench500": (
        "AmazonScience/SWE-PolyBench_500", "546075b4b05d17ba914e72b8f4c6d5b1ea150c1d",
        "test.csv",
        "20961b616b404875adead16dd456adc4cf583035436fc0d7e9c3f2adf8322e0c"),
    # Added 2026-09-27: the full SWE-PolyBench (2,110 issues, MIT). Its Java/JS/TS issues
    # outside the 500-issue subset give a larger development set (poly-dev-b).
    "polybench_full": (
        "AmazonScience/SWE-PolyBench", "d56445f9940eae4e9d2974ec66820c2f1d7754e6",
        "test.csv",
        "17ad661b20e9af1e2067fbbc2e2658a21137d56693570d1d07f966d8bc0408b7"),
    # Added 2026-09-26 for a second confirmation split (heldout-b); never tuned on.
    "swe_full_test": (
        "princeton-nlp/SWE-bench", "e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6",
        "data/test-00000-of-00001.parquet",
        "db4f70ef735b3162c74801ddcdf8d7bae8d704193788c6d844f898c20b571cbb"),
}

# 1.1: insertion anchors resolve to the nearest non-blank original lines, so
# a method appended at the end of a class is located by the class itself.
BENCH_VERSION = "npkbench-1.1"


def download(name: str) -> Path:
    repo, revision, path, digest = SOURCES[name]
    suffix = Path(path).suffix or ".parquet"
    target = HOME / "datasets" / f"{name}-{digest[:12]}{suffix}"
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
    lo = min(before, len(lines))   # an end-of-file insertion can point one past the last line
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


#: Gold targets. ``fix``: lines the reference fix edits (implementation).
#: ``tests``: lines of existing test files the reference test patch edits,
#: i.e. where maintainers put the regression test. ``docs``: lines of topical
#: documentation (not release notes) that the maintainers' upstream fix
#: commit edited. The same query and pack serve every target, so a selector
#: cannot win one by ignoring another.
TARGETS = ("fix", "tests", "docs")

#: Version of the docs-target construction (independent of BENCH_VERSION so
#: fix/tests gold stays byte-identical). docs-3: the upstream fix is the first
#: commit whose diff reproduces the reference patch (>= 60% of its distinctive
#: changed lines), widened to its pull request when a GitHub PR merge
#: introduced it (never to branch-integration merges such as 3.x -> master);
#: only topical prose pages count as documentation. (docs-2 widened to any
#: first-parent merge and swallowed integration merges; it was never used.)
DOCS_VERSION = "docs-3"
DOCS_MIN_OVERLAP = 0.6
DOCS_MAX_RANGE_FILES = 200
NOT_TOPICAL = re.compile(
    r"whats[-_]?new|release|change[-_]?log|(^|/)changes?(/|\.|$)|(^|/)news(/|\.|$)|upcoming[-_]changes"
    r"|api[-_]changes|history|contributors|authors|contributing|code[-_]of[-_]conduct|(^|/)\."
    r"|(^|/)tests?/", re.I)
PROSE = re.compile(r"\.(rst|md|txt|rest|adoc)$", re.I)
DOC_DIR = re.compile(r"(^|/)(docs?|doc_src|documentation)/", re.I)


def topical_doc(path: str) -> bool:
    """A prose documentation page that is not release notes or a people list."""
    if NOT_TOPICAL.search(path) or not PROSE.search(path):
        return False
    return bool(DOC_DIR.search(path)) or not path.lower().endswith(".txt")


def _git(clone, *args) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True,
                          check=True).stdout


def _changed_lines(diff: str) -> Tuple[set, set]:
    added, removed = set(), set()
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line[:1] in "+-" and line[1:].strip():
            (added if line[0] == "+" else removed).add(line[1:].strip())
    return added, removed


def _distinctive(lines: set) -> set:
    kept = {l for l in lines if len(l) >= 8 and re.search(r"[A-Za-z0-9_]{3}", l)}
    return kept or lines


def _is_ancestor(clone, older: str, newer: str) -> bool:
    import subprocess
    return subprocess.run(["git", "-C", str(clone), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True).returncode == 0


_FIRST_PARENT: Dict[str, set] = {}


def _find_fix_commit(clone, base: str, head: str, files: Sequence[str], ref_patch: str,
                     limit: int = 15) -> Tuple[Optional[str], float]:
    ref_add, ref_rm = _changed_lines(ref_patch)
    use_added = bool(ref_add)
    ref = _distinctive(ref_add if use_added else ref_rm)
    if not ref:
        return None, 0.0
    best = 0.0
    commits = _git(clone, "log", "--format=%H", "--reverse", f"{base}..{head}", "--", *files).split()
    for commit in commits[:limit]:
        add, rm = _changed_lines(_git(clone, "show", "--format=", commit, "--", *files))
        overlap = len(ref & (add if use_added else rm)) / len(ref)
        if overlap >= DOCS_MIN_OVERLAP:
            return commit, overlap
        best = max(best, overlap)
    return None, best


def _docs_patch(task: "Task", ref_patch: str) -> Tuple[str, Dict]:
    """Topical-docs part of the upstream change that shipped the fix.

    Hunk coordinates are exact for the compiled base snapshot: a docs file is
    kept only when it is unchanged between ``base_commit`` and the start of
    the upstream change.
    """
    from .repos import ensure_clone

    clone = ensure_clone(task.repo)
    head = _git(clone, "rev-parse", "--abbrev-ref", "origin/HEAD").strip() or "origin/main"
    meta: Dict = {"version": DOCS_VERSION, "commit": None, "overlap": 0.0, "merge": None,
                  "docs_files": [], "dropped_changed_since_base": []}
    commit, overlap = _find_fix_commit(clone, task.base_commit, head, task.files, ref_patch)
    meta["overlap"] = round(overlap, 3)
    if commit is None:
        return "", meta
    meta["commit"] = commit
    lo, hi = f"{commit}^", commit
    key = str(clone)
    if key not in _FIRST_PARENT:
        _FIRST_PARENT[key] = set(_git(clone, "rev-list", "--first-parent", head).split())
    if commit not in _FIRST_PARENT[key]:
        # The merge that introduced the fix: the oldest merge descending from it
        # whose first parent does not already contain it.
        merges = _git(clone, "rev-list", "--ancestry-path", "--merges", "--topo-order", "--reverse",
                      f"{commit}..{head}").split()
        for merge in merges[:200]:
            parents = _git(clone, "rev-list", "--parents", "-n", "1", merge).split()[1:]
            if len(parents) != 2 or _is_ancestor(clone, commit, parents[0]):
                continue
            subject = _git(clone, "log", "-1", "--format=%s", merge)
            if subject.startswith("Merge pull request #"):
                fork = _git(clone, "merge-base", parents[0], parents[1]).strip()
                if len(_git(clone, "diff", "--name-only", fork, parents[1]).split()) <= DOCS_MAX_RANGE_FILES:
                    lo, hi, meta["merge"] = fork, parents[1], merge
            break
    touched = _git(clone, "diff", "--name-only", lo, hi).split()
    kept = []
    for f in sorted(f for f in touched if topical_doc(f)):
        unchanged = not _git(clone, "diff", "--name-only", task.base_commit, lo, "--", f).strip()
        (kept if unchanged else meta["dropped_changed_since_base"]).append(f)
    meta["docs_files"] = kept
    if not kept:
        return "", meta
    return _git(clone, "diff", lo, hi, "--", *kept), meta


#: SWE-PolyBench repositories left out of the benchmark: vscode and angular are too large
#: for this machine's clone budget, guava has two issues; Python issues are left out
#: because the Python splits are already large.
POLY_EXCLUDED_REPOS = frozenset({"microsoft/vscode", "angular/angular", "google/guava"})
#: poly-dev-b: at most this many issues per repository (fixed hash order).
POLY_DEV_B_PER_REPO = 80


def _rows(name: str) -> List[Dict[str, object]]:
    if name == "polybench_heldoutb":
        # poly-heldout-b, declared 2026-09-27 before any result on it: the full SWE-PolyBench's
        # Java/JS/TS issues outside its 500-issue subset and outside poly-dev-b, minus
        # POLY_EXCLUDED_REPOS, at most POLY_DEV_B_PER_REPO per repository by a fixed hash.
        # Confirmation only (JS/TS; the Java issues outside the 500 all went to poly-dev-b).
        taken = ({row["instance_id"] for row in _rows("polybench500")}
                 | {row["instance_id"] for row in _rows("polybench_devb")})
        by_repo_h: Dict[str, List[Dict[str, object]]] = {}
        for row in _rows("polybench_full"):
            if row["instance_id"] not in taken:
                by_repo_h.setdefault(str(row["repo"]), []).append(row)
        chosen_h: List[Dict[str, object]] = []
        for _repo, items in sorted(by_repo_h.items()):
            items.sort(key=lambda row: _stable_hash("poly-hb:" + str(row["instance_id"])))
            chosen_h.extend(items[:POLY_DEV_B_PER_REPO])
        return sorted(chosen_h, key=lambda row: str(row["instance_id"]))
    if name == "polybench_devb":
        # poly-dev-b, declared 2026-09-27 before any result on it: the full SWE-PolyBench's
        # Java/JS/TS issues outside its 500-issue subset (so disjoint from poly-dev and
        # poly-heldout), minus POLY_EXCLUDED_REPOS, at most POLY_DEV_B_PER_REPO per
        # repository by a fixed hash. Only these rows are loaded (gold refinement fetches
        # base-commit files, so the rest of the full set is never touched).
        taken = {row["instance_id"] for row in _rows("polybench500")}
        by_repo: Dict[str, List[Dict[str, object]]] = {}
        for row in _rows("polybench_full"):
            if row["instance_id"] not in taken:
                by_repo.setdefault(str(row["repo"]), []).append(row)
        chosen: List[Dict[str, object]] = []
        for _repo, items in sorted(by_repo.items()):
            items.sort(key=lambda row: _stable_hash("poly-b:" + str(row["instance_id"])))
            chosen.extend(items[:POLY_DEV_B_PER_REPO])
        return sorted(chosen, key=lambda row: str(row["instance_id"]))
    path = download(name)
    if path.suffix == ".csv":
        import csv
        import sys
        csv.field_size_limit(sys.maxsize)
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if name in ("polybench500", "polybench_full"):
            rows = [row for row in rows if row["language"] != "Python"
                    and row["repo"] not in POLY_EXCLUDED_REPOS]
        return rows
    import pyarrow.parquet as pq
    return pq.read_table(path).to_pylist()


def load(name: str, target: str = "fix") -> List[Task]:
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}")
    rows = _rows(name)
    tasks = []
    docs_cache: Dict[str, list] = {}
    docs_cache_path = HOME / "gold" / f"{name}-docs-patches-{DOCS_VERSION}.json"
    if target == "docs" and docs_cache_path.exists():
        import json
        docs_cache = json.loads(docs_cache_path.read_text())
    for row in rows:
        if target == "docs":
            fix_hunks, _ = parse_patch(row["patch"])
            probe = Task(row["instance_id"], row["repo"], row["base_commit"], "", fix_hunks)
            if row["instance_id"] not in docs_cache:
                patch, meta = _docs_patch(probe, row["patch"])
                docs_cache[row["instance_id"]] = [patch, meta]
            hunks, new_files = parse_patch(docs_cache[row["instance_id"]][0])
        else:
            hunks, new_files = parse_patch(row["patch" if target == "fix" else "test_patch"])
        if not hunks:
            continue  # e.g. a test patch that only adds new files
        tasks.append(Task(
            instance_id=row["instance_id"], repo=row["repo"], base_commit=row["base_commit"],
            query=row["problem_statement"], hunks=hunks, created_at=row["created_at"],
            source=name, new_files=new_files,
        ))
    if target == "docs":
        import json
        docs_cache_path.parent.mkdir(parents=True, exist_ok=True)
        docs_cache_path.write_text(json.dumps(docs_cache, sort_keys=True))
    _refine(tasks, {"fix": name, "tests": f"{name}-tests"}.get(target, f"{name}-{DOCS_VERSION}"))
    return tasks


def _stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def split(name: str) -> List[Task]:
    """Return a named split. Membership rules are fixed; see package docstring.

    ``<split>:tests`` scores the same tasks against the test-patch target.
    Task membership is decided on the fix target, so both views of a split
    contain the same issues (minus any whose test patch only adds files).
    """
    if name.startswith("memory"):
        from . import memory
        return memory.split(name)
    base, _, target = name.partition(":")
    if target and base == "long-queries":
        wanted = {t.instance_id for t in split(base)}
        chosen: Dict[str, Task] = {}
        for ds in ("swe_lite_test", "swe_full_test", "swe_multi_test"):   # dev issues are also in full
            for t in load(ds, target):
                if t.instance_id in wanted:
                    chosen.setdefault(t.instance_id, t)
        return sorted(chosen.values(), key=lambda t: t.instance_id)
    if target:
        wanted = {t.instance_id for t in split(base)}
        dataset = {"dev": "swe_lite_test", "dev-fast": "swe_lite_test",
                   "heldout": "swe_verified_test", "ood": "swe_lite_dev",
                   "heldout-b": "swe_full_test", "heldout-b-all": "swe_full_test",
                   "heldout-c": "swe_full_test", "heldout-d": "swe_full_test",
                   "heldout-e": "swe_full_test",
                   "ood-multi": "swe_multi_test", "ood-multi-sample": "swe_multi_test",
                   "ood-multi-dev": "swe_multi_test",
                   "poly-dev": "polybench500", "poly-heldout": "polybench500",
                   "poly-dev-b": "polybench_devb", "poly-heldout-b": "polybench_heldoutb"}[base]
        lite = {t.instance_id for t in load("swe_lite_test")} if base == "heldout" else set()
        return [t for t in load(dataset, target)
                if t.instance_id in wanted and t.instance_id not in lite]
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
    if name == "ood-multi-dev":
        # Declared 2026-09-26 before any ood-multi result: the 186 multilingual issues
        # outside ood-multi-sample, for developing non-Python handling. Changes found
        # here are then measured on ood-multi-sample.
        sample = {t.instance_id for t in split("ood-multi-sample")}
        return [t for t in load("swe_multi_test") if t.instance_id not in sample]
    if name in ("ood-multi", "ood-multi-sample"):
        # Non-Python generalization (declared 2026-09-26, measurement only). The
        # sample keeps at most 3 issues per repository (41 repositories), in a fixed
        # hash order, to bound clone and compile cost.
        rows = load("swe_multi_test")
        if name == "ood-multi":
            return rows
        by_repo_m: Dict[str, List[Task]] = {}
        for task in rows:
            by_repo_m.setdefault(task.repo, []).append(task)
        chosen_m = []
        for repo, items in sorted(by_repo_m.items()):
            items.sort(key=lambda t: _stable_hash("ood-multi:" + t.instance_id))
            chosen_m.extend(items[:3])
        return sorted(chosen_m, key=lambda t: t.instance_id)
    if name == "heldout-c":
        # Third confirmation split (declared 2026-09-26, after heldout-b was spent on
        # E016c/HB01): a fixed stratified 400 of heldout-b-all minus heldout-b.
        spent = {t.instance_id for t in split("heldout-b")}
        rest = [t for t in split("heldout-b-all") if t.instance_id not in spent]
        by_repo_c: Dict[str, List[Task]] = {}
        for task in rest:
            by_repo_c.setdefault(task.repo, []).append(task)
        chosen_c = []
        for repo, items in sorted(by_repo_c.items()):
            items.sort(key=lambda t: _stable_hash("heldout-c:" + t.instance_id))
            chosen_c.extend(items[:max(2, round(400 * len(items) / len(rest)))])
        return sorted(chosen_c, key=lambda t: t.instance_id)
    if name in ("poly-dev", "poly-heldout"):
        # Declared 2026-09-27 before any result on SWE-PolyBench: its Java/JS/TS issues
        # (minus POLY_EXCLUDED_REPOS), split per repository by a fixed hash, about 60%
        # for development (poly-dev) and 40% for confirmation only (poly-heldout).
        by_repo_p: Dict[str, List[Task]] = {}
        for task in load("polybench500"):
            by_repo_p.setdefault(task.repo, []).append(task)
        chosen_p: List[Task] = []
        for repo, items in sorted(by_repo_p.items()):
            items.sort(key=lambda t: _stable_hash("poly:" + t.instance_id))
            cut = round(0.6 * len(items))
            chosen_p.extend(items[:cut] if name == "poly-dev" else items[cut:])
        return sorted(chosen_p, key=lambda t: t.instance_id)
    if name == "poly-dev-b":
        return load("polybench_devb")
    if name == "poly-heldout-b":
        return load("polybench_heldoutb")
    if name == "long-queries":
        # Diagnostic split (declared 2026-09-27 for E043, the query-term cap): the issues of
        # dev, ood-multi-dev and the spent heldout-b/c/d whose cleaned query has more than
        # 512 distinct lexical terms (heldout-e is left untouched). Frozen by ID.
        wanted = {"pydata__xarray-5662", "fastlane__fastlane-19207", "pydata__xarray-3637",
                  "scikit-learn__scikit-learn-11346", "matplotlib__matplotlib-21550",
                  "prometheus__prometheus-11859", "matplotlib__matplotlib-26020",
                  "sphinx-doc__sphinx-9104", "pylint-dev__pylint-7080",
                  "scikit-learn__scikit-learn-25308"}
        pool = {t.instance_id: t for s in ("dev", "heldout-b", "heldout-c", "heldout-d", "ood-multi-dev")
                for t in split(s)}
        return sorted((pool[i] for i in wanted), key=lambda t: t.instance_id)
    if name == "heldout-e":
        # Fifth confirmation split (declared 2026-09-27, before any result on it, after
        # heldout-d was spent on E039/HD01): every issue of heldout-b-all not in
        # heldout-b, heldout-c or heldout-d.
        spent = set()
        for other in ("heldout-b", "heldout-c", "heldout-d"):
            spent |= {t.instance_id for t in split(other)}
        return [t for t in split("heldout-b-all") if t.instance_id not in spent]
    if name == "heldout-d":
        # Fourth confirmation split (declared 2026-09-27, before any result on it, while
        # heldout-c was being spent on E031/HC01): a fixed stratified 400 of
        # heldout-b-all minus heldout-b and heldout-c.
        spent = {t.instance_id for t in split("heldout-b")} | {t.instance_id for t in split("heldout-c")}
        rest = [t for t in split("heldout-b-all") if t.instance_id not in spent]
        by_repo_d: Dict[str, List[Task]] = {}
        for task in rest:
            by_repo_d.setdefault(task.repo, []).append(task)
        chosen_d = []
        for repo, items in sorted(by_repo_d.items()):
            items.sort(key=lambda t: _stable_hash("heldout-d:" + t.instance_id))
            chosen_d.extend(items[:max(2, round(400 * len(items) / len(rest)))])
        return sorted(chosen_d, key=lambda t: t.instance_id)
    if name in ("heldout-b", "heldout-b-all"):
        # Second confirmation split (declared 2026-09-26, after `heldout` was spent on
        # E016b): SWE-bench test minus Verified minus Lite. `heldout-b` is a fixed,
        # repository-stratified sample of 400 (at least two per repository).
        used = ({t.instance_id for t in load("swe_lite_test")}
                | {t.instance_id for t in load("swe_verified_test")})
        rest = [t for t in load("swe_full_test") if t.instance_id not in used]
        if name == "heldout-b-all":
            return rest
        by_repo: Dict[str, List[Task]] = {}
        for task in rest:
            by_repo.setdefault(task.repo, []).append(task)
        chosen = []
        for repo, items in sorted(by_repo.items()):
            items.sort(key=lambda t: _stable_hash("heldout-b:" + t.instance_id))
            chosen.extend(items[:max(2, round(400 * len(items) / len(rest)))])
        return sorted(chosen, key=lambda t: t.instance_id)
    raise ValueError(f"unknown split {name!r}")

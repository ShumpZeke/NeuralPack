"""E035 prototype: choose the test mate's file with lexical evidence.

The product's test mate (E016c) mirrors the top implementation file's path
(``pkg/mod.py`` -> ``tests/.../test_mod.py``), keeps only the test files with
the single best mirror score (at most three), and takes the query's best
lexical block among them. On dev-fast at 4K the chosen file is a gold test
file in 36 of 103 issues; the lexically top test file is one in 37, and the two
agree in only 15. Two ways to combine them:

* ``e035_mirror_any``: every test file that mirrors the implementation at all
  (mirror score >= 1: shares its module or package name) is a candidate; the
  query's best lexical block among all of them is the mate (44/103 files).
* ``e035_fused``: each test file scores ``0.5 * mirror + 10 / (10 + r)``, where
  ``r`` is its rank among test files in the lexical ranking; the best-scoring
  file's best lexical block is the mate (49/103 files; two tuned constants).

Both were chosen on the dev-fast issues, so dev-fast results are optimistic;
the other 197 dev issues are the fair screen. Below 2K the mate is off, so
those budgets are unchanged by construction.
"""
from __future__ import annotations

import contextlib
import importlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")


def _block_paths(con, ids: Sequence[int]) -> Dict[int, str]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return dict(con.execute(
        f"SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id WHERE b.id IN ({marks})",
        list(ids)).fetchall())


def _file_blocks(con, query: str, files: List[str], limit: int = 50) -> List[int]:
    terms = sel._lexical_terms(con, query)
    if not terms or not files:
        return []
    marks = ",".join("?" * len(files))
    try:
        rows = con.execute(
            "SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid "
            "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
            f"AND f.path IN ({marks}) ORDER BY bm25(lexical,1.0,1.0,1.0),"
            "f.path COLLATE BINARY,b.ordinal LIMIT ?",
            (" OR ".join(f'"{term}"' for term in terms), *files, limit)).fetchall()
    except Exception:
        return []
    return [row[0] for row in rows]


def _make_mate(rule: str):
    def mate(con, query: str, impl_path: str, exclude: Set[int],
             test_paths: Optional[List[Tuple[str, frozenset]]] = None,
             deep: Optional[Sequence[int]] = None) -> Optional[int]:
        paths = test_paths if test_paths is not None else sel._test_paths(con)
        impl_parts = sel._path_parts(impl_path)
        mirror = {path: sel._mate_score(impl_path, path, parts, impl_parts) for path, parts in paths}
        if deep is None:
            deep = sel._lexical_channel(con, query, sel.TEST_MATE_DEPTH)
        where = _block_paths(con, deep)
        test_blocks = [b for b in deep if where.get(b) in mirror]
        if rule == "any":
            files = sorted(p for p, s in mirror.items() if s >= 1.0)
            if not files:
                return None
            wanted = set(files)
            ranked = [b for b in test_blocks if where[b] in wanted]
            if not ranked:
                ranked = _file_blocks(con, query, files)
            return next((b for b in ranked if b not in exclude), None)
        # fused: mirror strength plus lexical file rank among test files
        file_rank: Dict[str, int] = {}
        for b in test_blocks:
            file_rank.setdefault(where[b], len(file_rank))
        def score(path: str) -> float:
            r = file_rank.get(path)
            return 0.5 * mirror[path] + (10.0 / (10.0 + r) if r is not None else 0.0)
        candidates = [p for p in mirror if mirror[p] >= 1.0 or p in file_rank]
        if not candidates:
            return None
        best = min(candidates, key=lambda p: (-score(p), p))
        ranked = [b for b in test_blocks if where[b] == best] or _file_blocks(con, query, [best])
        return next((b for b in ranked if b not in exclude), None)
    return mate


@contextlib.contextmanager
def _patched(rule: str):
    original = sel._test_mate
    sel._test_mate = _make_mate(rule)
    try:
        yield
    finally:
        sel._test_mate = original


def make(name: str, rule: str) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with _patched(rule), PackSelector(str(pack), enable_cache=False) as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e035_mirror_any", "any")
make("e035_fused", "fused")

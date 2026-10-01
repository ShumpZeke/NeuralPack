"""E005 prototype: rank coarse units, emit fine units.

Observation (dev-fast): gold edits sit in large blocks (median 875 tokens), so
at 1-2K budgets one gold class chunk can consume the whole budget; with
method-level blocks the oracle needs 2.8x fewer tokens (median 344 vs 973),
but *ranking* method-level blocks directly lost recall at >=4K. Inside a large
coarse block that contains a gold hunk, the gold method is the best lexical
match among its sibling methods 64% of the time, and top-2 82%.

Hypothesis: rank with coarse blocks (current product, definition channel on),
but emit a large coarse block as only its best-matching K method-level
children in source order (optionally with a one-line reference to elided
siblings). More distinct coarse candidates then fit a small budget.

Prototype uses two packs of the same snapshot: the default pack for ranking
and the ``python_members`` pack for children. A product version would store
parent links in one artifact.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from npk.pack.format import open_pack
from npk.pack.select import PackSelector, _lexical_terms

from .. import packs as packs_mod
from ..arms import Arm, ArmResult, register
from ..data import Task

MEMBERS = {"python_members": True}


def _children(fine_con, path: str, lo: int, hi: int):
    return fine_con.execute(
        "SELECT b.id, b.start_line, b.end_line, b.kind, b.name, length(b.text) FROM blocks b "
        "JOIN files f ON f.id=b.file_id WHERE f.path=? AND b.start_line>=? AND b.end_line<=? "
        "ORDER BY b.start_line", (path, lo, hi)).fetchall()


def _child_scores(fine_con, query: str, ids: Sequence[int]) -> Dict[int, float]:
    terms = _lexical_terms(fine_con, query)
    if not terms or not ids:
        return {}
    match = " OR ".join(f'"{t}"' for t in terms)
    marks = ",".join(str(int(i)) for i in ids)
    return {r[0]: -r[1] for r in fine_con.execute(
        f"SELECT rowid, bm25(lexical,1.0,1.0,1.0) FROM lexical WHERE lexical MATCH ? AND rowid IN ({marks})",
        (match,))}


def emission_units(task: Task, coarse_pack: Path, fine_pack: Path, *, threshold: int, keep: int,
                   references: bool, limit: int = 60) -> List[Tuple[List[Tuple[str, int, int]], int]]:
    """Ranked units: (spans that carry text, chars including any reference line)."""
    with PackSelector(str(coarse_pack), enable_cache=False, candidate_limit=limit) as selector:
        ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
    units = []
    with open_pack(fine_pack) as fine:
        for ev in ranked:
            lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
            if len(ev.text) // 4 <= threshold:
                units.append(([(ev.path, lo, hi)], len(ev.text)))
                continue
            kids = _children(fine, ev.path, lo, hi)
            if len(kids) <= 1:
                units.append(([(ev.path, lo, hi)], len(ev.text)))
                continue
            scores = _child_scores(fine, task.query, [k[0] for k in kids])
            best = sorted(kids, key=lambda k: (-scores.get(k[0], float("-inf")), k[1]))[:keep]
            chosen = sorted(best, key=lambda k: k[1])
            chars = sum(k[5] for k in chosen) + 2 * (len(chosen) - 1)
            if references:
                elided = [k for k in kids if k not in chosen]
                note = "# elided: " + "; ".join(f"{k[4] or k[3]} L{k[1]}-{k[2]}" for k in elided)
                chars += len(note) + 1
            units.append(([(ev.path, k[1], k[2]) for k in chosen], chars))
    return units


def make(name: str, *, threshold: int = 400, keep: int = 2, references: bool = False) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        fine_pack = packs_mod.pack_path(task, MEMBERS)
        packs_mod.ensure_pack(task, MEMBERS)
        started = time.perf_counter()
        units = emission_units(task, pack, fine_pack, threshold=threshold, keep=keep, references=references)
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans: List[Tuple[str, int, int]] = []
            used, n = 0, 0
            for unit_spans, chars in units:
                total = used + chars + (2 if n else 0)
                if max(1, total // 4) > budget:
                    continue
                used, n = total, n + 1
                spans.extend(unit_spans)
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, elapsed,
                                    "selected" if n else "fallback_required", n)
        return out

    def ranker(pack: Path, task: Task):
        units = emission_units(task, pack, packs_mod.pack_path(task, MEMBERS),
                               threshold=threshold, keep=keep, references=references, limit=1000)
        ranking = []
        for unit_spans, chars in units:
            # Charge the whole unit to its first span; the rest are free riders.
            for i, (p, lo, hi) in enumerate(unit_spans):
                ranking.append((p, lo, hi, max(1, chars // 4) if i == 0 else 0))
        return ranking

    # No tokens-to-find ranker: scoring children for 1,000 candidates per task
    # costs minutes; budgeted selections are what this prototype must decide.
    return register(Arm(name, runner=runner))


make("e005_cf_k1", keep=1)
make("e005_cf_k2", keep=2)
make("e005_cf_k3", keep=3)
make("e005_cf_k2_refs", keep=2, references=True)
make("e005_cf_k2_t800", keep=2, threshold=800)


# ---------------------------------------------------------------------------
# Single-pack variant: children are line slices of the coarse block, found by
# parsing the block text; child relevance is BM25-style term overlap using
# document frequencies from the coarse index. This is what a product version
# can do without a second index.
# ---------------------------------------------------------------------------
import ast as _ast
import math as _math

from npk.pack.search import analyzed_terms as _analyzed_terms


def _python_children(text: str, first_line: int):
    """Top-level members of a class chunk as (start, end, name) in file lines."""
    try:
        tree = _ast.parse(text)
    except SyntaxError:
        # Chunked classes start mid-body; parse the dedented text instead.
        import textwrap
        try:
            tree = _ast.parse(textwrap.dedent(text))
        except SyntaxError:
            return []
    nodes = []
    for node in tree.body:
        body = node.body if isinstance(node, _ast.ClassDef) else [node]
        for member in body:
            if isinstance(member, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                start = min([member.lineno] + [d.lineno for d in member.decorator_list])
                nodes.append((first_line + start - 1, first_line + member.end_lineno - 1, member.name))
    return nodes


def single_pack_units(task: Task, pack: Path, *, threshold: int, keep: int, limit: int = 60):
    with PackSelector(str(pack), enable_cache=False, candidate_limit=limit) as selector:
        ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
    import sqlite3 as _sqlite3
    # The product reader sets query_only, which forbids temp vocab tables; a
    # plain read-only URI connection is enough for document frequencies.
    con = _sqlite3.connect(Path(pack).absolute().as_uri() + "?mode=ro", uri=True)
    try:
        terms = _lexical_terms(con, task.query)
        total = con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.npk_vocab USING fts5vocab(main, lexical, 'row')")
        marks = ",".join("?" * len(terms)) or "''"
        df = dict(con.execute(f"SELECT term, doc FROM temp.npk_vocab WHERE term IN ({marks})", terms))
    finally:
        con.close()
    idf = {t: max(0.0, _math.log((total - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))) for t in terms}
    units = []
    for ev in ranked:
        lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
        kids = (_python_children(ev.text, lo)
                if ev.path.endswith(".py") and len(ev.text) // 4 > threshold else [])
        if len(kids) <= 1:
            units.append(([(ev.path, lo, hi)], len(ev.text)))
            continue
        lines = ev.text.split("\n")
        def score(kid):
            body = "\n".join(lines[kid[0] - lo:kid[1] - lo + 1])
            counts = {}
            for term in _analyzed_terms(body):
                counts[term] = counts.get(term, 0) + 1
            n = sum(counts.values()) or 1
            return sum(idf[t] * counts[t] * 2.2 / (counts[t] + 1.2 * (0.25 + 0.75 * n / 200))
                       for t in terms if t in counts)
        best = sorted(kids, key=lambda k: (-score(k), k[0]))[:keep]
        chosen = sorted(best)
        chars = sum(len("\n".join(lines[k[0] - lo:k[1] - lo + 1])) for k in chosen) + 2 * (len(chosen) - 1)
        units.append(([(ev.path, k[0], k[1]) for k in chosen], chars))
    return units


def make_single(name: str, *, threshold: int = 400, keep: int = 2) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        units = single_pack_units(task, pack, threshold=threshold, keep=keep)
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for unit_spans, chars in units:
                total = used + chars + (2 if n else 0)
                if max(1, total // 4) > budget:
                    continue
                used, n = total, n + 1
                spans.extend(unit_spans)
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, elapsed,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make_single("e005s_k1", keep=1)
make_single("e005s_k2", keep=2)
make_single("e005s_k3", keep=3)



# ---------------------------------------------------------------------------
# E005c fit-or-trim: identical ranking and greedy fill, except that a block
# which no longer fits is replaced by its best-matching children that do fit
# (instead of being skipped). Whole blocks are never trimmed when they fit.
# ---------------------------------------------------------------------------
def make_fit_or_trim(name: str, *, min_block: int = 200, reference: bool = False,
                     max_rank: int = 10**9) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        fine_pack = packs_mod.pack_path(task, MEMBERS)
        packs_mod.ensure_pack(task, MEMBERS)
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        children_cache: Dict[int, list] = {}
        out = {}
        with open_pack(fine_pack) as fine:
            def children(ev, lo, hi):
                if ev.block_id not in children_cache:
                    kids = _children(fine, ev.path, lo, hi)
                    scores = _child_scores(fine, task.query, [k[0] for k in kids])
                    children_cache[ev.block_id] = sorted(
                        kids, key=lambda k: (-scores.get(k[0], float("-inf")), k[1]))
                return children_cache[ev.block_id]
            for budget in budgets:
                spans, used, n = [], 0, 0
                for rank, ev in enumerate(ranked):
                    lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
                    total = used + len(ev.text) + (2 if n else 0)
                    if max(1, total // 4) <= budget:
                        used, n = total, n + 1
                        spans.append((ev.path, lo, hi))
                        continue
                    if len(ev.text) // 4 < min_block or rank >= max_rank:
                        continue
                    kids = children(ev, lo, hi)
                    if len(kids) <= 1:
                        continue
                    for kid in kids:  # best first; add each child that still fits
                        extra = kid[5] + (2 if n else 0)
                        if reference:
                            extra += 40  # a one-line pointer to the elided remainder
                        if max(1, (used + extra) // 4) <= budget:
                            used, n = used + extra, n + 1
                            spans.append((ev.path, kid[1], kid[2]))
                out[budget] = ArmResult(spans, max(1, used // 4) if n else 0,
                                        (time.perf_counter() - started) * 1000,
                                        "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make_fit_or_trim("e005c_fit_or_trim")
make_fit_or_trim("e005c_fit_or_trim_ref", reference=True)

make_fit_or_trim("e005c_fot_r1", max_rank=1)
make_fit_or_trim("e005c_fot_r3", max_rank=3)
make_fit_or_trim("e005c_fot_r5", max_rank=5)


# Single-pack fit-or-trim: children come from parsing the block itself (what
# a product version can do without the members pack), scored like e005s.
def make_fit_or_trim_single(name: str, *, min_block: int = 200, max_rank: int = 10**9) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        import sqlite3 as _sqlite3
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        con = _sqlite3.connect(Path(pack).absolute().as_uri() + "?mode=ro", uri=True)
        try:
            terms = _lexical_terms(con, task.query)
            total = con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.v USING fts5vocab(main, lexical, 'row')")
            marks = ",".join("?" * len(terms)) or "''"
            df = dict(con.execute(f"SELECT term, doc FROM temp.v WHERE term IN ({marks})", terms))
        finally:
            con.close()
        idf = {t: max(0.0, _math.log((total - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))) for t in terms}
        cache: Dict[int, list] = {}

        def children(ev, lo):
            if ev.block_id not in cache:
                kids = _python_children(ev.text, lo) if ev.path.endswith(".py") else []
                lines = ev.text.split("\n")
                scored = []
                for k in kids:
                    body = "\n".join(lines[k[0] - lo:k[1] - lo + 1])
                    counts: Dict[str, int] = {}
                    for term in _analyzed_terms(body):
                        counts[term] = counts.get(term, 0) + 1
                    n_terms = sum(counts.values()) or 1
                    score = sum(idf[t] * counts[t] * 2.2 / (counts[t] + 1.2 * (0.25 + 0.75 * n_terms / 200))
                                for t in terms if t in counts)
                    scored.append((score, k, len(body)))
                cache[ev.block_id] = sorted(scored, key=lambda x: (-x[0], x[1][0]))
            return cache[ev.block_id]

        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for rank, ev in enumerate(ranked):
                lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
                total_chars = used + len(ev.text) + (2 if n else 0)
                if max(1, total_chars // 4) <= budget:
                    used, n = total_chars, n + 1
                    spans.append((ev.path, lo, hi))
                    continue
                if len(ev.text) // 4 < min_block or rank >= max_rank:
                    continue
                kids = children(ev, lo)
                if len(kids) <= 1:
                    continue
                for _score, kid, chars in kids:
                    extra = chars + (2 if n else 0)
                    if max(1, (used + extra) // 4) <= budget:
                        used, n = used + extra, n + 1
                        spans.append((ev.path, kid[0], kid[1]))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0,
                                    (time.perf_counter() - started) * 1000,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make_fit_or_trim_single("e005d_fots")
make_fit_or_trim_single("e005d_fots_r3", max_rank=3)


# ---------------------------------------------------------------------------
# E005e: product-grade single-pack fit-or-trim. Member spans are computed
# exactly as the python_members splitter does, from the whole file rebuilt
# out of its stored blocks (blocks carry exact line spans; gaps are blank
# lines), so chunked classes are handled. Only the top-ranked block is ever
# trimmed, and only when it cannot fit.
# ---------------------------------------------------------------------------
from npk.pack.compile import _class_member_spans as _member_spans


def file_member_spans(con, path: str) -> List[Tuple[int, int, str, str]]:
    rows = con.execute("SELECT b.start_line, b.text FROM blocks b JOIN files f ON f.id=b.file_id "
                       "WHERE f.path=? ORDER BY b.start_line", (path,)).fetchall()
    lines: List[str] = []
    for start, text in rows:
        body = text.split("\n")
        while len(lines) < start - 1:
            lines.append("")
        lines[start - 1:start - 1 + len(body)] = body
    try:
        tree = _ast.parse("\n".join(lines))
    except (SyntaxError, ValueError):
        return []
    spans: List[Tuple[int, int, str, str]] = []
    for node in tree.body:
        if isinstance(node, _ast.ClassDef):
            spans.extend(_member_spans(node, node.name))
    return spans


def _local_scores(texts: Dict[int, str], terms: Sequence[str], idf: Dict[str, float]) -> Dict[int, float]:
    out = {}
    for key, body in texts.items():
        counts: Dict[str, int] = {}
        for term in _analyzed_terms(body):
            counts[term] = counts.get(term, 0) + 1
        n = sum(counts.values()) or 1
        out[key] = sum(idf.get(t, 0.0) * counts[t] * 2.2 / (counts[t] + 1.2 * (0.25 + 0.75 * n / 200))
                       for t in terms if t in counts)
    return out


def make_fot_exact(name: str, *, idf_mode: str) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        import sqlite3 as _sqlite3
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence
        out = {}
        trimmed = None
        for budget in budgets:
            spans, used, n = [], 0, 0
            for rank, ev in enumerate(ranked):
                lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
                total_chars = used + len(ev.text) + (2 if n else 0)
                if max(1, total_chars // 4) <= budget:
                    used, n = total_chars, n + 1
                    spans.append((ev.path, lo, hi))
                    continue
                if rank != 0 or not ev.path.endswith(".py") or len(ev.text) // 4 < 200:
                    continue
                if trimmed is None:
                    con = _sqlite3.connect(Path(pack).absolute().as_uri() + "?mode=ro", uri=True)
                    try:
                        kids = [(s, e, k, nm) for s, e, k, nm in file_member_spans(con, ev.path)
                                if s >= lo and e <= hi]
                        # Clip spans that cross the chunk edges, keeping any line inside it.
                        if not kids:
                            kids = [(max(s, lo), min(e, hi), k, nm) for s, e, k, nm in file_member_spans(con, ev.path)
                                    if s <= hi and e >= lo]
                        lines = ev.text.split("\n")
                        texts = {i: "\n".join(lines[s - lo:e - lo + 1]) for i, (s, e, _k, _n) in enumerate(kids)}
                        terms = _lexical_terms(con, task.query)
                        if idf_mode == "global":
                            total = con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
                            con.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, lexical, 'row')")
                            marks = ",".join("?" * len(terms)) or "''"
                            df = dict(con.execute(f"SELECT term, doc FROM temp.v WHERE term IN ({marks})", terms))
                        else:  # file-local: rarity among this file's blocks
                            file_texts = [r[0] for r in con.execute(
                                "SELECT b.text FROM blocks b JOIN files f ON f.id=b.file_id WHERE f.path=?", (ev.path,))]
                            total = len(file_texts)
                            sets = [set(_analyzed_terms(x)) for x in file_texts]
                            df = {t: sum(t in s for s in sets) for t in terms}
                    finally:
                        con.close()
                    idf = {t: max(0.0, _math.log((total - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))) + 0.01
                           for t in terms}
                    scores = _local_scores(texts, terms, idf)
                    trimmed = [(kids[i], len(texts[i])) for i in sorted(texts, key=lambda i: (-scores[i], i))]
                for (s, e, _k, _nm), chars in trimmed:
                    extra = chars + (2 if n else 0)
                    if max(1, (used + extra) // 4) <= budget:
                        used, n = used + extra, n + 1
                        spans.append((ev.path, s, e))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0,
                                    (time.perf_counter() - started) * 1000,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make_fot_exact("e005e_exact_global", idf_mode="global")
make_fot_exact("e005e_exact_local", idf_mode="local")

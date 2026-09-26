"""E002 prototype: code-entity-aware query planning (runtime only, same packs).

Hypothesis: long natural-language issue queries name the code they concern
(``Signal.send_robust()``, ``django.core.exceptions.ValidationError``,
``StaticFilesHandlerMixin``). Flat OR-BM25 over ~100 prose terms drowns those
rare, precise tokens. Treating code-like tokens as entities -- up-weighting them
in BM25 and resolving them against the compiled definition index -- should rank
the defining source higher at no compile-time cost.

Parity: with every feature disabled the selector reproduces ``npk_default``.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from npk.pack.format import load_blocks, open_pack
from npk.pack.search import analyzed_terms
from npk.pack.select import FUNCTION_WORDS, RRF_K, _lexical_terms, _relation_channel

from ..arms import Arm, ArmResult, register
from ..data import Task

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
DOTTED = re.compile(rf"(?<![\w.]){IDENT}(?:\.{IDENT})+(?![\w(])|(?<![\w.]){IDENT}(?:\.{IDENT})+(?=\()")
CALL = re.compile(rf"(?<![\w.])({IDENT})\(")
BACKTICK = re.compile(r"`([^`\n]{1,200})`")
WORD = re.compile(IDENT)
PATHLIKE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|pyi|js|ts|rst|md|txt|cfg|toml|ini|json|yaml|yml))\b")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')


def code_like(token: str) -> bool:
    """snake_case, CamelCase/camelCase humps, or letters mixed with digits."""
    core = token.strip("_")
    if not core or len(token) < 3:
        return False
    if "_" in core:
        return True
    if re.search(r"[a-z][A-Z]", core) or re.search(r"[A-Z]{2,}[a-z]", core):
        return True
    if re.search(r"[A-Za-z]", core) and re.search(r"\d", core):
        return True
    return False


def extract_entities(query: str, *, strict: bool = False, qualified: bool = False) -> Dict[str, List[str]]:
    """Identifiers the issue names explicitly, in first-mention order.

    ``strict`` keeps a dotted component only when it is itself code-like or
    is the final component (``models.Field`` keeps ``Field``, drops
    ``models``). ``qualified`` also keeps whole dotted spellings.
    """
    names: List[str] = []
    for match in DOTTED.finditer(query):
        parts = match.group(0).split(".")
        # Skip abbreviations/versions ("e.g", "i.e", "v2.0") via identifier rules.
        if all(len(p) <= 2 for p in parts):
            continue
        if qualified:
            names.append(match.group(0))
        if strict:
            names.extend(p for i, p in enumerate(parts)
                         if len(p) >= 3 and (code_like(p) or i == len(parts) - 1)
                         and p.lower() not in FUNCTION_WORDS and p != "self")
            continue
        names.extend(p for p in parts if len(p) >= 3 and p.lower() not in FUNCTION_WORDS)
    names.extend(m.group(1) for m in CALL.finditer(query) if len(m.group(1)) >= 3)
    for match in BACKTICK.finditer(query):
        names.extend(w for w in WORD.findall(match.group(1)) if len(w) >= 3)
    names.extend(w for w in WORD.findall(query) if code_like(w))
    seen: Set[str] = set()
    ordered = [n for n in names if not (n in seen or seen.add(n))]
    paths = list(dict.fromkeys(m.group(1) for m in PATHLIKE.finditer(query)))
    frames = [(m.group(1), m.group(3)) for m in FRAME.finditer(query)]
    return {"names": ordered, "paths": paths, "frames": frames}


def _match_expression(weighted: Dict[str, int]) -> str:
    return " OR ".join(" OR ".join([f'"{t}"'] * w) for t, w in weighted.items())


def weighted_lexical_scored(con, query: str, entities: Sequence[str], limit: int,
                            weight: int) -> List[Tuple[int, int, float]]:
    """(block_id, file_id, score) with score = -bm25 (higher is better)."""
    terms = _lexical_terms(con, query)
    if not terms:
        return []
    boosted = {t.lower() for t in entities}
    weighted = {t: (weight if t in boosted else 1) for t in terms}
    for name in boosted:
        # Whole entity spellings are indexed tokens even when the analyzer's
        # stopword rules would drop them from the prose term list.
        weighted.setdefault(name, weight)
    rows = con.execute(
        "SELECT lexical.rowid, b.file_id, bm25(lexical,1.0,1.0,1.0) FROM lexical "
        "JOIN blocks b ON b.id=lexical.rowid "
        "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
        "ORDER BY bm25(lexical,1.0,1.0,1.0), f.path COLLATE BINARY, b.ordinal LIMIT ?",
        (_match_expression(weighted), limit)).fetchall()
    return [(r[0], r[1], -r[2]) for r in rows]


def weighted_lexical(con, query: str, entities: Sequence[str], limit: int, weight: int) -> List[int]:
    return [b for b, _f, _s in weighted_lexical_scored(con, query, entities, limit, weight)]


def file_aggregated(scored: Sequence[Tuple[int, int, float]], alpha: float, k: int) -> List[int]:
    """Re-rank blocks by own score plus alpha * (sum of the file's top-k scores).

    Several matching blocks in one file are corroborating evidence that the
    file is on topic; a lone strong block in an unrelated file is not.
    """
    per_file: Dict[int, List[float]] = {}
    for _b, f, s in scored:
        per_file.setdefault(f, []).append(s)
    file_score = {f: sum(sorted(v, reverse=True)[:k]) for f, v in per_file.items()}
    keyed = [(-(s + alpha * file_score[f]), i, b) for i, (b, f, s) in enumerate(scored)]
    return [b for _k, _i, b in sorted(keyed)]


def definition_channel(con, names: Sequence[str], limit: int, max_defs: int,
                       lexical_rank: Dict[int, int]) -> List[int]:
    """Blocks defining a named entity; ambiguous names (> max_defs) are ignored."""
    if not names:
        return []
    marks = ",".join("?" * len(names))
    rows = con.execute(
        f"SELECT name, block_id FROM symbols WHERE is_def=1 AND name IN ({marks})", tuple(names)).fetchall()
    by_name: Dict[str, List[int]] = {}
    for name, block_id in rows:
        by_name.setdefault(name, []).append(block_id)
    score: Dict[int, float] = {}
    for name, blocks in by_name.items():
        if len(blocks) > max_defs:
            continue
        # Specific names (few definitions) are stronger evidence.
        for block_id in set(blocks):
            score[block_id] = score.get(block_id, 0.0) + 1.0 / math.log2(1 + len(set(blocks)))
    fallback = len(lexical_rank) + 1
    ordered = sorted(score, key=lambda b: (-score[b], lexical_rank.get(b, fallback), b))
    return ordered[:limit]


def path_channel(con, paths: Sequence[str], frames: Sequence[Tuple[str, str]], limit: int,
                 lexical_rank: Dict[int, int]) -> List[int]:
    """Blocks of files the issue names by path; traceback frames add a function."""
    wanted = [p.lstrip("./") for p in paths] + [f[0].replace("\\", "/") for f in frames]
    if not wanted:
        return []
    files = con.execute("SELECT id, path FROM files").fetchall()
    matched: Dict[int, int] = {}
    for order, raw in enumerate(wanted):
        parts = [p for p in raw.split("/") if p not in ("", ".", "..")]
        # Longest indexed suffix match, e.g. site-packages/django/x.py -> django/x.py
        for n in range(len(parts), 0, -1):
            suffix = "/".join(parts[-n:])
            hits = [fid for fid, path in files if path == suffix or path.endswith("/" + suffix)]
            if hits and (n >= 2 or len(hits) == 1):
                for fid in hits:
                    matched.setdefault(fid, order)
                break
    if not matched:
        return []
    frame_funcs = {f[1] for f in frames}
    marks = ",".join("?" * len(matched))
    rows = con.execute(f"SELECT id, file_id, name FROM blocks WHERE file_id IN ({marks})",
                       tuple(matched)).fetchall()
    fallback = len(lexical_rank) + 1
    def key(row):
        func_hit = 0 if (row[2] and row[2].split(".")[-1] in frame_funcs) else 1
        return (func_hit, lexical_rank.get(row[0], fallback), matched[row[1]], row[0])
    return [r[0] for r in sorted(rows, key=key) if r[0] in lexical_rank or r[2] in frame_funcs][:limit]


def fill(con, ordered_ids: Sequence[int], budget: int) -> Tuple[List[Tuple[str, int, int]], int, int]:
    """Product-identical greedy fill with chars/4 accounting including separators."""
    blocks = {b.id: b for b in load_blocks(con, list(ordered_ids))}
    spans, used_chars, n = [], 0, 0
    for block_id in ordered_ids:
        blk = blocks.get(block_id)
        if blk is None:
            continue
        chars = used_chars + len(blk.text) + (2 if n else 0)
        if max(1, chars // 4) > budget:
            continue
        used_chars = chars
        n += 1
        spans.append((blk.path, blk.start_line, blk.end_line))
    return spans, (max(1, used_chars // 4) if n else 0), n


ROLE_PATTERNS = (
    re.compile(r"(^|/)(tests?|testing)(/|$)|(^|/)test_[^/]*$|_tests?\.py$|(^|/)conftest\.py$"),
    re.compile(r"(^|/)(docs?|doc_src)(/|$)|\.(rst|md|txt)$"),
    re.compile(r"(^|/)(examples?|galleries|tutorials?|benchmarks?|asv_bench)(/|$)"),
)


def role_adjusted(con, scored: Sequence[Tuple[int, int, float]], factor: float) -> List[int]:
    """Scale BM25 of test/doc/example files by ``factor`` (H6: implementation first)."""
    files = dict(con.execute("SELECT id, path FROM files"))
    def adjusted(item):
        _b, f, s = item
        return s * factor if any(p.search(files[f]) for p in ROLE_PATTERNS) else s
    keyed = [(-adjusted(item), i, item[0]) for i, item in enumerate(scored)]
    return [b for _k, _i, b in sorted(keyed)]


def select_ranked(con, query: str, *, limit: int = 60, weight: int = 1, defs: bool = False,
                  paths: bool = False, relations: bool = True, max_defs: int = 10,
                  agg_alpha: float = 0.0, agg_k: int = 3, agg_pool: int = 200,
                  role_factor: float = 1.0, strict: bool = False, qualified: bool = False,
                  def_limit: Optional[int] = None, def_k: int = RRF_K) -> List[int]:
    ents = extract_entities(query, strict=strict, qualified=qualified)
    names = ents["names"] if weight > 1 else []
    if agg_alpha > 0 or role_factor != 1.0:
        pool = max(limit, agg_pool)
        scored = weighted_lexical_scored(con, query, names, pool, weight)
        if role_factor != 1.0:
            order = {b: i for i, b in enumerate(role_adjusted(con, scored, role_factor))}
            scored = sorted(scored, key=lambda item: order[item[0]])
        lexical = (file_aggregated(scored, agg_alpha, agg_k) if agg_alpha > 0
                   else [b for b, _f, _s in scored])
        lexical = lexical[:pool if limit >= 1000 else limit]
    else:
        lexical = weighted_lexical(con, query, names, limit, weight)
    ranks: Dict[str, List[int]] = {}
    if lexical:
        ranks["lexical"] = lexical
    lexical_rank = {b: i for i, b in enumerate(lexical)}
    if relations:
        rel = _relation_channel(con, query, limit)
        if rel:
            ranks["relation"] = rel
    if defs:
        d = definition_channel(con, ents["names"], def_limit or limit, max_defs, lexical_rank)
        if d:
            ranks["definition"] = d
    if paths:
        p = path_channel(con, ents["paths"], ents["frames"], limit, lexical_rank)
        if p:
            ranks["path"] = p
    fused: Dict[int, float] = {}
    for channel, ordered in ranks.items():
        k = def_k if channel == "definition" else RRF_K
        for rank, block_id in enumerate(ordered):
            fused[block_id] = fused.get(block_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused, key=lambda b: -fused[b])


def make_arm(name: str, compile_options: Optional[Dict] = None, **options) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out = {}
        with open_pack(pack) as con:
            for budget in budgets:
                started = time.perf_counter()
                ordered = select_ranked(con, task.query, **options)
                spans, tokens, n = fill(con, ordered, budget)
                out[budget] = ArmResult(spans, tokens, (time.perf_counter() - started) * 1000,
                                        "selected" if n else "fallback_required", n)
        return out

    def ranker(pack: Path, task: Task):
        with open_pack(pack) as con:
            ordered = select_ranked(con, task.query, **{**options, "limit": 1000})
            blocks = {b.id: b for b in load_blocks(con, ordered)}
        return [(blocks[i].path, blocks[i].start_line, blocks[i].end_line, max(1, len(blocks[i].text) // 4))
                for i in ordered if i in blocks]

    return register(Arm(name, compile_options=dict(compile_options or {}), runner=runner, ranker=ranker))


# Parity control: must equal npk_default exactly.
make_arm("e002_parity")
make_arm("e002_w3", weight=3)
make_arm("e002_defs", defs=True)
make_arm("e002_paths", paths=True)
make_arm("e002_w3_defs", weight=3, defs=True)
make_arm("e002_w3_defs_paths", weight=3, defs=True, paths=True)
# H7: file-level evidence aggregation (lexical channel re-ranked before fusion).
make_arm("e003_agg05", agg_alpha=0.5)
make_arm("e003_agg10", agg_alpha=1.0)
make_arm("e002_w2", weight=2)
make_arm("e002_w5", weight=5)
# H6: implementation-first role prior (reported separately; see gaming caveat).
make_arm("e006_role05", role_factor=0.5)
make_arm("e006_role07", role_factor=0.7)

# --- E002 refinement sweep (dev-fast only; held-out untouched) ---
for _n in (3, 5, 25):
    make_arm(f"e002_defs_max{_n}", defs=True, max_defs=_n)
make_arm("e002_defs_strict", defs=True, strict=True)
make_arm("e002_defs_qual", defs=True, qualified=True)
make_arm("e002_defs_strict_qual", defs=True, strict=True, qualified=True)
make_arm("e002_defs_members", compile_options={"python_members": True}, defs=True)
make_arm("e002_defs_role05", defs=True, role_factor=0.5)
make_arm("e002_defs_role07", defs=True, role_factor=0.7)
make_arm("e002_defs_members_role05", compile_options={"python_members": True}, defs=True, role_factor=0.5)
make_arm("e006_role05_members", compile_options={"python_members": True}, role_factor=0.5)

# --- E002c: reduce displacement of other evidence (both gold targets) ---
for _n in (3, 5, 10, 20):
    make_arm(f"e002_deflim{_n}", defs=True, def_limit=_n)
make_arm("e002_defk120", defs=True, def_k=120)
make_arm("e002_deflim5_k120", defs=True, def_limit=5, def_k=120)

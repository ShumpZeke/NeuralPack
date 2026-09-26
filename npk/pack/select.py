"""Local query-time retrieval over a compiled .npk; zero generative LLM calls.

BM25 is the default. Hybrid fusion, conflict deletion and dependency expansion
are explicit experiments. Cycle 3 corrected the old benchmark and found no
general advantage from combining these systems. See EVOLUTION_LOG.md.

PROVED UNDER ASSUMPTIONS: dependency reachability cannot expand an empty seed
set without another source of seeds. Failed retrieval requires explicit fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import collections
import copy
import math
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .format import Block, PackError, connect, load_blocks, open_pack, read_manifest, require_supported, require_encoder_match
from .search import CODE_WORDS, analyzed_terms, requested_raise_names, surface_names
from .tokenizer import LocalTokenizer

RRF_K = 60

#: Escalation ladder. Strictly local and deterministic; no step contacts a
#: remote provider, and no step invokes a generative model.
ESCALATION_STEPS = ("widen_retrieval", "expand_dependencies", "raw_fallback")


def _context_tokens(evidence: Sequence[Evidence]) -> int:
    """Same estimate as compile. Includes default context_text separators."""
    chars = sum(len(e.text) for e in evidence) + max(0, len(evidence) - 1) * 2
    return max(1, chars // 4) if evidence else 0


#: Function words carry no evidence, so they must not count toward retrieval
#: coverage. Counting them made coverage look poor for perfectly good
#: selections ("explain", "how", "works" never appear in source code).
STOPWORDS = frozenset("""
a an the and or but if then else for while of in on at to from by with without
what which who whom whose when where why how is are was were be been being do
does did done have has had having can could should would may might must will
shall this that these those it its as not no yes into about over under again
value values return returns get set use used using exactly exact configured
""".split())
FUNCTION_WORDS = STOPWORDS - CODE_WORDS


def _query_terms(query: str) -> List[str]:
    """Tokenize a query, additionally splitting snake_case/dotted identifiers."""
    raw = re.findall(r"\w+", query.lower())
    terms: List[str] = []
    for tok in raw:
        terms.append(tok)
        if "_" in tok:
            terms.extend(p for p in tok.split("_") if len(p) > 2)
    for tok in raw:
        parts = re.findall(r"[a-z]+|[A-Z][a-z]*|\d+", tok)
        if len(parts) > 1:
            terms.extend(p.lower() for p in parts if len(p) > 2)
    return list(dict.fromkeys(terms))


def _content_terms(query: str) -> List[str]:
    """Evidence-bearing query terms, used for coverage scoring and lexical matching."""
    return [t for t in _query_terms(query) if t not in FUNCTION_WORDS and len(t) > 2]


def _identifier_candidates(query: str) -> List[str]:
    """Identifiers a user is likely naming: CamelCase, snake_case, dotted."""
    out: List[str] = []
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", query):
        out.append(tok)
        if "." in tok:
            out.extend(p for p in tok.split(".") if len(p) > 2)
    return list(dict.fromkeys(out))


@dataclass
class Evidence:
    """One selected block, with the provenance a caller needs to cite it."""

    block_id: int
    path: str
    span: str
    kind: str
    name: Optional[str]
    tokens: int
    text: str
    score: float
    channels: List[str] = field(default_factory=list)

    def as_dict(self, include_text: bool = True) -> Dict[str, Any]:
        d = {
            "block_id": self.block_id, "path": self.path, "span": self.span,
            "kind": self.kind, "name": self.name, "tokens": self.tokens,
            "score": round(self.score, 6), "channels": self.channels,
        }
        if include_text:
            d["text"] = self.text
        return d


@dataclass
class Selection:
    """Result of a query. Carries its own uncertainty and fallback reasoning."""

    query: str
    evidence: List[Evidence]
    total_tokens: int
    budget_tokens: int
    available_tokens: Optional[int]
    channels_used: List[str]
    escalations: List[str]
    risk_band: str
    seed_failed: bool
    latency_ms: float
    used_generative_llm: bool = False   # invariant: always False on this path
    notes: List[str] = field(default_factory=list)
    #: Contradicting variants that were dropped, and why. Never silent.
    conflicts_resolved: List[Dict[str, Any]] = field(default_factory=list)
    tokenizer: Optional[Dict[str, Any]] = None
    available_tokens_estimate: Optional[int] = None

    def context_text(self, separator: str = "\n\n", *, order: str = "relevance",
                     tokenizer: Optional[LocalTokenizer] = None) -> str:
        """Render evidence; canonical order needs its own exact budget check.

        total_tokens describes relevance order with default separators.
        Reordering can change tokenizer merges. For an exact selection, supply
        the matching local tokenizer when requesting canonical emission.
        """
        if order == "relevance":
            return separator.join(e.text for e in self.evidence)
        if order == "canonical":
            ordered = sorted(self.evidence, key=_source_order)
            text = separator.join(e.text for e in ordered)
            if self.tokenizer is not None:
                if (not isinstance(tokenizer, LocalTokenizer)
                        or tokenizer.sha256 != self.tokenizer.get("asset_sha256")):
                    raise ValueError("canonical exact context requires the matching local tokenizer")
                count = tokenizer.count(text)
            else:
                count = max(1, len(text) // 4) if text else 0
            if count > self.budget_tokens:
                raise PackError("canonical context exceeds token budget; use relevance order or a lower selection budget")
            return text
        raise ValueError(f"unknown order {order!r}; expected 'relevance' or 'canonical'")

    def as_dict(self, include_text: bool = True) -> Dict[str, Any]:
        return {
            "query": self.query,
            "evidence": [e.as_dict(include_text) for e in self.evidence],
            "total_tokens": self.total_tokens,
            "budget_tokens": self.budget_tokens,
            "available_tokens": self.available_tokens,
            "available_tokens_estimate": self.available_tokens_estimate,
            "reduction_pct": (
                round(100.0 * (self.available_tokens - self.total_tokens) / self.available_tokens, 2)
                if self.available_tokens and self.evidence and not self.seed_failed else None
            ),
            "status": "fallback_required" if self.seed_failed or not self.evidence else "selected",
            "token_accounting": ("exact for supplied tokenizer JSON including default separators; excludes query and caller wrappers"
                                 if self.tokenizer else "estimated chars/4 including default separators; excludes query and caller wrappers"),
            "tokenizer": self.tokenizer,
            "sufficiency": "unverified" if self.evidence else "no_evidence",
            "channels_used": self.channels_used,
            "escalations": self.escalations,
            "risk_band": self.risk_band,
            "seed_failed": self.seed_failed,
            "used_generative_llm": self.used_generative_llm,
            "latency_ms": round(self.latency_ms, 2),
            "notes": self.notes,
            "conflicts_resolved": self.conflicts_resolved,
        }


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def _source_order(evidence: Evidence) -> Tuple[str, int, int]:
    start, end = evidence.span.rsplit(":", 1)[1].split("-")
    return evidence.path, int(start), int(end)


def _copy_selection(selection: Selection) -> Selection:
    """Copy the public mutable result without traversing immutable source text."""
    result = copy.copy(selection)
    result.evidence = []
    for original in selection.evidence:
        evidence = copy.copy(original)
        evidence.channels = list(original.channels)
        result.evidence.append(evidence)
    result.channels_used = list(selection.channels_used)
    result.escalations = list(selection.escalations)
    result.notes = list(selection.notes)
    result.conflicts_resolved = copy.deepcopy(selection.conflicts_resolved)
    result.tokenizer = copy.deepcopy(selection.tokenizer)
    return result


def _symbol_channel(con: sqlite3.Connection, query: str, limit: int) -> List[int]:
    idents = _identifier_candidates(query)
    if not idents:
        return []
    marks = ",".join("?" * len(idents))
    rows = con.execute(
        f"SELECT s.block_id, SUM(s.is_def) d, COUNT(*) c FROM symbols s "
        f"JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id "
        f"WHERE s.name IN ({marks}) GROUP BY s.block_id "
        f"ORDER BY d DESC,c DESC,f.path COLLATE BINARY,b.ordinal LIMIT ?",
        (*idents, limit),
    ).fetchall()
    return [r["block_id"] for r in rows]


def _explicit_literals(query: str) -> List[str]:
    """Atomic inline code references override prose stopwords/length filters.

    Dotted references retain both the full spelling and its components. This
    narrow rule does not interpret code fences or rewrite the caller's query.
    """
    literals = re.findall(r"(?<!`)`(\w+(?:\.\w+)*)`(?!`)", query)
    return list(dict.fromkeys(part.lower() for literal in literals
                             for part in (literal, *literal.split("."))))


def _lexical_terms(_con: sqlite3.Connection, query: str) -> List[str]:
    """Analyze query words exactly as format-v8 search fields are analyzed.

    Whole identifiers and their components coexist in the index, so no
    request-time vocabulary probes or corpus-dependent rewriting are needed.
    Backticked literals survive function-word and short-token filtering.
    """
    explicit = set(_explicit_literals(query))
    terms = [
        term for term in analyzed_terms(query)
        if (term not in FUNCTION_WORDS and len(term) > 1) or term in explicit
    ]
    terms.extend(term for term in explicit if term not in terms)
    return list(dict.fromkeys(terms))


def _whole_lexical_terms(query: str) -> List[str]:
    """Whole query spellings before identifier-component expansion."""
    explicit = set(_explicit_literals(query))
    terms = [
        term.lower() for term in re.findall(r"\w+", query, re.UNICODE)
        if (term.lower() not in FUNCTION_WORDS and len(term) > 1)
        or term.lower() in explicit
    ]
    terms.extend(term for term in explicit if term not in terms)
    return list(dict.fromkeys(terms))


def _rank_lexical_terms(
    con: sqlite3.Connection, terms: Sequence[str], limit: int
) -> List[int]:
    if not terms:
        return []
    match = " OR ".join(f'"{term}"' for term in terms)
    rows = con.execute(
        "SELECT lexical.rowid AS block_id FROM lexical JOIN blocks b ON b.id=lexical.rowid "
        "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
        "ORDER BY bm25(lexical,1.0,1.0,1.0),"
        "f.path COLLATE BINARY,b.ordinal LIMIT ?",
        (match, limit),
    ).fetchall()
    return [row["block_id"] for row in rows]


def _lexical_channel(con: sqlite3.Connection, query: str, limit: int) -> List[int]:
    try:
        terms = _lexical_terms(con, query)
        if not terms:
            return []
        expanded = _rank_lexical_terms(con, terms, limit)
        whole_terms = _whole_lexical_terms(query)
        if whole_terms == terms or len(whole_terms) != 1:
            return expanded
        whole = _rank_lexical_terms(con, whole_terms, limit)
        # A one-symbol lookup with an exact corpus spelling is unambiguous.
        # Admitting component-only matches here turns ``item1`` into a match for
        # every ``itemN`` and can consume the context budget with distractors.
        # Expansion remains the fallback for spelling aliases such as a camel
        # query against a snake_case definition when no exact spelling exists.
        return whole or expanded
    except sqlite3.OperationalError:
        return []


def _relation_channel(con: sqlite3.Connection, query: str, limit: int) -> List[int]:
    """Rank selective literal raise sites for explicit positive raise intent."""
    _whole, expanded = surface_names(query)
    arguments = requested_raise_names(query, expanded)
    if not arguments:
        return []
    marks = ",".join("?" * len(arguments))
    try:
        total = con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        cap = max(1, int(total * 0.02))
        rows = con.execute(
            "WITH selective(name) AS ("
            " SELECT name FROM relations WHERE kind='raises' "
            f" AND name IN ({marks}) GROUP BY name "
            " HAVING COUNT(DISTINCT block_id)<=?"
            ") "
            "SELECT DISTINCT r.block_id,f.path,b.ordinal "
            "FROM relations r JOIN selective s ON s.name=r.name "
            "JOIN blocks b ON b.id=r.block_id JOIN files f ON f.id=b.file_id "
            "WHERE r.kind='raises'",
            (*arguments, cap),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    scope = {
        row["path"].split("/", 1)[0].lower()
        for row in rows
        if row["path"].split("/", 1)[0].lower() in expanded
    }
    ordered = sorted(rows, key=lambda row: (
        bool(scope) and row["path"].split("/", 1)[0].lower() not in scope,
        row["path"], row["ordinal"], row["block_id"],
    ))
    return [row["block_id"] for row in ordered[:limit]]


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_DOTTED_NAME = re.compile(rf"(?<![\w.]){_IDENT}(?:\.{_IDENT})+")
_CALLED_NAME = re.compile(rf"(?<![\w.])({_IDENT})\(")
_BACKTICKED = re.compile(r"`([^`\n]{1,200})`")
_IDENT_WORD = re.compile(_IDENT)

#: A name with more definitions than this is too ambiguous to be evidence
#: (``__init__``, ``get``). NPK-Bench E002b measured 3-25 within noise.
MAX_DEFINITION_AMBIGUITY = 10


def _code_like(token: str) -> bool:
    """snake_case, camel humps, or letters mixed with digits (not prose)."""
    core = token.strip("_")
    if not core or len(token) < 3:
        return False
    if "_" in core:
        return True
    if re.search(r"[a-z][A-Z]", core) or re.search(r"[A-Z]{2,}[a-z]", core):
        return True
    return bool(re.search(r"[A-Za-z]", core) and re.search(r"\d", core))


def _query_entities(query: str) -> List[str]:
    """Code identifiers a query names explicitly, in first-mention order.

    Sources: dotted references (``django.core.exceptions.ValidationError``,
    ``Signal.send_robust``), called names (``send_robust(``), backticked code,
    and words that are code-like by spelling. Plain prose words are ignored.
    """
    names: List[str] = []
    for match in _DOTTED_NAME.finditer(query):
        parts = match.group(0).split(".")
        if all(len(part) <= 2 for part in parts):  # e.g. "e.g", "v2.0"
            continue
        names.extend(part for part in parts
                     if len(part) >= 3 and part.lower() not in FUNCTION_WORDS)
    names.extend(m.group(1) for m in _CALLED_NAME.finditer(query) if len(m.group(1)) >= 3)
    for match in _BACKTICKED.finditer(query):
        names.extend(w for w in _IDENT_WORD.findall(match.group(1)) if len(w) >= 3)
    names.extend(w for w in _IDENT_WORD.findall(query) if _code_like(w))
    return list(dict.fromkeys(names))


TEST_PATH = re.compile(r"(^|/)(tests?|testing)(/|$)|(^|/)test_[^/]*$|_tests?\.py$|(^|/)conftest\.py$")
DOC_PATH = re.compile(r"(^|/)(docs?|doc_src)(/|$)|\.(rst|md|txt)$")
_GENERIC_PATH_PARTS = frozenset({"tests", "test", "testing", "src", "lib", "py", "__init__", "unit", "units", "t"})


def _path_parts(path: str) -> List[str]:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", path)
    return [part for part in re.split(r"[/_.-]+", stem.lower()) if part]


def _mate_score(impl: str, test: str) -> float:
    """How strongly a test path mirrors an implementation path (0 = unrelated).

    ``pkg/mod.py`` -> ``tests/pkg/test_mod.py``: the module name counts 2, its
    package 1, any other shared non-generic path part 0.25.
    """
    ip, tp = _path_parts(impl), _path_parts(test)
    if not ip or not tp:
        return 0.0
    module, parent = ip[-1], (ip[-2] if len(ip) > 1 else "")
    score = 0.0
    if module in tp and module not in _GENERIC_PATH_PARTS:
        score += 2.0
    if parent and parent in tp and parent not in _GENERIC_PATH_PARTS:
        score += 1.0
    shared = (set(ip) & set(tp)) - _GENERIC_PATH_PARTS - {module, parent}
    return score + 0.25 * len(shared)


def _test_mate(con: sqlite3.Connection, query: str, impl_path: str, exclude: Set[int]) -> Optional[int]:
    """Best query-matching block of the test file that mirrors *impl_path*."""
    scored = sorted(((_mate_score(impl_path, row[0]), row[0]) for row in con.execute("SELECT path FROM files")
                     if TEST_PATH.search(row[0])), key=lambda pair: (-pair[0], pair[1]))
    if not scored or scored[0][0] < 1.0:
        return None
    mates = [path for score, path in scored[:3] if score == scored[0][0]]
    terms = _lexical_terms(con, query)
    if not terms:
        return None
    marks = ",".join("?" * len(mates))
    try:
        rows = con.execute(
            "SELECT lexical.rowid FROM lexical JOIN blocks b ON b.id=lexical.rowid "
            "JOIN files f ON f.id=b.file_id WHERE lexical MATCH ? "
            f"AND f.path IN ({marks}) ORDER BY bm25(lexical,1.0,1.0,1.0),"
            "f.path COLLATE BINARY,b.ordinal LIMIT 5",
            (" OR ".join(f'"{term}"' for term in terms), *mates)).fetchall()
    except sqlite3.OperationalError:
        return None
    return next((row[0] for row in rows if row[0] not in exclude), None)


def _definition_channel(con: sqlite3.Connection, query: str, limit: int,
                        lexical: Sequence[int]) -> List[int]:
    """Blocks that define identifiers the query names.

    Issue-style queries name the code they concern, but a flat OR over many
    prose terms lets documentation and tests that repeat the vocabulary
    outrank the definition. Each named identifier votes for its defining
    blocks with weight ``1/log2(1+n)`` for ``n`` distinct definitions; names
    defined in more than ``MAX_DEFINITION_AMBIGUITY`` blocks are ignored.
    Ties keep lexical rank, then source order (never mutable row IDs).
    """
    names = _query_entities(query)
    if not names:
        return []
    marks = ",".join("?" * len(names))
    try:
        rows = con.execute(
            "SELECT s.name, s.block_id, f.path, b.ordinal FROM symbols s "
            "JOIN blocks b ON b.id=s.block_id JOIN files f ON f.id=b.file_id "
            f"WHERE s.is_def=1 AND s.name IN ({marks})", tuple(names)).fetchall()
    except sqlite3.OperationalError:
        return []
    by_name: Dict[str, Set[int]] = {}
    position: Dict[int, Tuple[str, int]] = {}
    for row in rows:
        by_name.setdefault(row[0], set()).add(row[1])
        position[row[1]] = (row[2], row[3])
    score: Dict[int, float] = {}
    for blocks in by_name.values():
        if len(blocks) > MAX_DEFINITION_AMBIGUITY:
            continue
        weight = 1.0 / math.log2(1 + len(blocks))
        for block_id in blocks:
            score[block_id] = score.get(block_id, 0.0) + weight
    lexical_rank = {block_id: rank for rank, block_id in enumerate(lexical)}
    unranked = len(lexical_rank)
    ordered = sorted(score, key=lambda b: (-score[b], lexical_rank.get(b, unranked), position[b]))
    return ordered[:limit]


def _embedding_channel(con: sqlite3.Connection, query: str, limit: int,
                       manifest: Dict[str, str]) -> Tuple[List[int], Optional[float]]:
    """Rank by cosine similarity against the PRECOMPUTED index.

    Only the query is encoded here. Returns ``([], None)`` when the pack has no
    embedding index or no local encoder is installed -- the deterministic
    channels then carry the query on their own.
    """
    dim = int(manifest.get("embedding_dim") or 0)
    if dim <= 0:
        return [], None

    from ..context.embedding import get_backend
    from .compile import unpack_vector

    backend = get_backend()
    if not backend.available():
        return [], None
    require_encoder_match(manifest,backend.identity())
    qvec = backend.embed_query(query)
    if qvec is None:
        return [], None
    if len(qvec)!=dim or any(type(x) not in (int,float) or not math.isfinite(x) for x in qvec):
        raise PackError("query encoder returned an incompatible vector")

    rows = con.execute(
        "SELECT e.block_id,e.vector FROM embeddings e JOIN blocks b ON b.id=e.block_id "
        "JOIN files f ON f.id=b.file_id WHERE e.dim=? ORDER BY f.path COLLATE BINARY,b.ordinal",
        (len(qvec),)).fetchall()
    if not rows:
        return [], None

    # Columnar scan. The row-at-a-time version (struct.unpack + a scalar dot
    # product per block) measured 81.7 ms on 1,587 blocks -- 60x the lexical
    # channel, and O(N) in Python, which would be seconds on a real repository.
    # Concatenating the raw buffers and doing ONE matmul moves the whole scan
    # into BLAS.
    try:
        import numpy as np

        ids = np.fromiter((r["block_id"] for r in rows), dtype=np.int64, count=len(rows))
        matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32)
        matrix = matrix.reshape(len(rows), len(qvec))
        sims = matrix @ np.asarray(qvec, dtype=np.float32)
        # Stable ties inherit canonical source order, not mutable row IDs.
        top_k = np.argsort(-sims,kind="stable")[:limit]
        return [int(ids[i]) for i in top_k], float(sims[top_k[0]])
    except ImportError:
        # numpy is optional; correctness must not depend on it.
        scored: List[Tuple[float, int]] = []
        for row in rows:
            vec = unpack_vector(row["vector"], len(qvec))
            scored.append((sum(a * b for a, b in zip(vec, qvec)), row["block_id"]))
        scored.sort(key=lambda pair:-pair[0])
        return [bid for _s, bid in scored[:limit]], scored[0][0]


def _expand_dependencies(con: sqlite3.Connection, seeds: Sequence[int], depth: int,
                         limit: int) -> List[int]:
    """Experimental bounded graph reachability; the caller rechecks its budget."""
    if not seeds:
        return []
    reached: Set[int] = set(seeds)
    frontier: Set[int] = set(seeds)
    for _ in range(max(0, depth)):
        if not frontier or len(reached) >= limit:
            break
        marks = ",".join("?" * len(frontier))
        rows = con.execute(
            f"SELECT DISTINCT dst_block_id FROM deps WHERE src_block_id IN ({marks})",
            tuple(frontier),
        ).fetchall()
        nxt = {r["dst_block_id"] for r in rows} - reached
        reached |= nxt
        frontier = nxt
    return sorted(reached - set(seeds))


# ---------------------------------------------------------------------------
# Graceful degradation for an oversized top-ranked block
# ---------------------------------------------------------------------------

#: Only Python blocks at least this large are split into member spans.
TRIM_MIN_TOKENS = 200


def _member_spans(con: sqlite3.Connection, block: Block) -> List[Tuple[int, int, str, str]]:
    """Member spans of a Python class block, as the python_members splitter cuts them.

    The file is rebuilt from its stored blocks (exact line spans; gaps are
    blank lines), so classes that were cut into several line-window chunks
    still parse. Every member overlapping *block* is returned, clipped to the
    block's lines: a method that straddles a chunk boundary stays eligible.
    """
    import ast
    from .compile import _class_member_spans

    lines: List[str] = []
    for start, text in con.execute(
            "SELECT start_line, text FROM blocks WHERE file_id=? ORDER BY start_line", (block.file_id,)):
        body = text.split("\n")
        if len(lines) < start - 1:
            lines.extend([""] * (start - 1 - len(lines)))
        lines[start - 1:start - 1 + len(body)] = body
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    spans = [span for node in tree.body if isinstance(node, ast.ClassDef)
             for span in _class_member_spans(node, node.name)]
    lo, hi = block.start_line, block.end_line
    return [(max(s, lo), min(e, hi), kind, name) for s, e, kind, name in spans if s <= hi and e >= lo]


def _rank_members(con: sqlite3.Connection, block: Block, members, query: str):
    """Order member spans by BM25-style overlap with the query.

    IDF is local to the block's file (rarity among its blocks), which needs
    no index writes and distinguishes sibling methods of one class.
    """
    terms = _lexical_terms(con, query)
    rows = [r[0] for r in con.execute("SELECT text FROM blocks WHERE file_id=?", (block.file_id,))]
    vocab = [set(analyzed_terms(text)) for text in rows]
    total = len(vocab)
    idf = {t: max(0.0, math.log((total - sum(t in v for v in vocab) + 0.5)
                                / (sum(t in v for v in vocab) + 0.5))) + 0.01 for t in terms}
    lines = block.text.split("\n")
    ranked = []
    for index, (start, end, kind, name) in enumerate(members):
        text = "\n".join(lines[start - block.start_line:end - block.start_line + 1])
        counts: Dict[str, int] = {}
        for term in analyzed_terms(text):
            counts[term] = counts.get(term, 0) + 1
        n = sum(counts.values()) or 1
        score = sum(idf[t] * counts[t] * 2.2 / (counts[t] + 1.2 * (0.25 + 0.75 * n / 200))
                    for t in terms if t in counts)
        ranked.append((-score, index, start, end, kind, name, text))
    ranked.sort()
    return [(start, end, kind, name, text) for _s, _i, start, end, kind, name, text in ranked]


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

class PackSelector:
    """Query-time selection over a compiled artifact.

    Provider-independent: ``target_model`` is accepted as advisory metadata;
    exact token accounting requires an explicit local tokenizer asset. The
    model name alone does not infer or download one.
    """

    def __init__(
        self,
        pack_path: str,
        *,
        default_budget: int = 2000,
        candidate_limit: int = 60,
        retrieval: str = "lexical",
        enable_dependency_expansion: bool = False,
        resolve_conflicts: bool = False,
        dense_floor: float = 0.35,
        tokenizer: Optional[LocalTokenizer] = None,
        enable_relations: bool = True,
        enable_definitions: bool = True,
        enable_trim: bool = True,
        enable_test_mate: bool = True,
        enable_cache: bool = True,
        max_cache_entries: int = 128,
    ):
        for name, value in (("default_budget", default_budget), ("candidate_limit", candidate_limit)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if retrieval not in {"lexical", "hybrid"}:
            raise ValueError("retrieval must be 'lexical' or 'hybrid'")
        self.retrieval = retrieval
        self.pack_path = str(pack_path)
        self.default_budget = default_budget
        self.candidate_limit = candidate_limit
        self.enable_dependency_expansion = enable_dependency_expansion
        self.resolve_conflicts = resolve_conflicts
        self.dense_floor = dense_floor
        if tokenizer is not None and not isinstance(tokenizer, LocalTokenizer):
            raise TypeError("tokenizer must be an explicit LocalTokenizer")
        self.tokenizer = tokenizer
        if type(enable_relations) is not bool:
            raise ValueError("enable_relations must be a boolean")
        self.enable_relations = enable_relations
        if type(enable_definitions) is not bool:
            raise ValueError("enable_definitions must be a boolean")
        self.enable_definitions = enable_definitions
        if type(enable_trim) is not bool:
            raise ValueError("enable_trim must be a boolean")
        self.enable_trim = enable_trim
        if type(enable_test_mate) is not bool:
            raise ValueError("enable_test_mate must be a boolean")
        self.enable_test_mate = enable_test_mate
        self._con: Optional[sqlite3.Connection] = None
        self._manifest: Optional[Dict[str, str]] = None
        self._data_version: Optional[int] = None
        if type(enable_cache) is not bool:
            raise ValueError("enable_cache must be a boolean")
        if type(max_cache_entries) is not int or max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be a positive integer")
        self.enable_cache = enable_cache
        self.max_cache_entries = max_cache_entries
        self._cache: collections.OrderedDict = collections.OrderedDict()

    def __enter__(self) -> PackSelector:
        if self._con is None:
            con = connect(self.pack_path, readonly=True)
            try:
                con.execute("BEGIN")
                data_version = con.execute("PRAGMA data_version").fetchone()[0]
                manifest = read_manifest(con)
                require_supported(manifest)
                con.execute("ROLLBACK")
            except BaseException:
                con.close()
                raise
            self._con = con
            self._manifest = manifest
            self._data_version = data_version
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            finally:
                self._con = None
                self._manifest = None
                self._data_version = None
        self.clear_cache()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _count(self, evidence: Sequence[Evidence]) -> int:
        if self.tokenizer is None:
            return _context_tokens(evidence)
        return self.tokenizer.count("\n\n".join(e.text for e in evidence))

    def _fits(self, evidence: Sequence[Evidence], text: str, budget: int,
              *, used_chars: Optional[int] = None) -> bool:
        if self.tokenizer is None:
            if used_chars is None:
                used_chars = sum(len(e.text) for e in evidence) + max(0,len(evidence)-1)*2
            chars = used_chars + len(text) + (2 if evidence else 0)
            return max(1, chars // 4) <= budget
        return self.tokenizer.count("\n\n".join([e.text for e in evidence] + [text])) <= budget

    def _enforce_final_budget(self, selection: Selection, budget: int) -> None:
        # Token counts need not be additive or decrease after context edits.
        # Recheck the final bytes after optional conflict deletion/expansion.
        removed = 0
        while selection.evidence and self._count(selection.evidence) > budget:
            selection.evidence.pop()
            removed += 1
        selection.total_tokens = self._count(selection.evidence)
        if removed:
            selection.notes.append(f"final token reconciliation removed {removed} passage(s)")

    # ------------------------------------------------------------------
    def select(
        self,
        query: str,
        *,
        budget_tokens: Optional[int] = None,
        target_model: Optional[str] = None,
        allow_escalation: bool = True,
    ) -> Selection:
        started = time.perf_counter()
        # target_model is accepted for provider-independent integrations. No
        # pricing lookup or automatic model-to-tokenizer inference happens here.
        budget = self.default_budget if budget_tokens is None else budget_tokens
        if type(budget) is not int or budget <= 0:
            raise ValueError("budget_tokens must be a positive integer")

        if self._con is not None:
            self._con.execute("BEGIN")
            try:
                # Metadata, candidates and cache identity must belong to this
                # query's snapshot, including after a committed update.
                data_version = self._con.execute("PRAGMA data_version").fetchone()[0]
                if self._manifest is None or data_version != self._data_version:
                    manifest = read_manifest(self._con)
                    require_supported(manifest)
                    self.clear_cache()
                    self._manifest = manifest
                    self._data_version = data_version
                else:
                    manifest = self._manifest
                return self._select_with_con(
                    self._con, manifest, query, budget, target_model, allow_escalation, started
                )
            finally:
                self._con.execute("ROLLBACK")

        with open_pack(self.pack_path) as con:
            manifest = read_manifest(con)
            require_supported(manifest)

            return self._select_with_con(
                con, manifest, query, budget, target_model, allow_escalation, started
            )

    def _select_with_con(
        self,
        con: sqlite3.Connection,
        manifest: Dict[str, str],
        query: str,
        budget: int,
        target_model: Optional[str],
        allow_escalation: bool,
        started: float,
    ) -> Selection:
            cache_key = None
            # Hybrid selection observes the current local encoder. An artifact
            # root alone cannot key its availability or identity checks.
            if self.enable_cache and self.retrieval == "lexical":
                cache_key = (
                    manifest.get("root_sha256", ""),
                    query,
                    budget,
                    target_model,
                    allow_escalation,
                    self.retrieval,
                    self.enable_dependency_expansion,
                    self.resolve_conflicts,
                    self.candidate_limit,
                    self.enable_relations,
                    self.enable_definitions,
                    self.enable_trim,
                    self.enable_test_mate,
                    self.tokenizer.sha256 if self.tokenizer is not None else None,
                )
                if cache_key in self._cache:
                    cached = self._cache[cache_key]
                    self._cache.move_to_end(cache_key)
                    res = _copy_selection(cached)
                    res.latency_ms = (time.perf_counter() - started) * 1000.0
                    return res

            try:
                available = int(manifest["available_tokens"])
                if available < 0:
                    raise ValueError
            except (KeyError, ValueError) as exc:
                raise PackError("artifact has invalid available-token metadata; recompile") from exc

            sel = self._select_once(con, manifest, query, budget, self.candidate_limit)
            escalations: List[str] = []

            # Escalation ladder -- deterministic and local at every rung.
            if allow_escalation and (sel.seed_failed or not sel.evidence):
                escalations.append("widen_retrieval")
                sel = self._select_once(con, manifest, query, budget,
                                        self.candidate_limit * 4)

            if allow_escalation and self.enable_dependency_expansion and sel.evidence:
                extra = _expand_dependencies(
                    con, [e.block_id for e in sel.evidence], depth=2,
                    limit=self.candidate_limit)
                if extra:
                    escalations.append("expand_dependencies")
                    sel = self._assemble(con, query, sel, extra, budget)

            if self.resolve_conflicts and len(sel.evidence) > 1:
                sel = self._drop_contradictions(con, sel, query)

            self._enforce_final_budget(sel, budget)
            sel.risk_band = self._risk({ch: [] for ch in sel.channels_used}, sel.evidence, query)

            if not sel.evidence:
                # Nothing survived. Report an explicit failure rather than an
                # empty context that looks like a successful optimization.
                escalations.append("raw_fallback")
                sel.seed_failed = True
                sel.risk_band = "uncalibrated:maximum"
                sel.notes.append(
                    "no evidence selected; caller MUST fall back to full context")

            sel.escalations = escalations
            sel.available_tokens_estimate = available
            # Do not divide exact selected tokens by an estimated corpus size.
            sel.available_tokens = available if self.tokenizer is None else None
            sel.tokenizer = self.tokenizer.as_dict() if self.tokenizer else None
            if self.tokenizer:
                for evidence in sel.evidence:
                    evidence.tokens = self.tokenizer.count(evidence.text)
            elif target_model is not None:
                sel.notes.append("target model is advisory; configure a matching local tokenizer for exact context counts")
            sel.latency_ms = (time.perf_counter() - started) * 1000.0
            sel.used_generative_llm = False
            if self.enable_cache and cache_key is not None:
                self._cache[cache_key] = _copy_selection(sel)
                if len(self._cache) > self.max_cache_entries:
                    self._cache.popitem(last=False)
            return sel

    # ------------------------------------------------------------------
    def _drop_contradictions(self, con, sel: "Selection", query: str) -> "Selection":
        """Experimental path-based deletion, with conservative abstention."""
        from .conflict import resolve_value_conflicts

        ids = [e.block_id for e in sel.evidence]
        paths = {e.block_id: e.path for e in sel.evidence}
        rank_of = {e.block_id: i for i, e in enumerate(sel.evidence)}

        drop, decisions = resolve_value_conflicts(con, ids, paths, query, rank_of)
        if not drop:
            return sel

        sel.evidence = [e for e in sel.evidence if e.block_id not in drop]
        sel.total_tokens = self._count(sel.evidence)
        sel.conflicts_resolved = [d.as_dict() for d in decisions]
        sel.notes.append(
            f"dropped {len(drop)} contradicting block(s) across "
            f"{len(decisions)} symbol conflict(s)")
        return sel

    # ------------------------------------------------------------------
    def _select_once(self, con, manifest, query: str, budget: int, limit: int) -> Selection:
        ranks: Dict[str, List[int]] = {}
        notes: List[str] = []

        if self.retrieval == "hybrid":
            sym = _symbol_channel(con, query, limit)
            if sym:
                ranks["symbol"] = sym
        lex = _lexical_channel(con, query, limit)
        if lex:
            ranks["lexical"] = lex
        if self.enable_relations:
            relation = _relation_channel(con, query, limit)
            if relation:
                ranks["relation"] = relation
        if self.enable_definitions:
            definition = _definition_channel(con, query, limit, lex)
            if definition:
                ranks["definition"] = definition

        if self.retrieval == "hybrid":
            emb, top_sim = _embedding_channel(con, query, limit, manifest)
            if emb and (top_sim is None or top_sim >= self.dense_floor):
                ranks["embedding"] = emb
            elif int(manifest.get("embedding_dim") or 0)>0 and not emb:
                notes.append("local embedding channel unavailable; selection uses remaining channels")

        if not ranks:
            return Selection(query=query, evidence=[], total_tokens=0,
                             budget_tokens=budget, available_tokens=0,
                             channels_used=[], escalations=[],
                             risk_band="uncalibrated:maximum", seed_failed=True,
                             latency_ms=0.0,
                             notes=notes+["no channel produced a candidate"])

        fused: Dict[int, float] = {}
        channels_of: Dict[int, List[str]] = {}
        for channel, ordered in ranks.items():
            for rank, block_id in enumerate(ordered):
                fused[block_id] = fused.get(block_id, 0.0) + 1.0 / (RRF_K + rank)
                channels_of.setdefault(block_id, []).append(channel)

        ordered_ids = sorted(fused, key=lambda b: -fused[b])
        if self.enable_test_mate and ordered_ids:
            ordered_ids = self._place_test_mate(con, query, ordered_ids, fused, channels_of)
        blocks = {b.id: b for b in load_blocks(con, ordered_ids)}

        evidence: List[Evidence] = []
        used_chars = 0
        top = ordered_ids[0] if ordered_ids else None
        for block_id in ordered_ids:
            blk = blocks.get(block_id)
            if blk is None:
                continue
            if not self._fits(evidence, blk.text, budget, used_chars=used_chars):
                # The best candidate never silently disappears: when it alone
                # cannot fit, admit its most query-relevant member spans.
                # Lower-ranked blocks that do not fit are skipped as before.
                if block_id == top and self.enable_trim:
                    used_chars = self._admit_members(
                        con, blk, query, budget, evidence, used_chars,
                        fused[block_id], channels_of.get(block_id, []), notes)
                continue
            used_chars += len(blk.text) + (2 if evidence else 0)
            evidence.append(Evidence(
                block_id=blk.id, path=blk.path, span=blk.span, kind=blk.kind,
                name=blk.name, tokens=blk.tokens, text=blk.text,
                score=fused[block_id], channels=channels_of.get(block_id, []),
            ))

        risk = self._risk(ranks, evidence, query)
        return Selection(
            query=query, evidence=evidence, total_tokens=self._count(evidence),
            budget_tokens=budget, available_tokens=0,
            channels_used=sorted(ranks), escalations=[],
            risk_band=risk, seed_failed=not evidence, latency_ms=0.0, notes=notes,
        )

    def _place_test_mate(self, con, query: str, ordered_ids: List[int], fused: Dict[int, float],
                         channels_of: Dict[int, List[str]]) -> List[int]:
        """Put the test block that mirrors the top implementation file right after it.

        Tests that exercise the code under change are where a regression test
        goes; lexical ranking alone places them far down once definitions rank
        first (E002). The mate is chosen structurally (path convention) and
        lexically within that file, never by demoting anything else.
        """
        paths = dict(con.execute(
            f"SELECT b.id, f.path FROM blocks b JOIN files f ON f.id=b.file_id "
            f"WHERE b.id IN ({','.join('?' * len(ordered_ids))})", ordered_ids).fetchall())
        position = next((i for i, b in enumerate(ordered_ids)
                         if not TEST_PATH.search(paths.get(b, "")) and not DOC_PATH.search(paths.get(b, ""))), None)
        if position is None:
            return ordered_ids
        mate = _test_mate(con, query, paths[ordered_ids[position]], set(ordered_ids[:position + 1]))
        if mate is None:
            return ordered_ids
        reordered = [b for b in ordered_ids if b != mate]
        reordered.insert(position + 1, mate)
        fused.setdefault(mate, 0.0)
        channels_of.setdefault(mate, []).append("test_mate")
        return reordered

    def _admit_members(self, con, blk: Block, query: str, budget: int, evidence: List[Evidence],
                       used_chars: int, score: float, channels: List[str], notes: List[str]) -> int:
        """Admit the best member spans of an oversized block; return used chars.

        Members are exact line slices of the block with their own spans, so
        each can be cited and the elided remainder re-read by span. Only
        Python class blocks of at least ``TRIM_MIN_TOKENS`` are split.
        """
        if not blk.path.endswith((".py", ".pyi")) or blk.tokens < TRIM_MIN_TOKENS:
            return used_chars
        members = _member_spans(con, blk)
        if len(members) <= 1:
            return used_chars
        added = 0
        for start, end, kind, name, text in _rank_members(con, blk, members, query):
            if not text.strip() or not self._fits(evidence, text, budget, used_chars=used_chars):
                continue
            used_chars += len(text) + (2 if evidence else 0)
            evidence.append(Evidence(
                block_id=blk.id, path=blk.path, span=f"{blk.path}:{start}-{end}",
                kind=kind, name=name, tokens=max(1, len(text) // 4), text=text,
                score=score, channels=list(channels) + ["trimmed"],
            ))
            added += 1
        if added:
            notes.append(f"top-ranked block {blk.span} exceeds the budget; "
                         f"emitted {added} of its {len(members)} member spans")
        return used_chars

    def _assemble(self, con, query, base: Selection, extra_ids: List[int], budget: int) -> Selection:
        have = {e.block_id for e in base.evidence}
        used_chars = sum(len(e.text) for e in base.evidence) + max(0,len(base.evidence)-1)*2
        for blk in load_blocks(con, [i for i in extra_ids if i not in have]):
            if not self._fits(base.evidence, blk.text, budget, used_chars=used_chars):
                continue
            used_chars += len(blk.text) + (2 if base.evidence else 0)
            base.evidence.append(Evidence(
                block_id=blk.id, path=blk.path, span=blk.span, kind=blk.kind,
                name=blk.name, tokens=blk.tokens, text=blk.text,
                score=0.0, channels=["dependency_expansion"],
            ))
        base.total_tokens = self._count(base.evidence)
        return base

    def _risk(self, ranks: Dict[str, List[int]], evidence: List[Evidence], query: str) -> str:
        """Ordinal, uncalibrated. Never presented as a probability."""
        if not evidence:
            return "uncalibrated:maximum"
        terms = _content_terms(query)
        if terms:
            joined = " ".join(e.text for e in evidence).lower()
            present = [t for t in terms if t in joined]
            coverage = len(present) / len(terms)
        else:
            coverage = 1.0
        # Having two channels is not agreement: they may retrieve disjoint sets.
        overlap = any(len(set(e.channels) - {"dependency_expansion"}) >= 2 for e in evidence)
        if coverage >= 0.8 and overlap:
            return "uncalibrated:low"
        if coverage >= 0.5 or overlap:
            return "uncalibrated:moderate"
        return "uncalibrated:high"

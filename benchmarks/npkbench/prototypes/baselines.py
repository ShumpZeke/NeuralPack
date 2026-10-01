"""B001: a standard-RAG baseline on the same packs, budgets and gold.

The question the README leaves open: does NeuralPack beat what a typical
retrieval pipeline does with the same repository? The baseline here is the
common default: every indexed file cut into fixed 60-line chunks, Okapi BM25
(k1=1.2, b=0.75) over lowercase word tokens, the issue text (unique terms) as
the query, and greedy filling of the budget in score order.

``b001_bm25_chunks`` keeps identifiers whole (``send_robust``), as most
off-the-shelf tokenizers do; ``b001_bm25_chunks_split`` also indexes their
snake/camel parts, like NeuralPack's analyzer. ``b002_bm25_chars1000_split``
uses the common RAG splitter default instead (about 1,000 characters per chunk,
cut at line boundaries), which suits chat text with long lines. File texts are rebuilt exactly
from the pack's stored blocks, so both systems see the same files.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from npk.pack.format import open_pack

from ..arms import Arm, ArmResult, register
from ..data import Task

CHUNK_LINES = 60
K1, B = 1.2, 0.75
WORD = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def _tokens(text: str, split: bool) -> List[str]:
    out = []
    for word in WORD.findall(text):
        low = word.lower()
        out.append(low)
        if split:
            parts = [p.lower() for piece in word.split("_") if piece for p in CAMEL.findall(piece)]
            if len(parts) > 1:
                out.extend(parts)
    return out


def _char_chunks(con, size: int) -> List[Tuple[str, int, int, str]]:
    """Chunks of about *size* characters cut at line boundaries (LangChain-style default)."""
    out = []
    for path, lo, hi, text in _chunks(con, lines_per_chunk=10**9):
        lines = text.split("\n")
        start, buf, used = lo, [], 0
        for offset, line in enumerate(lines):
            if buf and used + len(line) + 1 > size:
                body = "\n".join(buf)
                if body.strip():
                    out.append((path, start, lo + offset - 1, body))
                start, buf, used = lo + offset, [], 0
            buf.append(line)
            used += len(line) + 1
        body = "\n".join(buf)
        if body.strip():
            out.append((path, start, lo + len(lines) - 1, body))
    return out


def _chunks(con, lines_per_chunk: int = CHUNK_LINES) -> List[Tuple[str, int, int, str]]:
    files: Dict[str, List[str]] = {}
    for path, start, text in con.execute(
            "SELECT f.path, b.start_line, b.text FROM blocks b JOIN files f ON f.id=b.file_id "
            "ORDER BY f.path, b.start_line"):
        lines = files.setdefault(path, [])
        body = text.split("\n")
        if len(lines) < start - 1:
            lines.extend([""] * (start - 1 - len(lines)))
        lines[start - 1:start - 1 + len(body)] = body
    out = []
    for path, lines in files.items():
        for i in range(0, len(lines), lines_per_chunk):
            text = "\n".join(lines[i:i + lines_per_chunk])
            if text.strip():
                out.append((path, i + 1, min(i + lines_per_chunk, len(lines)), text))
    return out


def bm25_order(chunks, query: str, split: bool) -> List[int]:
    docs = [Counter(_tokens(text, split)) for _p, _s, _e, text in chunks]
    lengths = [sum(d.values()) for d in docs]
    avg = sum(lengths) / max(1, len(lengths))
    df: Dict[str, int] = defaultdict(int)
    for d in docs:
        for term in d:
            df[term] += 1
    n = len(docs)
    terms = list(dict.fromkeys(_tokens(query, split)))
    scores = []
    for i, d in enumerate(docs):
        s = 0.0
        for t in terms:
            tf = d.get(t)
            if tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * lengths[i] / avg))
        if s > 0:
            scores.append((-s, chunks[i][0], chunks[i][1], i))
    scores.sort()
    return [i for _s, _p, _l, i in scores]


def make(name: str, split: bool, chars: int = 0) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with open_pack(pack) as con:
            chunks = _char_chunks(con, chars) if chars else _chunks(con)
        order = bm25_order(chunks, task.query, split)
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for i in order:
                path, lo, hi, text = chunks[i]
                extra = len(text) + (2 if n else 0)
                if max(1, (used + extra) // 4) > budget:
                    continue
                used, n = used + extra, n + 1
                spans.append((path, lo, hi))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, elapsed,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make("b001_bm25_chunks", split=False)
make("b001_bm25_chunks_split", split=True)
# B002: the common RAG default chunker (about 1,000 characters at line boundaries).
make("b002_bm25_chars1000_split", split=True, chars=1000)

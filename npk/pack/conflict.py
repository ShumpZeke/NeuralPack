"""Experimental path-scoped conflict filtering; disabled by default.

Different values are a diagnostic, not proof that one block can be deleted.
Comparison/history queries and blocks with other named facts cause abstention.
These are heuristics, not evidence-sufficiency guarantees. Cycle 3 discarded
source-order supersession and literal-to-path voting after counterexamples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

#: ``NAME = literal`` at statement level. Deliberately narrow: only screaming-snake
#: constants, which is where configuration conflicts actually live.
ASSIGNMENT_RE = re.compile(
    r"^[ \t]*([A-Z_][A-Z0-9_]{2,})[ \t]*(?::[^=\n]+)?=[ \t]*(.+?)[ \t]*$",
    re.MULTILINE,
)

#: Path fragments that mark a variant as superseded.
DEPRECATION_MARKERS = ("legacy", "deprecated", "old", "backup", "bak", "v0", "archive", "vendor")

#: Words meaning "give me the historical/old one" -- inverts the recency rule.
HISTORICAL_CUES = frozenset({"original", "previous", "old", "deprecated", "former", "initial"})


def extract_assignments(text: str) -> List[Tuple[str, str]]:
    """Return ``(symbol, value_hash)`` pairs for constant assignments in *text*."""
    out: List[Tuple[str, str]] = []
    for match in ASSIGNMENT_RE.finditer(text):
        symbol, value = match.group(1), match.group(2).strip()
        if not value or value.startswith(("#",)):
            continue
        # Normalise trailing comments so `X = 1  # note` matches `X = 1`.
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if not value:
            continue
        digest = hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()[:16]
        out.append((symbol, digest))
    return out


def _scope_tokens(query: str) -> Set[str]:
    """Lowercased words from the query usable as path/scope hints."""
    return {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query.lower())}


def _path_affinity(path: str, scope: Set[str]) -> int:
    """How strongly *path* matches the query's scope tokens."""
    parts = set(re.split(r"[/\\._-]+", path.lower()))
    return len(parts & scope)


def _deprecation_penalty(path: str) -> int:
    low = path.lower()
    parts = set(re.split(r"[/\\._-]+", low))
    return sum(1 for m in DEPRECATION_MARKERS if m in parts)


# No literal-to-path voting: a comment, example, or unused assignment can name
# any variant. A future indirection resolver must prove the binding/use chain.
COMPARISON_CUES = frozenset({
    "compare", "comparison", "contrast", "difference", "differences", "differ",
    "both", "versus", "between", "across", "before", "after", "changed", "changes",
})


@dataclass
class ConflictDecision:
    """Why a block was kept or dropped. Surfaced as provenance, never silent."""

    symbol: str
    kept_block_id: int
    dropped_block_ids: List[int] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kept_block_id": self.kept_block_id,
            "dropped_block_ids": self.dropped_block_ids,
            "reason": self.reason,
        }


def find_conflict_sets(con: sqlite3.Connection, block_ids: Sequence[int]) -> Dict[str, List[int]]:
    """Symbols among *block_ids* that are assigned DIFFERENT values.

    A symbol assigned the same value everywhere is not a conflict -- it is
    corroboration, and dropping it would lose nothing but also gain nothing.
    """
    if not block_ids:
        return {}
    marks = ",".join("?" * len(block_ids))
    rows = con.execute(
        f"SELECT symbol, block_id, value_hash FROM assignments WHERE block_id IN ({marks})",
        tuple(block_ids),
    ).fetchall()

    by_symbol: Dict[str, Dict[int, Set[str]]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], {}).setdefault(row["block_id"], set()).add(
            row["value_hash"])

    conflicts: Dict[str, List[int]] = {}
    for symbol, per_block in by_symbol.items():
        distinct = {h for hashes in per_block.values() for h in hashes}
        if len(per_block) > 1 and len(distinct) > 1:
            conflicts[symbol] = sorted(per_block)
    return conflicts


def resolve_value_conflicts(
    con: sqlite3.Connection,
    ordered_block_ids: Sequence[int],
    paths: Dict[int, str],
    query: str,
    rank_of: Dict[int, int],
) -> Tuple[Set[int], List[ConflictDecision]]:
    """Return ``(block_ids_to_drop, decisions)``.

    Preference order, strongest first: path affinity with the query's scope
    tokens, absence of a deprecation marker, then the fusion rank that got the
    block here. Ties keep everything -- a weak signal must not cost evidence.
    """
    scope = _scope_tokens(query)
    # Historical and comparison requests need variants the old filter deleted.
    # Abstain rather than interpret the user's requested timeframe heuristically.
    if scope & (HISTORICAL_CUES | COMPARISON_CUES):
        return set(), []
    conflicts = find_conflict_sets(con, ordered_block_ids)
    if not conflicts:
        return set(), []

    marks = ",".join("?" * len(ordered_block_ids))
    texts = {r["id"]: r["text"] for r in con.execute(
        f"SELECT id, text FROM blocks WHERE id IN ({marks})", tuple(ordered_block_ids))}
    query_names = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", query))
    mentioned = {bid: query_names & set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text))
                 for bid, text in texts.items()}
    drop: Set[int] = set()
    decisions: List[ConflictDecision] = []

    for symbol, members in conflicts.items():
        members = [b for b in members if b not in drop]
        if len(members) < 2:
            continue

        scored = []
        for bid in members:
            path = paths.get(bid, "")
            scored.append((
                _path_affinity(path, scope),
                -_deprecation_penalty(path),
                -rank_of.get(bid, 10_000),
                bid,
            ))
        scored.sort(reverse=True)

        best, runner_up = scored[0], scored[1]
        # Only act on a decisive signal: identical (affinity, deprecation) means
        # the query does not tell us which variant it wants.
        if best[:2] == runner_up[:2]:
            continue

        keep = best[3]
        # A whole block may hold another requested symbol. Resolving TIMEOUT
        # cannot justify dropping MAX_JOBS from the same block.
        losers = [b for *_x, b in scored[1:]
                  if not (mentioned.get(b, set()) - mentioned.get(keep, set()))]
        if not losers:
            continue
        drop.update(losers)
        reason = ("query scope matches path" if best[0] > runner_up[0]
                  else "other variant is marked deprecated/legacy")
        decisions.append(ConflictDecision(symbol, keep, losers, reason))

    return drop, decisions

"""Deterministic search analysis shared by compilation and query planning."""
from __future__ import annotations

import re
from typing import Iterable, List, Set, Tuple


WORDS = re.compile(r"\w+", re.UNICODE)
CAMEL = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|[0-9]|_|$)|[A-Z]?[a-z]+|[0-9]+"
)
SURFACE = re.compile(r"(?<!\w)[^\W\d]\w*(?:\.[^\W\d]\w*)*(?!\w)", re.UNICODE)
CONTRACTION = re.compile(r"\b\w+n['\u2019]t\b", re.IGNORECASE)

# These words are common English, but they are also frequent program concepts.
# Removing them prevents queries about get/set/return/default-style APIs.
CODE_WORDS = frozenset(
    "value values return returns get set use used using exactly exact configured".split()
)

RELATION_ACTION_WORDS = frozenset(
    "raise raises raised raising throw throws thrown".split()
)
RELATION_BLOCKERS = frozenset("""not no never neither nor without cannot
avoid avoids avoided avoiding prevent prevents prevented preventing
catch catches caught catching handle handles handled handling
suppress suppresses suppressed suppressing
mention mentions mentioned mentioning literal literals string strings""".split())


def analyzed_terms(text: str) -> List[str]:
    """Keep whole Unicode words and add ASCII identifier components."""
    out: List[str] = []
    for word in WORDS.findall(text):
        pieces: List[str] = []
        for piece in word.split("_"):
            camel = CAMEL.findall(piece)
            if len(camel) > 1:
                pieces.extend(part.lower() for part in camel)
            else:
                pieces.append(piece.lower())
        original = word.lower()
        out.append(original)
        if len(pieces) > 1:
            out.extend(part for part in pieces if part and part != original)
    return out


def analyzed_text(text: str) -> str:
    """Stable text stored in FTS fields; source evidence remains elsewhere."""
    return " ".join(analyzed_terms(text))


def surface_names(query: str) -> Tuple[Set[str], Set[str]]:
    """Return whole surface names and those names plus dotted components."""
    whole = {match.group(0).lower() for match in SURFACE.finditer(query)}
    expanded = whole | {part for item in whole for part in item.split(".")}
    return whole, expanded


def requested_raise_names(query: str, known: Iterable[str]) -> List[str]:
    """Conservatively identify explicitly requested exception names.

    This is a retrieval hint, never a claim that a syntactic raise executes.
    Ambiguous global negation/catching language suppresses the hint while normal
    lexical retrieval continues.
    """
    whole, expanded = surface_names(query)
    if not whole.intersection(RELATION_ACTION_WORDS):
        return []
    if whole.intersection(RELATION_BLOCKERS) or CONTRACTION.search(query):
        return []
    return sorted((expanded & set(known)) - RELATION_ACTION_WORDS)

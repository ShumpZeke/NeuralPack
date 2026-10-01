"""Deterministic search analysis shared by compilation and query planning."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple


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


def _word_terms(word: str) -> Tuple[str, ...]:
    """Analysis of one ``\\w+`` word: the word, then its identifier pieces."""
    pieces: List[str] = []
    for piece in word.split("_"):
        camel = CAMEL.findall(piece)
        if len(camel) > 1:
            pieces.extend(part.lower() for part in camel)
        else:
            pieces.append(piece.lower())
    original = word.lower()
    if len(pieces) > 1:
        return (original, *(part for part in pieces if part and part != original))
    return (original,)


# Source vocabularies are small relative to their token streams (a Django
# checkout repeats ~120K distinct words across ~6M occurrences), so per-word
# memoization removes most analysis work. The cache is bounded and the analysis
# is a pure function of the word, so hits and misses give identical output.
_WORD_CACHE: Dict[str, Tuple[str, ...]] = {}
_WORD_CACHE_LIMIT = 1 << 18


def _cached_word_terms(word: str) -> Tuple[str, ...]:
    terms = _WORD_CACHE.get(word)
    if terms is None:
        terms = _word_terms(word)
        if len(_WORD_CACHE) >= _WORD_CACHE_LIMIT:
            _WORD_CACHE.clear()
        _WORD_CACHE[word] = terms
    return terms


def analyzed_terms(text: str) -> List[str]:
    """Keep whole Unicode words and add ASCII identifier components."""
    out: List[str] = []
    for word in WORDS.findall(text):
        out.extend(_cached_word_terms(word))
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

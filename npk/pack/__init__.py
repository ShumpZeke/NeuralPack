"""The .npk compiled context artifact: compiler, format, and query runtime.

NeuralPack is an **LLM-independent context compiler and runtime**. The default
fast path makes **zero generative LLM calls**:

    source / repo / docs / agent history
        -> npk compile  ->  project.npk        (expensive, amortized, once)
        -> npk select   ->  evidence set       (cheap, deterministic, per query)
        -> YOUR target LLM                     (called once, by you)

The optional sentence encoder runs locally and is non-generative. BM25 is the
default; hybrid retrieval must be requested explicitly. No remote frontier
model is used as an optimizer.
"""
from __future__ import annotations

from .compile import CompileStats, compile_pack, estimate_tokens, update_pack
from .format import (
    COMPILE_MODES, MODE_DETERMINISTIC, MODE_SEMANTIC, PACK_FORMAT_VERSION,
    Block, PackError, open_pack, pack_stats, verify,
)
from .select import Evidence, Location, PackSelector, Selection
from .tokenizer import LocalTokenizer

__all__ = [
    "CompileStats", "compile_pack", "update_pack", "estimate_tokens",
    "PACK_FORMAT_VERSION", "COMPILE_MODES", "MODE_DETERMINISTIC", "MODE_SEMANTIC",
    "Block", "PackError", "open_pack", "pack_stats", "verify",
    "PackSelector", "Selection", "Evidence", "Location", "LocalTokenizer",
    "select",
]


def select(pack_path: str, query: str, *, budget_tokens: int = 2000,
           target_model: str | None = None, tokenizer: LocalTokenizer | None = None) -> Selection:
    """Convenience entry point: ``npk.pack.select("project.npk", "why is retry wrong?")``.

    *target_model* is advisory. An explicit local tokenizer enables exact counts.
    """
    return PackSelector(pack_path, tokenizer=tokenizer).select(
        query, budget_tokens=budget_tokens, target_model=target_model)

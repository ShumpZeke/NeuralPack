"""Query-conditioned safe extractive context compressor."""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .analyzer import estimate_tokens


class ExtractiveCompressor:
    def compress_text(
        self,
        text: str,
        query: str,
        target_ratio: float = 0.5,
        min_tokens: int = 500,
    ) -> Tuple[str, Dict[str, int]]:
        orig_tokens = estimate_tokens(text)
        if orig_tokens <= min_tokens:
            return text, {"original_tokens": orig_tokens, "optimized_tokens": orig_tokens, "avoided_tokens": 0}

        query_words = set(re.findall(r"\w+", query.lower()))
        paragraphs = text.split("\n\n")
        scored_paras = []

        for p in paragraphs:
            p_words = set(re.findall(r"\w+", p.lower()))
            overlap = len(query_words & p_words)
            # Priority for definitions, headers, and code signatures
            is_structural = bool(re.search(r"^(?:#|##|def |class |export |public )", p.strip()))
            score = overlap * 2.0 + (1.5 if is_structural else 0.0)
            scored_paras.append((score, p))

        # Select paragraphs until target ratio is met
        target_tokens = max(min_tokens, int(orig_tokens * target_ratio))
        # Rank paragraphs by score
        indexed_scores = sorted(enumerate(scored_paras), key=lambda x: x[1][0], reverse=True)

        kept_indices = set()
        current_tokens = 0
        for idx, (score, p) in indexed_scores:
            p_tok = estimate_tokens(p)
            if current_tokens + p_tok <= target_tokens or not kept_indices:
                kept_indices.add(idx)
                current_tokens += p_tok
            else:
                break

        # Reconstruct in original order
        kept_paragraphs = []
        for idx in sorted(kept_indices):
            kept_paragraphs.append(scored_paras[idx][1])

        compressed_text = "\n\n".join(kept_paragraphs)
        new_tokens = estimate_tokens(compressed_text)
        avoided = max(0, orig_tokens - new_tokens)

        return compressed_text, {
            "original_tokens": orig_tokens,
            "optimized_tokens": new_tokens,
            "avoided_tokens": avoided,
        }

"""Conversation State Compiler: resolves superseded turns and preserves active constraints."""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .analyzer import estimate_tokens


class ConversationCompiler:
    def is_conversation_context(self, text: str) -> bool:
        return "User:" in text and "Assistant:" in text

    def compile_conversation(self, text: str) -> Tuple[str, Dict[str, int]]:
        orig_tokens = estimate_tokens(text)
        turns = re.split(r"(?=(?:User|Assistant):)", text)
        turns = [t.strip() for t in turns if t.strip()]

        if len(turns) <= 3:
            return text, {"original_tokens": orig_tokens, "optimized_tokens": orig_tokens, "tokens_avoided": 0}

        # Find superseded statements (e.g. "disregard option A, use option B now")
        superseded_keywords = set()
        for t in turns:
            m = re.search(r"(?:disregard|ignore|update on|instead of)\s+([a-zA-Z0-9_\s]+?)(?:,|\.|\bwe\b|\buse\b)", t, re.IGNORECASE)
            if m:
                kw = m.group(1).strip().lower()
                if len(kw) > 2:
                    superseded_keywords.add(kw)

        kept_turns = []
        pruned_turns_count = 0
        # Always keep the last 3 turns
        for i, t in enumerate(turns):
            if i >= len(turns) - 3:
                kept_turns.append(t)
            else:
                # Check if turn contains superseded info
                contains_superseded = any(kw in t.lower() for kw in superseded_keywords)
                # Keep turns establishing strict constraints
                is_constraint = any(w in t.lower() for w in ["never", "must", "strictly", "constraint", "always", "only"])
                if contains_superseded and not is_constraint:
                    pruned_turns_count += 1
                    continue
                elif is_constraint:
                    kept_turns.append(t)
                else:
                    pruned_turns_count += 1

        compiled_text = "\n".join(kept_turns)
        new_tokens = estimate_tokens(compiled_text)

        return compiled_text, {
            "original_tokens": orig_tokens,
            "optimized_tokens": new_tokens,
            "tokens_avoided": max(0, orig_tokens - new_tokens),
            "pruned_turns": pruned_turns_count,
        }


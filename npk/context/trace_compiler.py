"""Agent Tool Trace Compiler: compiles noisy, massive tool logs into concise state."""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .analyzer import estimate_tokens


class ToolTraceCompiler:
    def is_trace_context(self, text: str) -> bool:
        return bool(re.search(r"\[(?:Step\s*\d+|Tool Call)\]", text))

    def compile_trace(self, text: str, query: str = "") -> Tuple[str, Dict[str, int]]:
        orig_tokens = estimate_tokens(text)
        lines = text.splitlines()
        query_words = set(re.findall(r"\w+", query.lower())) if query else set()

        kept_lines = []
        omitted_count = 0

        for line in lines:
            line_lower = line.lower()
            # Always keep critical discoveries and errors
            is_critical = any(w in line_lower for w in ["critical", "error", "fail", "exception", "finding", "blocked"])
            # Keep lines matching query terms
            matches_query = bool(query_words and any(qw in line_lower for qw in query_words if len(qw) > 3))

            # Filter out noisy empty results
            is_noise = any(n in line_lower for n in [
                "0 matches found", "clean, 0 errors", "0% packet loss", "dummy keys",
                "general tips", "standard startup logs", "no critical entries"
            ])

            if (is_critical or matches_query) and not is_noise:
                kept_lines.append(line)
            elif not is_noise and len(kept_lines) < 2:
                # Keep initial context line for grounding
                kept_lines.append(line)
            else:
                omitted_count += 1

        summary_header = f"<!-- [Agent Trace Compiler: {omitted_count} noisy/empty tool steps omitted] -->"
        compiled_text = summary_header + "\n" + "\n".join(kept_lines)
        new_tokens = estimate_tokens(compiled_text)

        return compiled_text, {
            "original_tokens": orig_tokens,
            "optimized_tokens": new_tokens,
            "tokens_avoided": max(0, orig_tokens - new_tokens),
            "omitted_steps": omitted_count,
        }

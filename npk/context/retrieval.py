from __future__ import annotations
from .bm25 import BM25Scorer
"""Query-conditioned context selection and hybrid lexical/dependency retrieval."""

import math
import re
from typing import Any, Dict, List, Set, Tuple

from .analyzer import estimate_tokens
from .graph_slicer import ProgramGraphSlicer
from .info_gain import DEFAULT_STRATEGY, InformationGainSelector


class CodeContextRetriever:
    def __init__(self, selection_strategy: str = DEFAULT_STRATEGY, rel_floor: float = 0.25,
                 enable_escalation: bool = False):
        #: Stopping rule for the seed selector.
        self.selection_strategy = selection_strategy
        self.rel_floor = rel_floor
        #: Optional local embedding fusion; default retrieval never probes it.
        self.enable_escalation = enable_escalation

    def parse_blocks(self, text: str) -> List[Dict[str, Any]]:
        """Extract individual file sections from prompt text."""
        blocks = []
        # Regex matching file headers or markdown code fences
        pattern = re.compile(r"(?:\[File:\s*([^\]]+)\]|```(?:[a-zA-Z0-9_-]+)?\s*(?:#|//)?\s*(?:File:|path:)?\s*([^\n]+)?\n)(.*?)(?=\[File:|```(?:[a-zA-Z0-9_-]+)?\s*(?:#|//)?\s*(?:File:|path:)|$)", re.DOTALL)
        matches = list(pattern.finditer(text))
        if not matches or len(matches) < 2:
            # Try splitting by markdown headers
            sec_pattern = re.compile(r"^(##?\s+.+)$", re.MULTILINE)
            parts = sec_pattern.split(text)
            if len(parts) > 2:
                for i in range(1, len(parts), 2):
                    title = parts[i].strip()
                    content = parts[i+1].strip() if i+1 < len(parts) else ""
                    blocks.append({"name": title, "content": content, "text": f"{title}\n{content}"})
                return blocks
            return [{"name": "main", "content": text, "text": text}]

        for m in matches:
            filename = (m.group(1) or m.group(2) or "unknown").strip()
            filename = re.sub(r"^[:\s]+", "", filename)
            body = m.group(3).strip()
            blocks.append({"name": filename, "content": body, "text": m.group(0)})
        return blocks

    def retrieve_relevant_context(
        self,
        context_text: str,
        query: str,
        max_token_budget: int = 12_000,
        dependency_depth: int = 2,
    ) -> Tuple[str, Dict[str, Any]]:
        if type(max_token_budget) is not int or max_token_budget <= 0:
            raise ValueError('max_token_budget must be a positive integer')
        # Separate attached trailing query if present
        query_suffix = ""
        cleaned_context = context_text
        trailing_match = re.search(r'(\n\n(?:QUESTION|Question|Query):.*?)$', context_text, re.DOTALL)
        if trailing_match:
            query_suffix = trailing_match.group(1)
            cleaned_context = context_text[:trailing_match.start()]

        blocks = self.parse_blocks(cleaned_context)
        if len(blocks) <= 1:
            if estimate_tokens(context_text) > max_token_budget:
                return self._full_fallback(context_text, {}, max_token_budget,
                                           'single block exceeds budget')
            return context_text, {
                "selected_blocks": len(blocks), "dropped_blocks": 0,
                "reason": "single_block", "seed_failed": False,
                "original_tokens": estimate_tokens(context_text),
                "optimized_tokens": estimate_tokens(context_text),
                "fallback_required": False, "budget_exceeded": False,
            }

        slicer = ProgramGraphSlicer()
        edges, _defs = slicer.build_dependency_graph(blocks)
        costs = [max(1, estimate_tokens(b["text"])) for b in blocks]

        selector = InformationGainSelector(
            strategy=self.selection_strategy, rel_floor=self.rel_floor,
            enable_escalation=self.enable_escalation,
        )
        outcome = selector.select(
            blocks=blocks, query=query,
            dependency_edges=edges, token_budget=max_token_budget,
        )

        # INVARIANT: a failed seed stage must never be reported as a valid empty
        # context. Closure_D(emptyset) = emptyset, so expansion cannot recover
        # here -- return the ORIGINAL context and flag the failure so the planner
        # falls back instead of shipping a bare question.
        if outcome.seed_failed or not outcome.kept_indices:
            stats = outcome.as_stats()
            stats.update({
                "total_blocks": len(blocks),
                "selected_blocks": len(blocks),
                "dropped_blocks_count": 0,
                "dropped_blocks": [],
                "original_tokens": estimate_tokens(context_text),
                "optimized_tokens": estimate_tokens(context_text),
                "seed_failed": True,
                "reason": outcome.reason or "seed stage failed; returned original context",
            })
            return self._full_fallback(context_text, stats, max_token_budget, stats['reason'])

        # Budget-aware expansion: prevents expansion from pushing a
        # budget-respecting selection back over budget.
        closure_indices = slicer.compute_transitive_closure(
            set(outcome.kept_indices), edges,
            max_depth=dependency_depth,
            block_costs=costs, token_budget=max_token_budget,
        )
        final_indices = sorted(closure_indices)

        kept_blocks = [blocks[i] for i in final_indices]
        dropped_blocks = [blocks[i]["name"] for i in range(len(blocks)) if i not in final_indices]

        optimized_text = "\n\n".join(b["text"] for b in kept_blocks)
        if query_suffix:
            optimized_text += query_suffix

        # Re-check the actual joined representation, including separators and
        # attached query. Per-block rounding is not additive.
        if estimate_tokens(optimized_text) > max_token_budget:
            return self._full_fallback(context_text, outcome.as_stats(), max_token_budget,
                                       'joined dependency evidence exceeds budget')

        out_stats = outcome.as_stats()
        out_stats.update({
            "total_blocks": len(blocks),
            "selected_blocks": len(kept_blocks),
            "seed_blocks": len(outcome.kept_indices),
            "expanded_blocks": len(kept_blocks) - len(outcome.kept_indices),
            "dropped_blocks_count": len(dropped_blocks),
            "dropped_blocks": dropped_blocks[:10],
            "original_tokens": estimate_tokens(context_text),
            "optimized_tokens": estimate_tokens(optimized_text),
            "dropped_fraction": (len(dropped_blocks) / len(blocks)) if blocks else 0.0,
            "fallback_required": False, "budget_exceeded": False,
        })
        return optimized_text, out_stats

    @staticmethod
    def _full_fallback(context_text, stats, budget, reason):
        """Raw output can exceed budget only as a declared, zero-saving fallback."""
        tokens = estimate_tokens(context_text)
        return context_text, {**stats, 'seed_failed': True, 'fallback_required': True,
                              'budget_exceeded': tokens > budget, 'budget': budget,
                              'original_tokens': tokens, 'optimized_tokens': tokens,
                              'dropped_fraction': 0.0, 'dropped_blocks_count': 0,
                              'dropped_blocks': [], 'tokens_avoided': 0, 'reason': reason}

"""Context structure analysis and workload classification."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set


@dataclass
class CodeSymbolInfo:
    file_path: str = ""
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    language: str = "python"


@dataclass
class ContextAnalysis:
    context_type: str  # code, document, conversation, agent_trace, general
    estimated_tokens: int
    has_repeated_blocks: bool = False
    code_symbols: Dict[str, CodeSymbolInfo] = field(default_factory=dict)
    sections: List[str] = field(default_factory=list)
    is_stable_prefix_candidate: bool = False
    dynamic_suffix_index: int = 0


def estimate_tokens(text: str) -> int:
    """Legacy chars/3.8 estimate; not a bound on a target model's tokenizer."""
    return estimate_tokens_from_length(len(text))


def estimate_tokens_from_length(length: int) -> int:
    """Same estimate without allocating an intermediate joined string."""
    if not length:
        return 0
    return max(1, int(length / 3.8))


class ContextAnalyzer:
    def analyze_messages(self, messages: List[Dict[str, str]]) -> ContextAnalysis:
        full_text = "\n".join(m.get("content", "") for m in messages)
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

        # Check if conversation
        turns = [m for m in messages if m.get("role") in ("user", "assistant")]
        is_convo = len(turns) >= 4

        # Check if code
        code_blocks = re.findall(r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)\n```", full_text, flags=re.DOTALL)
        has_code = len(code_blocks) > 0 or bool(re.search(r"\b(?:def |class |import |function |const |public |private )\b", full_text))

        # Check if agent trace
        has_agent_trace = "tool_calls" in full_text or "observation:" in full_text.lower() or bool(re.search(r"\btool_result\b", full_text))

        if has_agent_trace:
            ctx_type = "agent_trace"
        elif has_code:
            ctx_type = "code"
        elif is_convo:
            ctx_type = "conversation"
        elif len(full_text) > 3000 and ("# " in full_text or "## " in full_text):
            ctx_type = "document"
        else:
            ctx_type = "general"

        symbols: Dict[str, CodeSymbolInfo] = {}
        if has_code:
            symbols = self._extract_symbols(full_text)

        # Find stable prefix split
        stable_idx = 0
        for i, m in enumerate(messages):
            if m.get("role") == "system":
                stable_idx = i + 1
            elif i == 0 and len(m.get("content", "")) > 2000:
                stable_idx = i + 1

        return ContextAnalysis(
            context_type=ctx_type,
            estimated_tokens=total_tokens,
            has_repeated_blocks=self._detect_repetition(full_text),
            code_symbols=symbols,
            sections=re.findall(r"^(?:#|##|###)\s+(.+)$", full_text, flags=re.MULTILINE),
            is_stable_prefix_candidate=stable_idx > 0,
            dynamic_suffix_index=stable_idx,
        )

    def _extract_symbols(self, text: str) -> Dict[str, CodeSymbolInfo]:
        info = CodeSymbolInfo()
        # Python symbols
        info.functions = re.findall(r"\bdef\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text)
        info.classes = re.findall(r"\bclass\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", text)
        info.imports = re.findall(r"^(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", text, flags=re.MULTILINE)
        return {"extracted": info}

    def _detect_repetition(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 30]
        if len(lines) < 4:
            return False
        seen: Set[str] = set()
        duplicates = 0
        for l in lines:
            if l in seen:
                duplicates += 1
            seen.add(l)
        return duplicates >= 2

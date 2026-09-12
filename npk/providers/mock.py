"""Mock provider for offline testing, record/replay, and deterministic benchmarking."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Generator, List, Optional

from .base import BaseProvider, ChatResponse, ProviderCapabilities, UsageInfo


class MockProvider(BaseProvider):
    name = "mock"
    capabilities = ProviderCapabilities(
        explicit_context_cache=True,
        implicit_prompt_cache=True,
        usage_reporting=True,
        streaming=True,
        tool_calling=True,
        structured_output=True,
        max_context_tokens=128_000,
    )

    def __init__(self, response_fn: Optional[Callable[[List[Dict[str, str]]], str]] = None):
        self.response_fn = response_fn or (lambda msgs: f"Mock response to: {msgs[-1].get('content', '')[:30]}")
        self.call_history: List[Dict[str, Any]] = []

    def list_models(self) -> List[str]:
        return ["mock-model-1", "mock-model-2"]

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "mock-model-1",
        max_tokens: Optional[int] = 100,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | Generator[Dict[str, Any], None, None]:
        start = time.perf_counter_ns()
        content = self.response_fn(messages)
        prompt_len = sum(len(m.get("content", "").split()) for m in messages) * 2  # token estimate
        comp_len = len(content.split()) * 2
        usage = UsageInfo(
            prompt_tokens=prompt_len,
            completion_tokens=comp_len,
            total_tokens=prompt_len + comp_len,
            cached_tokens=0,
        )
        latency_ms = (time.perf_counter_ns() - start) / 1e6 + 5.0
        record = {"messages": messages, "model": model, "response": content, "usage": usage}
        self.call_history.append(record)

        if stream:
            def gen():
                words = content.split()
                for w in words:
                    yield {
                        "id": "chatcmpl-mock",
                        "object": "chat.completion.chunk",
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": w + " "}, "finish_reason": None}],
                    }
                yield {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": usage.to_dict()
                }
            return gen()

        return ChatResponse(
            content=content,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            raw={"id": "chatcmpl-mock", "model": model, "choices": [{"message": {"content": content}}]}
        )

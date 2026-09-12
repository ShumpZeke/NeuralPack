"""Base provider abstraction for closed and open model gateways."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional


@dataclass(frozen=True)
class ProviderCapabilities:
    explicit_context_cache: bool = False
    implicit_prompt_cache: bool = True
    usage_reporting: bool = True
    streaming: bool = True
    tool_calling: bool = True
    structured_output: bool = True
    max_context_tokens: int = 128_000


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass
class ChatResponse:
    content: str
    model: str
    usage: UsageInfo = field(default_factory=UsageInfo)
    latency_ms: float = 0.0
    ttft_ms: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_openai_dict(self) -> Dict[str, Any]:
        return {
            "id": self.raw.get("id", "chatcmpl-npk"),
            "object": "chat.completion",
            "created": self.raw.get("created", 0),
            "model": self.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": self.content},
                "finish_reason": "stop"
            }],
            "usage": self.usage.to_dict()
        }


class BaseProvider(ABC):
    name: str = "base"
    capabilities: ProviderCapabilities = ProviderCapabilities()

    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | Generator[Dict[str, Any], None, None]:
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        pass

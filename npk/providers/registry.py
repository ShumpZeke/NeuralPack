"""Provider registry and automatic resolver."""
from __future__ import annotations

import os
from typing import Optional

from .base import BaseProvider
from .openai import OpenAIProvider
from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .nvidia import NvidiaNIMProvider
from .openai_compatible import OpenAICompatibleProvider
from .mock import MockProvider


def get_provider(
    provider_name: str = "auto",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> BaseProvider:
    """
    Resolve and instantiate the appropriate provider adapter.
    """
    name = provider_name.lower().strip()
    m = (model or "").lower()

    if name == "mock":
        return MockProvider()
    elif name in ("openai", "oai"):
        return OpenAIProvider(api_key=api_key, default_model=model or "gpt-4o-mini")
    elif name in ("anthropic", "claude"):
        return AnthropicProvider(api_key=api_key, default_model=model or "claude-3-5-sonnet-20241022")
    elif name in ("gemini", "google"):
        return GeminiProvider(api_key=api_key, default_model=model or "gemini-1.5-flash")
    elif name in ("nvidia", "nvidia_nim"):
        return NvidiaNIMProvider(api_key=api_key, default_model=model or "meta/llama-3.2-11b-vision-instruct")
    elif name in ("compatible", "openai_compatible", "vllm", "ollama", "openrouter"):
        return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, default_model=model or "default")

    # Automatic detection based on model name or available environment keys
    if "claude" in m:
        return AnthropicProvider(api_key=api_key, default_model=model or "claude-3-5-sonnet-20241022")
    elif any(k in m for k in ("gpt-", "o1", "o3", "text-embedding")):
        return OpenAIProvider(api_key=api_key, default_model=model or "gpt-4o-mini")
    elif "gemini" in m:
        return GeminiProvider(api_key=api_key, default_model=model or "gemini-1.5-flash")
    elif any(k in m for k in ("meta/", "deepseek", "nvidia/")):
        return NvidiaNIMProvider(api_key=api_key, default_model=model or "meta/llama-3.2-11b-vision-instruct")

    # Auto-detect by configured environment variable
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIProvider(default_model=model or "gpt-4o-mini")
    elif os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicProvider(default_model=model or "claude-3-5-sonnet-20241022")
    elif os.environ.get("NVIDIA_API_KEY"):
        return NvidiaNIMProvider(default_model=model or "meta/llama-3.2-11b-vision-instruct")
    elif os.environ.get("GEMINI_API_KEY"):
        return GeminiProvider(default_model=model or "gemini-1.5-flash")

    # Fallback to local / mock
    return OpenAICompatibleProvider(base_url=base_url, default_model=model or "default")

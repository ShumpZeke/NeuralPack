"""Google Gemini provider adapter via OpenAI-compatible endpoints."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .openai import OpenAIProvider
from .base import ChatResponse, ProviderCapabilities


class GeminiProvider(OpenAIProvider):
    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    capabilities = ProviderCapabilities(
        explicit_context_cache=True,
        implicit_prompt_cache=True,
        usage_reporting=True,
        streaming=True,
        tool_calling=True,
        structured_output=True,
        max_context_tokens=1_000_000,
    )

    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-1.5-flash"):
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            env_path = Path(".env")
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
        super().__init__(api_key=key, default_model=default_model)

    def list_models(self) -> List[str]:
        return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]

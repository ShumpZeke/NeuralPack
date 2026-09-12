"""Universal OpenAI-compatible provider adapter (Ollama, vLLM, OpenRouter, Together, etc.)."""
from __future__ import annotations

import os
from typing import Optional

from .openai import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: str = "default",
    ):
        super().__init__(api_key=api_key or os.environ.get("OPENAI_COMPATIBLE_API_KEY", "local-key"), default_model=default_model)
        self.base_url = (base_url or os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000/v1")).rstrip("/")

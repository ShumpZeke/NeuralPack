"""OpenAI provider adapter with native prompt caching and usage tracking."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional

from .base import BaseProvider, ChatResponse, ProviderCapabilities, UsageInfo
from ..telemetry import redact_secrets


def _load_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if not key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{env_name}="):
                    key = line.split("=", 1)[1].strip()
                    break
    return key


class OpenAIProvider(BaseProvider):
    name = "openai"
    base_url = "https://api.openai.com/v1"
    capabilities = ProviderCapabilities(
        explicit_context_cache=False,
        implicit_prompt_cache=True,
        usage_reporting=True,
        streaming=True,
        tool_calling=True,
        structured_output=True,
        max_context_tokens=128_000,
    )

    def __init__(self, api_key: Optional[str] = None, default_model: str = "gpt-4o-mini"):
        self._api_key = api_key or _load_key("OPENAI_API_KEY")
        self.default_model = default_model

    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY not configured.")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def list_models(self) -> List[str]:
        req = urllib.request.Request(f"{self.base_url}/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            raise RuntimeError(f"Failed to list OpenAI models: {redact_secrets(str(e))}") from None

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = 512,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | Generator[Dict[str, Any], None, None]:
        target_model = model or self.default_model
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        for k in ("top_p", "stop", "presence_penalty", "frequency_penalty", "tools", "tool_choice"):
            if k in kwargs:
                payload[k] = kwargs[k]

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=self._headers())
        start = time.perf_counter_ns()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI API error ({e.code}): {redact_secrets(err_body)}") from None
        except Exception as e:
            raise RuntimeError(f"OpenAI connection error: {redact_secrets(str(e))}") from None

        latency_ms = (time.perf_counter_ns() - start) / 1e6
        content = ""
        if "choices" in raw and len(raw["choices"]) > 0:
            content = raw["choices"][0].get("message", {}).get("content", "") or ""
        raw_usage = raw.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            total_tokens=raw_usage.get("total_tokens", 0),
            cached_tokens=(raw_usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        )
        return ChatResponse(
            content=content,
            model=target_model,
            usage=usage,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            raw=raw,
        )

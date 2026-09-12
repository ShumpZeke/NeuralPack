"""Anthropic provider adapter with explicit ephemeral prompt cache control."""
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


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    base_url = "https://api.anthropic.com/v1"
    capabilities = ProviderCapabilities(
        explicit_context_cache=True,
        implicit_prompt_cache=True,
        usage_reporting=True,
        streaming=True,
        tool_calling=True,
        structured_output=False,
        max_context_tokens=200_000,
    )

    def __init__(self, api_key: Optional[str] = None, default_model: str = "claude-3-5-sonnet-20241022"):
        self._api_key = api_key or _load_key("ANTHROPIC_API_KEY")
        self.default_model = default_model

    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured.")
        return {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "Content-Type": "application/json",
        }

    def list_models(self) -> List[str]:
        return ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = 1024,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | Generator[Dict[str, Any], None, None]:
        target_model = model or self.default_model
        # Extract system prompt
        system_content = ""
        anthropic_msgs = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_content += content + "\n"
            else:
                anthropic_msgs.append({"role": role, "content": content})

        # Ephemeral prompt caching on large system or context turns
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
        }
        if system_content.strip():
            # Enable prompt caching on system prompt if > 1024 tokens
            if len(system_content) > 3000:
                payload["system"] = [
                    {"type": "text", "text": system_content.strip(), "cache_control": {"type": "ephemeral"}}
                ]
            else:
                payload["system"] = system_content.strip()

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/messages", data=body, headers=self._headers())
        start = time.perf_counter_ns()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Anthropic API error ({e.code}): {redact_secrets(err_body)}") from None
        except Exception as e:
            raise RuntimeError(f"Anthropic connection error: {redact_secrets(str(e))}") from None

        latency_ms = (time.perf_counter_ns() - start) / 1e6
        content = ""
        for block in raw.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        raw_usage = raw.get("usage", {})
        input_tok = raw_usage.get("input_tokens", 0)
        cached_read = raw_usage.get("cache_read_input_tokens", 0)
        output_tok = raw_usage.get("output_tokens", 0)

        usage = UsageInfo(
            prompt_tokens=input_tok + cached_read,
            completion_tokens=output_tok,
            total_tokens=input_tok + cached_read + output_tok,
            cached_tokens=cached_read,
        )
        return ChatResponse(
            content=content,
            model=target_model,
            usage=usage,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            raw=raw,
        )

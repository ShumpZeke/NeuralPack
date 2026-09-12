"""NVIDIA NIM provider adapter with secure credential management and usage tracking."""
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


def _load_env_key() -> str:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("NVIDIA_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    return key


class NvidiaNIMProvider(BaseProvider):
    name = "nvidia_nim"
    base_url = "https://integrate.api.nvidia.com/v1"
    capabilities = ProviderCapabilities(
        explicit_context_cache=False,
        implicit_prompt_cache=True,
        usage_reporting=True,
        streaming=True,
        tool_calling=True,
        structured_output=True,
        max_context_tokens=128_000,
    )

    def __init__(self, api_key: Optional[str] = None, default_model: str = "meta/llama-3.2-11b-vision-instruct"):
        self._api_key = api_key or _load_env_key()
        if not self._api_key:
            raise ValueError("NVIDIA_API_KEY not found in environment or .env file.")
        self.default_model = default_model

    def _headers(self) -> Dict[str, str]:
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
            raise RuntimeError(f"Failed to list NVIDIA models: {redact_secrets(str(e))}") from None

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
        for k in ("top_p", "stop", "presence_penalty", "frequency_penalty"):
            if k in kwargs:
                payload[k] = kwargs[k]
        if stream:
            payload["stream"] = True
            return self._stream_request(payload, target_model)
        else:
            return self._sync_request(payload, target_model)

    def _sync_request(self, payload: Dict[str, Any], model: str) -> ChatResponse:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=self._headers())
        start = time.perf_counter_ns()
        raw = None
        last_err = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                last_err = RuntimeError(f"NVIDIA NIM API error ({e.code}): {redact_secrets(err_body)}")
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 ** attempt)
                    continue
                raise last_err from None
            except Exception as e:
                last_err = RuntimeError(f"NVIDIA NIM connection error: {redact_secrets(str(e))}")
                time.sleep(1.5 ** attempt)
                continue
        if raw is None:
            raise last_err or RuntimeError("Failed to query NVIDIA NIM after 3 attempts")

        latency_ms = (time.perf_counter_ns() - start) / 1e6
        content = ""
        if "choices" in raw and len(raw["choices"]) > 0:
            msg = raw["choices"][0].get("message", {})
        content = msg.get("content") or msg.get("reasoning_content") or ""
        raw_usage = raw.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            total_tokens=raw_usage.get("total_tokens", 0),
            cached_tokens=(raw_usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        )
        return ChatResponse(
            content=content,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            raw=raw,
        )

    def _stream_request(self, payload: Dict[str, Any], model: str) -> Generator[Dict[str, Any], None, None]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=self._headers())
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"NVIDIA NIM stream error ({e.code}): {redact_secrets(err_body)}") from None
        except Exception as e:
            raise RuntimeError(f"NVIDIA NIM stream error: {redact_secrets(str(e))}") from None

        with resp:
            for line in resp:
                line_str = line.decode("utf-8", errors="ignore").strip()
                if not line_str or line_str.startswith(":"):
                    continue
                if line_str.startswith("data: "):
                    data_str = line_str[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        yield chunk
                    except Exception:
                        continue


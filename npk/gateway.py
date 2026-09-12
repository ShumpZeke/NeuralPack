"""OpenAI-compatible HTTP Gateway & Reverse Proxy for NeuralPack."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
from typing import Any, Dict, Optional
import urllib.parse

from .runtime import NeuralPackClient
from .providers.base import ChatResponse


class GatewayRequestHandler(BaseHTTPRequestHandler):
    client: NeuralPackClient

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/v1/models", "/models"):
            self._handle_models()
        elif parsed.path in ("/", "/health"):
            self._send_json(200, {"status": "ok", "service": "neuralpack-gateway", "mode": self.client.mode})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/v1/chat/completions", "/chat/completions"):
            self._handle_chat_completions()
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def _handle_models(self):
        try:
            models = self.client.provider.list_models()
            res = {
                "object": "list",
                "data": [{"id": m, "object": "model", "created": 0, "owned_by": "neuralpack"} for m in models]
            }
            self._send_json(200, res)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_chat_completions(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self._send_json(400, {"error": "Empty request body"})
            return

        try:
            body = json.loads(self.rfile.read(content_len).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})
            return

        messages = body.get("messages", [])
        model = body.get("model", self.client.default_model)
        max_tokens = body.get("max_tokens", 512)
        temperature = body.get("temperature", 0.7)
        stream = body.get("stream", False)
        mode_override = self.headers.get("X-NeuralPack-Mode")

        try:
            res = self.client.chat_completion(
                messages=messages, model=model, max_tokens=max_tokens,
                temperature=temperature, stream=stream, mode_override=mode_override
            )
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for chunk in res:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                if isinstance(res, ChatResponse):
                    self._send_json(200, res.to_openai_dict())
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status: int, data: Dict[str, Any]):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_gateway(
    host: str = "127.0.0.1",
    port: int = 8000,
    provider: str = "auto",
    mode: str = "optimized",
    default_model: str = "gpt-4o-mini",
) -> ThreadingHTTPServer:
    client = NeuralPackClient(provider=provider, mode=mode, default_model=default_model)
    handler = GatewayRequestHandler
    handler.client = client
    server = ThreadingHTTPServer((host, port), handler)
    return server

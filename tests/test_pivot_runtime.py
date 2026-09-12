"""Unit and integration tests for the NeuralPack context optimization layer."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path
import pytest

from npk.context.analyzer import ContextAnalyzer, estimate_tokens
from npk.context.retrieval import CodeContextRetriever
from npk.context.compressor import ExtractiveCompressor
from npk.cost import calculate_savings, estimate_cost, get_pricing
from npk.planner import ContextExecutionPlanner
from npk.providers.mock import MockProvider
from npk.runtime import NeuralPackClient
from npk.gateway import run_gateway
from npk.telemetry import TraceLogger, TraceRecord, analyze_traces


def test_context_analyzer():
    analyzer = ContextAnalyzer()
    # Code detection
    msgs = [{"role": "user", "content": "def authenticate(user, password):\n    return True\n"}]
    res = analyzer.analyze_messages(msgs)
    assert res.context_type == "code"
    assert "authenticate" in res.code_symbols["extracted"].functions

    # Document detection
    doc_text = "# Architecture Overview\n\n" + "Some details\n\n" * 300
    res_doc = analyzer.analyze_messages([{"role": "user", "content": doc_text}])
    assert res_doc.context_type == "document"
    assert len(res_doc.sections) > 0


def test_code_retriever():
    retriever = CodeContextRetriever()
    context = """
```File: auth.py
def authenticate(token):
    valid = verify_token(token)
    return valid
```

```File: utils.py
def verify_token(t):
    return t == "valid"
```

```File: graphics.py
def render_cube():
    return "cube"
```
"""
    # Query about authentication should keep auth.py and expanded dependency utils.py, but drop graphics.py
    optimized, stats = retriever.retrieve_relevant_context(context, "How does authenticate handle token?")
    assert "auth.py" in optimized
    assert "utils.py" in optimized
    assert "graphics.py" in stats.get("dropped_blocks", [])
    assert stats["dropped_blocks_count"] >= 1


def test_cost_calculation():
    model = "gpt-4o-mini"
    orig_c, opt_c, saved, pct = calculate_savings(model, original_input_tokens=10000, optimized_input_tokens=2000, output_tokens=100, provider="openai")
    assert orig_c > opt_c
    assert saved > 0
    assert pct > 50.0


def test_execution_planner():
    planner = ContextExecutionPlanner()
    code_content = """
```File: database.py
def connect_db():
    return 'connected'
```

```File: unused.py
def helper():
    return 42
```
""" * 20
    messages = [
        {"role": "system", "content": "You are a code assistant."},
        {"role": "user", "content": code_content},
        {"role": "user", "content": "Explain how connect_db works."} 
    ]
    opt_msgs, plan = planner.plan_and_optimize(messages)
    assert len(plan.strategies) > 0
    assert plan.tokens_avoided > 0
    assert plan.estimated_savings is None  # no provider identified; no invented quote
    assert len(plan.explanation) > 0


def test_client_modes(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    client = NeuralPackClient(provider="mock", mode="optimized", trace_path=str(trace_file))
    msgs = [{"role": "user", "content": "Hello world!"}]

    # 1. Optimized mode
    res_opt = client.chat_completion(msgs, mode_override="optimized")
    assert res_opt.content
    assert "neuralpack_plan" in res_opt.raw

    # 2. Baseline mode
    res_base = client.chat_completion(msgs, mode_override="baseline")
    assert res_base.content

    # 3. Shadow mode
    res_shadow = client.chat_completion(msgs, mode_override="shadow")
    assert res_shadow.content

    # Analyze traces
    summary = analyze_traces(trace_file)
    assert summary["requests"] == 3


def test_gateway_server(tmp_path):
    trace_file = tmp_path / "gw_traces.jsonl"
    server = run_gateway(host="127.0.0.1", port=9876, provider="mock", mode="optimized")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)

    try:
        # Test health
        req = urllib.request.Request("http://127.0.0.1:9876/health")
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
            assert data["status"] == "ok"

        # Test models
        req_models = urllib.request.Request("http://127.0.0.1:9876/v1/models")
        with urllib.request.urlopen(req_models) as r:
            data = json.loads(r.read())
            assert len(data["data"]) > 0

        # Test chat completions
        payload = json.dumps({
            "model": "mock-model-1",
            "messages": [{"role": "user", "content": "Tell me a joke."}]
        }).encode("utf-8")
        req_chat = urllib.request.Request(
            "http://127.0.0.1:9876/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_chat) as r:
            data = json.loads(r.read())
            assert "choices" in data
            assert "content" in data["choices"][0]["message"]
    finally:
        server.shutdown()
        server.server_close()

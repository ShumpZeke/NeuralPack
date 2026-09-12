"""Unit and integration tests for holdout dataset, MSC ablation, and audit tooling."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from benchmarks.holdout_v1 import generate_50_holdout_tasks
from npk.context.trace_compiler import ToolTraceCompiler
from npk.context.convo_compiler import ConversationCompiler
from npk.auditor import audit_run


def test_holdout_task_generation():
    tasks = generate_50_holdout_tasks()
    assert len(tasks) == 50
    domains = {t.domain for t in tasks}
    assert domains == {"code", "doc", "convo", "trace", "adversarial"}
    for t in tasks:
        assert t.id
        assert t.query
        assert t.expected_fact
        assert len(t.required_blocks) > 0


def test_tool_trace_compiler():
    tc = ToolTraceCompiler()
    trace = """
[Step 1] Tool Call: ls("src/") -> Result: ["a.py", "b.py"]
[Step 2] Tool Call: grep("needle", "src/") -> Result: 0 matches found.
[Step 3] Tool Call: run_tests() -> Clean, 0 errors.
[Step 4] Tool Call: inspect_db() -> CRITICAL FINDING: Port 5432 is blocked by sg-99999.
[Step 5] Tool Call: ping("host") -> 0% packet loss.
"""
    compiled, stats = tc.compile_trace(trace, query="What was the firewall finding?")
    assert stats["tokens_avoided"] > 0
    assert "sg-99999" in compiled
    assert "0% packet loss" not in compiled


def test_convo_compiler():
    cc = ConversationCompiler()
    dialogue = """
User: Set port to 3000.
Assistant: Port set to 3000.
User: Scratch that, disregard port 3000, we MUST use port 8080 now.
Assistant: Port updated to 8080.
User: What is the final port?
"""
    compiled, stats = cc.compile_conversation(dialogue)
    assert stats["tokens_avoided"] > 0
    assert "8080" in compiled


def test_audit_run_verifies_artifacts(tmp_path):
    run_dir = tmp_path / "test_run"
    run_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps({"model": "meta/llama-3.2-11b-vision-instruct"}))
    (run_dir / "inputs.jsonl").write_text(json.dumps({"id": "t1", "expected_fact": "42"}) + "\n")
    (run_dir / "baseline_outputs.jsonl").write_text(json.dumps({"id": "t1", "content": "The answer is 42."}) + "\n")
    (run_dir / "optimized_outputs.jsonl").write_text(json.dumps({"id": "t1", "content": "The answer is 42."}) + "\n")
    (run_dir / "usage.jsonl").write_text(
        json.dumps({"id": "t1", "mode": "baseline", "prompt_tokens": 1000, "completion_tokens": 20}) + "\n" +
        json.dumps({"id": "t1", "mode": "optimized", "prompt_tokens": 300, "completion_tokens": 20}) + "\n"
    )
    res = audit_run(run_dir)
    assert res["artifact_consistency_checked"] is True
    assert res["audited_tokens_avoided"] == 700
    assert res["audited_reduction_percentage"] == 70.0
    assert res["audited_baseline_fixture_pass_pct"] == 100.0
    assert res["audited_optimized_fixture_pass_pct"] == 100.0
    assert res["audited_baseline_cost_usd"] is None

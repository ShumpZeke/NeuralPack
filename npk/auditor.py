"""Recompute declared substring-fixture results from consistent, identified logs.

This is a log consistency checker, not independent answer validation. It cannot
establish that outputs came from a model, token counts came from billing, or a
substring match is a correct answer. No dollar amounts are inferred from these
artifacts. Use the prospective benchmark's raw provider responses and executable
oracles for answer-quality experiments.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field in audit artifacts")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("Non-finite JSON constant in audit artifacts")


def _json(text):
    result = json.loads(text, object_pairs_hook=_object, parse_constant=_nonfinite)
    if not isinstance(result, dict):
        raise ValueError("Audit records must be JSON objects")
    return result


def _rows(path):
    return [_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _by_id(rows):
    indexed = {}
    for row in rows:
        key = row.get("id")
        if not isinstance(key, str) or not key.strip() or key in indexed:
            raise ValueError("Each artifact needs unique, non-empty task IDs")
        indexed[key] = row
    return indexed


def _require_usage(row):
    for field in ("prompt_tokens", "completion_tokens", "cached_tokens"):
        value = row.get(field, 0 if field == "cached_tokens" else None)
        if type(value) is not int or value < 0:
            raise ValueError("Usage counts must be non-negative integers; prompt and completion counts are required")
    if row.get("cached_tokens", 0) > row["prompt_tokens"]:
        raise ValueError("Cached tokens exceed prompt tokens")


def _retention(optimized, baseline):
    return round(optimized / baseline * 100, 2) if baseline else None


def audit_run(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"Experiment run directory not found: {path}")
    config = _json((path / "config.json").read_text(encoding="utf-8"))
    provider = config.get("provider")
    mode = config.get("evidence_mode", "MOCK" if provider == "mock" else "UNKNOWN")
    if not isinstance(mode, str) or mode not in {"LIVE", "LOCAL", "MOCK", "REPLAY", "UNKNOWN"}:
        raise ValueError("Unsupported declared evidence mode")
    if provider == "mock" and mode != "MOCK":
        raise ValueError("Mock provider cannot declare another evidence mode")
    inputs = _by_id(_rows(path / "inputs.jsonl"))
    if not inputs:
        raise ValueError("Cannot audit a run with no tasks")
    outputs = {arm: _by_id(_rows(path / f"{arm}_outputs.jsonl"))
               for arm in ("baseline", "optimized")}
    records = _rows(path / "usage.jsonl")
    if any(not isinstance(row.get("mode"), str) or row["mode"] not in outputs for row in records):
        raise ValueError("Usage must identify baseline or optimized mode")
    usage = {arm: _by_id([row for row in records if row["mode"] == arm]) for arm in outputs}
    for arm in outputs:
        if outputs[arm].keys() != inputs.keys() or usage[arm].keys() != inputs.keys():
            raise ValueError("Input, output and usage task IDs do not match")
        for row in usage[arm].values():
            _require_usage(row)

    passes = {arm: 0 for arm in outputs}
    task_audits = []
    for key, task in inputs.items():
        expected, forbidden = task.get("expected_fact"), task.get("forbidden_fact", "")
        if not isinstance(expected, str) or not expected.strip() or not isinstance(forbidden, str):
            raise ValueError("A non-empty expected fixture and string forbidden fixture are required")
        expected, forbidden = expected.lower(), forbidden.lower()
        outcomes = {}
        for arm in outputs:
            content = outputs[arm][key].get("content")
            if not isinstance(content, str):
                raise ValueError("Output content must be a string")
            text = content.lower()
            outcomes[arm] = expected in text and (not forbidden or forbidden not in text)
            passes[arm] += int(outcomes[arm])
        task_audits.append({"task_id": key, "expected": expected,
                            "baseline_pass": outcomes["baseline"], "optimized_pass": outcomes["optimized"],
                            "base_prompt_tokens": usage["baseline"][key]["prompt_tokens"],
                            "opt_prompt_tokens": usage["optimized"][key]["prompt_tokens"]})
    totals = {arm: sum(row["prompt_tokens"] for row in usage[arm].values()) for arm in outputs}
    avoided = totals["baseline"] - totals["optimized"]
    discrepancies = []
    summary_file = path / "summary.json"
    if summary_file.exists():
        stored = _json(summary_file.read_text(encoding="utf-8"))
        for field in ("total_tokens_avoided_by_neuralpack", "total_tokens_avoided"):
            if field in stored and stored[field] is not None and stored[field] != avoided:
                discrepancies.append(f"{field} disagrees with audited token difference")
    return {
        "audit_schema_version": 2,
        "run_id": path.name, "model": config.get("model"), "provider": provider,
        "evidence_mode": mode, "evidence_mode_basis": "declared; execution not authenticated",
        "tasks_audited": len(inputs), "artifact_consistency_checked": True,
        "grading_method": "case-insensitive expected substring, excluding forbidden substring",
        "metric_limitation": "Fixture matching does not establish answer correctness or sufficiency",
        "usage_basis": "reported counts; not independently measured or billing-verified",
        "audited_baseline_tokens": totals["baseline"], "audited_optimized_tokens": totals["optimized"],
        "audited_tokens_avoided": avoided,
        "audited_reduction_percentage": _retention(avoided, totals["baseline"]),
        "audited_baseline_fixture_pass_pct": round(passes["baseline"] / len(inputs) * 100, 2),
        "audited_optimized_fixture_pass_pct": round(passes["optimized"] / len(inputs) * 100, 2),
        "audited_fixture_retention_pct": _retention(passes["optimized"], passes["baseline"]),
        "audited_baseline_cost_usd": None, "audited_optimized_cost_usd": None,
        "audited_cost_saved_usd": None, "audited_cost_saved_percentage": None,
        "cost_status": "N/A: this artifact schema does not establish billing provenance or verified rates",
        "summary_discrepancies": discrepancies, "task_audits": task_audits,
    }

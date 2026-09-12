"""The public audit command must not turn incomplete logs into success claims."""
import json

import pytest

from npk.auditor import audit_run


def write_run(root, *, baseline="wrong", optimized="wrong", provider="mock"):
    documents = {
        "config.json": {"model": "unpriced-example", "provider": provider},
        "inputs.jsonl": [{"id": "one", "expected_fact": "correct", "forbidden_fact": "forbidden"}],
        "baseline_outputs.jsonl": [{"id": "one", "content": baseline}],
        "optimized_outputs.jsonl": [{"id": "one", "content": optimized}],
        "usage.jsonl": [
            {"id": "one", "mode": mode, "prompt_tokens": tokens, "completion_tokens": 2}
            for mode, tokens in (("baseline", 100), ("optimized", 150))
        ],
    }
    persist(root, documents)
    return documents


def persist(root, documents):
    for name, value in documents.items():
        text = "\n".join(json.dumps(row) for row in value) if name.endswith("jsonl") else json.dumps(value)
        (root / name).write_text(text, encoding="utf-8")


@pytest.mark.parametrize("optimized", ["wrong", "correct"])
def test_zero_baseline_cannot_report_full_retention(tmp_path, optimized):
    write_run(tmp_path, optimized=optimized)
    result = audit_run(tmp_path)
    assert result.get("audited_fixture_retention_pct") is None
    assert not any("quality" in key or "accuracy" in key for key in result)
    assert result["audited_baseline_fixture_pass_pct"] == 0
    assert result["evidence_mode"] == "MOCK"
    assert result["audited_baseline_cost_usd"] is None
    assert result["audited_cost_saved_usd"] is None
    assert result["audited_tokens_avoided"] == -50
    assert result["audited_reduction_percentage"] == -50


def test_audit_joins_ids_instead_of_relying_on_row_order(tmp_path):
    documents = write_run(tmp_path, baseline="correct", optimized="correct")
    documents["inputs.jsonl"].append({"id": "two", "expected_fact": "other", "forbidden_fact": "forbidden"})
    for name in ("baseline_outputs.jsonl", "optimized_outputs.jsonl"):
        documents[name].insert(0, {"id": "two", "content": "other forbidden"})
    documents["usage.jsonl"] += [
        {"id": "two", "mode": mode, "prompt_tokens": tokens, "completion_tokens": 1}
        for mode, tokens in (("baseline", 10), ("optimized", 20))
    ]
    documents["usage.jsonl"].reverse()
    persist(tmp_path, documents)
    result = audit_run(tmp_path)
    assert result["audited_baseline_fixture_pass_pct"] == 50
    assert result["audited_fixture_retention_pct"] == 100
    assert result["task_audits"][0]["base_prompt_tokens"] == 100
    assert result["task_audits"][1]["baseline_pass"] is False
    assert result["artifact_consistency_checked"] is True


@pytest.mark.parametrize("attack", [
    "no_tasks", "missing_expected", "blank_expected", "missing_output_id",
    "wrong_output_id", "duplicate_output_id", "missing_usage", "duplicate_usage",
    "unknown_usage_mode", "missing_token_count", "negative_tokens", "boolean_tokens",
    "fractional_tokens", "cache_exceeds_prompt", "null_content", "unknown_evidence_mode",
    "mock_as_live", "structured_evidence_mode", "structured_usage_mode",
])
def test_incomplete_or_ambiguous_evidence_is_rejected(tmp_path, attack):
    d = write_run(tmp_path, baseline="correct", optimized="correct")
    if attack == "no_tasks":
        for name in d:
            if name.endswith("jsonl"):
                d[name] = []
    elif attack == "missing_expected": del d["inputs.jsonl"][0]["expected_fact"]
    elif attack == "blank_expected": d["inputs.jsonl"][0]["expected_fact"] = " "
    elif attack == "missing_output_id": del d["baseline_outputs.jsonl"][0]["id"]
    elif attack == "wrong_output_id": d["baseline_outputs.jsonl"][0]["id"] = "missing"
    elif attack == "duplicate_output_id": d["baseline_outputs.jsonl"] *= 2
    elif attack == "missing_usage": d["usage.jsonl"].pop()
    elif attack == "duplicate_usage": d["usage.jsonl"].append(d["usage.jsonl"][0])
    elif attack == "unknown_usage_mode": d["usage.jsonl"][0]["mode"] = "typo"
    elif attack == "missing_token_count": del d["usage.jsonl"][0]["prompt_tokens"]
    elif attack == "negative_tokens": d["usage.jsonl"][0]["prompt_tokens"] = -1
    elif attack == "boolean_tokens": d["usage.jsonl"][0]["prompt_tokens"] = True
    elif attack == "fractional_tokens": d["usage.jsonl"][0]["prompt_tokens"] = 1.5
    elif attack == "cache_exceeds_prompt": d["usage.jsonl"][0]["cached_tokens"] = 101
    elif attack == "null_content": d["baseline_outputs.jsonl"][0]["content"] = None
    elif attack == "unknown_evidence_mode": d["config.json"]["evidence_mode"] = "LIVEISH"
    elif attack == "mock_as_live": d["config.json"]["evidence_mode"] = "LIVE"
    elif attack == "structured_evidence_mode": d["config.json"]["evidence_mode"] = []
    elif attack == "structured_usage_mode": d["usage.jsonl"][0]["mode"] = []
    persist(tmp_path, d)
    rejected = False
    try:
        audit_run(tmp_path)
    except ValueError:
        rejected = True
    assert rejected, f"audit accepted {attack}"


def test_provider_name_does_not_prove_live_execution_and_zero_summary_is_checked(tmp_path):
    d = write_run(tmp_path, provider="nvidia_nim")
    d["summary.json"] = {"total_tokens_avoided_by_neuralpack": 0}
    persist(tmp_path, d)
    result = audit_run(tmp_path)
    assert result["evidence_mode"] == "UNKNOWN"
    assert len(result["summary_discrepancies"]) == 1
    d["config.json"]["evidence_mode"] = "REPLAY"
    persist(tmp_path, d)
    assert audit_run(tmp_path)["evidence_mode"] == "REPLAY"


@pytest.mark.parametrize("raw", ['{"model":"a","model":"b"}', '{"model":NaN}'])
def test_noncanonical_json_cannot_override_evidence(tmp_path, raw):
    write_run(tmp_path)
    (tmp_path / "config.json").write_text(raw)
    with pytest.raises(ValueError):
        audit_run(tmp_path)

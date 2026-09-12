"""Telemetry, auditable trace logging, secret redaction, and offline log analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

SECRET_PATTERNS = [
    (re.compile(r"nvapi-[A-Za-z0-9_\-]{30,}"), "[REDACTED_NVIDIA_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
]


def redact_secrets(val: Any) -> Any:
    """Recursively mask secrets in strings, dicts, and lists."""
    if isinstance(val, str):
        result = val
        for pattern, replacement in SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
    elif isinstance(val, dict):
        res = {}
        for k, v in val.items():
            if any(x in k.lower() for x in ["api_key", "secret", "access_token", "auth_token", "password", "credential"]):
                res[k] = "[REDACTED]"
            else:
                res[k] = redact_secrets(v)
        return res
    elif isinstance(val, list):
        return [redact_secrets(v) for v in val]
    return val


@dataclass
class TraceRecord:
    request_id: str
    timestamp_utc: str
    provider: str
    model: str
    mode: str
    original_tokens: int
    optimized_tokens: int
    tokens_avoided: int
    original_cost_est: Optional[float]
    optimized_cost_est: Optional[float]
    cost_saved_est: Optional[float]
    latency_ms: float
    ttft_ms: Optional[float]
    plan_strategy: List[str]
    plan_details: Dict[str, Any] = field(default_factory=dict)
    quality_status: str = "unverified"
    trace_schema_version: int = 2
    token_basis: str = "unspecified"
    evidence_mode: str = "UNKNOWN"
    reported_usage: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return redact_secrets(asdict(self))


class TraceLogger:
    def __init__(self, trace_path: Path | str = "experiments/traces.jsonl"):
        self.path = Path(trace_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: TraceRecord) -> None:
        data = record.to_dict()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")


def analyze_traces(trace_path: Path | str) -> Dict[str, Any]:
    """Group consistent v2 token observations; never total historical cost claims."""
    from .auditor import _json
    path = Path(trace_path)
    if not path.exists():
        return {"error": f"File {path} does not exist", "requests": 0}
    records = [_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = {}; legacy = 0; seen = set(); strategies = {}
    for row in records:
        key = row.get("request_id")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("Trace IDs must be present and unique")
        seen.add(key)
        if row.get("trace_schema_version") != 2:
            legacy += 1
            continue
        basis = row.get("token_basis"); mode = row.get("mode"); evidence = row.get("evidence_mode")
        if basis not in ("planner_chars_div3_8_estimate", "provider_adapter_reported"):
            raise ValueError("Unknown trace token basis")
        if mode not in ("baseline", "optimized", "shadow") or evidence not in ("LIVE", "MOCK", "LOCAL", "REPLAY", "UNKNOWN"):
            raise ValueError("Unknown trace mode")
        original, optimized, avoided = (row.get(k) for k in ("original_tokens", "optimized_tokens", "tokens_avoided"))
        if any(type(n) is not int for n in (original, optimized, avoided)) or min(original, optimized) < 0:
            raise ValueError("Invalid token counts in trace")
        if avoided != original-optimized or (mode != "optimized" and avoided != 0):
            raise ValueError("Trace token difference disagrees with executed mode")
        g = groups.setdefault((basis, mode, evidence), {"requests": 0, "original_tokens": 0, "optimized_tokens": 0, "tokens_avoided": 0})
        g["requests"] += 1; g["original_tokens"] += original; g["optimized_tokens"] += optimized; g["tokens_avoided"] += avoided
        for strategy in row.get("plan_strategy", []): strategies[strategy] = strategies.get(strategy, 0)+1
    comparable = bool(groups) and not legacy and len({key[0] for key in groups}) == 1
    original = sum(g["original_tokens"] for g in groups.values()) if comparable else None
    optimized = sum(g["optimized_tokens"] for g in groups.values()) if comparable else None
    avoided = original-optimized if comparable else None
    return {"requests": len(records), "legacy_records": legacy,
            "total_original_tokens": original, "total_optimized_tokens": optimized, "total_tokens_avoided": avoided,
            "token_reduction_pct": avoided/original*100 if original else None,
            "token_basis": next(iter(groups))[0] if comparable else "not comparable",
            "groups": [{"token_basis": key[0], "mode": key[1], "evidence_mode": key[2], **value} for key, value in groups.items()],
            "total_original_cost_est": None, "total_optimized_cost_est": None,
            "total_cost_saved_est": None, "cost_saved_pct": None,
            "cost_status": "N/A: traces do not establish actual paired billing or savings",
            "strategy_distribution": strategies}

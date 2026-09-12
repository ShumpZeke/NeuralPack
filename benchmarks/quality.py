"""Strict, deterministic answer validation for the synthetic context probes."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .corpus import Task


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant: {value}")


def _strict_equal(actual: Any, expected: Any) -> bool:
    # Python otherwise considers True == 1 and 1.0 == 1; probe types are exact.
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_strict_equal(actual[key], item) for key, item in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_strict_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def evaluate(task: Task, response: str) -> dict[str, Any]:
    """Evaluate assistant content only, never prompt-plus-completion output.

    Outer whitespace is ignored. Prose wrappers, markdown, extra keys, wrong
    case, nearby numbers, duplicate keys, and incorrect JSON types fail. A
    tool_call check validates serialized intent, not real tool execution.
    """
    if task.check_kind not in ("exact", "json", "tool_call"):
        raise ValueError(f"unsupported check_kind: {task.check_kind}")
    result: dict[str, Any] = {
        "task_id": task.id, "category": task.category, "check_kind": task.check_kind,
        "passed": False, "score": 0.0, "format_passed": False,
        "content_passed": False, "reason": "response must be a string",
    }
    if not isinstance(response, str):
        return result
    answer = response.strip()
    if task.check_kind == "exact":
        passed = type(task.expected) is str and answer == task.expected
        result.update(passed=passed, score=float(passed), format_passed=passed,
                      content_passed=passed, reason="exact match" if passed else "exact answer mismatch")
        return result
    try:
        actual = json.loads(answer, object_pairs_hook=_object_without_duplicates, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        result["reason"] = "invalid JSON, duplicate keys, or surrounding text"
        return result
    if not isinstance(actual, dict):
        result["reason"] = "top-level JSON must be an object"
        return result
    # Format means the complete declared key/type structure, not just parseability.
    def same_shape(value: Any, reference: Any) -> bool:
        if type(value) is not type(reference):
            return False
        if isinstance(reference, dict):
            return value.keys() == reference.keys() and all(same_shape(value[k], v) for k, v in reference.items())
        if isinstance(reference, list):
            return len(value) == len(reference) and all(same_shape(a, b) for a, b in zip(value, reference))
        return True
    shape = same_shape(actual, task.expected)
    passed = _strict_equal(actual, task.expected)
    result.update(passed=passed, score=float(passed), format_passed=shape,
                  content_passed=passed, reason="exact JSON match" if passed else "JSON key, type, or value mismatch")
    return result


def summarize(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counts and micro-accuracy; preserve per-task results for regression gates."""
    rows = list(results)
    by_category: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_category.setdefault(row["category"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
    for bucket in by_category.values():
        bucket["accuracy"] = bucket["passed"] / bucket["total"]
    passed = sum(int(row["passed"]) for row in rows)
    return {"total": len(rows), "passed": passed, "accuracy": passed / len(rows) if rows else None, "by_category": by_category}

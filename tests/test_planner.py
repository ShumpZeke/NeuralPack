"""Adversarial contracts for conservative state identity and measured planning."""
from dataclasses import asdict, replace
import math

import pytest

from npk.compatibility import ModelIdentity, digest, prefix_key, reusable_prefix_tokens
from npk.optimizer import Option, break_even_requests, choose, pareto_frontier


@pytest.fixture
def identity():
    return ModelIdentity(weights_sha256="a" * 64, tokenizer_sha256="b" * 64,
                         architecture="qwen2", layers=24, kv_heads=2, head_dim=64,
                         rope="theta=1000000", quantization="none", dtype="float16",
                         runtime="transformers-4.57.6/torch-2.8", attention_implementation="sdpa")


@pytest.mark.parametrize("field,value", [
    ("weights_sha256", "c" * 64), ("tokenizer_sha256", "c" * 64),
    ("architecture", "other"), ("layers", 25), ("kv_heads", 4), ("head_dim", 128),
    ("rope", "theta=10000"), ("quantization", "int8"), ("dtype", "bfloat16"),
    ("runtime", "different-version"), ("attention_implementation", "eager"),
    ("adapter_sha256", "d" * 64), ("layout", "sequence,batch,head,dim"),
])
def test_every_model_field_invalidates_state(identity, field, value):
    changed = replace(identity, **{field: value})
    assert changed.fingerprint != identity.fingerprint
    assert prefix_key(changed, [1, 2], namespace="private") != prefix_key(
        identity, [1, 2], namespace="private")


def test_fingerprint_is_stable_and_key_order_independent(identity):
    assert ModelIdentity(**asdict(identity)).fingerprint == identity.fingerprint
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


@pytest.mark.parametrize("value", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, ""])
def test_full_lowercase_model_digests_required(identity, value):
    with pytest.raises((ValueError, TypeError)):
        replace(identity, weights_sha256=value)


@pytest.mark.parametrize("field", ["layers", "kv_heads", "head_dim"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True, math.nan, math.inf])
def test_model_dimensions_are_positive_integers(identity, field, value):
    with pytest.raises((ValueError, TypeError)):
        replace(identity, **{field: value})


@pytest.mark.parametrize("tokens", [[True], [-1], [2**32], [1.0], ["1"], [None]])
def test_malformed_tokens_rejected(identity, tokens):
    with pytest.raises((ValueError, TypeError)):
        prefix_key(identity, tokens, namespace="private")


def test_prefix_identity_binds_order_length_namespace_mask_and_position(identity):
    common = prefix_key(identity, [1, 2, 3], namespace="tenant-a")
    alternatives = [
        prefix_key(identity, [1, 3, 2], namespace="tenant-a"),
        prefix_key(identity, [1, 2, 3, 0], namespace="tenant-a"),
        prefix_key(identity, [1, 2, 3], namespace="tenant-b"),
        prefix_key(identity, [1, 2, 3], namespace="tenant-a", attention_mask_hash="restricted"),
        prefix_key(identity, [1, 2, 3], namespace="tenant-a", position_offset=1),
    ]
    assert common not in alternatives
    assert len(set(alternatives)) == len(alternatives)


@pytest.mark.parametrize("kwargs", [
    {"namespace": ""}, {"namespace": None}, {"namespace": True},
    {"namespace": "private", "attention_mask_hash": ""},
    {"namespace": "private", "attention_mask_hash": None},
    {"namespace": "private", "position_offset": -1},
    {"namespace": "private", "position_offset": 0.5},
    {"namespace": "private", "position_offset": True},
])
def test_missing_or_invalid_derivation_parameters_rejected(identity, kwargs):
    with pytest.raises((ValueError, TypeError)):
        prefix_key(identity, [1, 2], **kwargs)


@pytest.mark.parametrize("old,new,expected", [
    ([1, 2, 3], [1, 2, 3, 4], 3),
    ([1, 2, 3], [1, 8, 3], 1),
    ([1, 2, 3], [1, 3], 1),
    ([1, 2, 3], [1, 2], 2),
    ([1, 2, 3], [2, 1, 3], 0),
    ([1, 2, 3], [1, 8, 9, 2, 3], 1),
    ([], [1], 0), ([1], [], 0), ([], [], 0),
])
def test_append_replacement_deletion_reorder_and_insertion(old, new, expected):
    assert reusable_prefix_tokens(old, new) == expected


@pytest.mark.parametrize("field", ["request_ms", "setup_ms", "p95_ms"])
@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf, -math.inf])
def test_invalid_costs_cannot_enter_planning(field, value):
    args = {"name": "test", "request_ms": 1, "evidence": "raw.jsonl"}
    args[field] = value
    with pytest.raises((ValueError, TypeError)):
        Option(**args)


@pytest.mark.parametrize("value", [-1, 1.5, math.nan, math.inf, True])
def test_storage_is_nonnegative_integer(value):
    with pytest.raises((ValueError, TypeError)):
        Option("test", 1, storage_bytes=value, evidence="measured")


@pytest.mark.parametrize("requests", [0, -1, True, 1.5, math.nan, math.inf])
def test_request_count_is_positive_integer(requests):
    with pytest.raises((ValueError, TypeError)):
        choose([Option("cold", 10, evidence="measured")], expected_requests=requests)


@pytest.mark.parametrize("kwargs", [
    {"storage_budget_bytes": -1}, {"storage_budget_bytes": 1.5},
    {"storage_budget_bytes": math.nan}, {"storage_budget_bytes": math.inf},
    {"ttft_slo_ms": -1}, {"ttft_slo_ms": math.nan}, {"ttft_slo_ms": math.inf},
])
def test_invalid_constraints_fail_closed(kwargs):
    with pytest.raises((ValueError, TypeError)):
        choose([Option("cold", 10, evidence="measured", p95_ms=11)], **kwargs)


def test_gates_exclude_faster_incompatible_unqualified_and_unproven_options():
    candidates = [Option("cold", 10, evidence="run-1"),
                  Option("bad-model", 0.1, compatible=False, evidence="run-1"),
                  Option("bad-quality", 0.1, quality_passed=False, evidence="run-1"),
                  Option("unmeasured", 0)]
    result = choose(candidates)
    assert result["choice"] == "cold"
    assert all(row["rejected"] for row in result["options"][1:])


def test_setup_cost_and_storage_tie_break_are_accounted():
    cold = Option("cold", 10, evidence="run-1")
    warm = Option("warm", 2, setup_ms=16, storage_bytes=100, evidence="run-1")
    assert choose([warm, cold], expected_requests=1)["choice"] == "cold"
    assert choose([warm, cold], expected_requests=2)["choice"] == "cold"
    assert choose([warm, cold], expected_requests=3)["choice"] == "warm"
    assert choose([warm, cold], expected_requests=3, storage_budget_bytes=99)["choice"] == "cold"


def test_slo_requires_tail_evidence_and_accepts_exact_boundary():
    options = [Option("no-tail", 1, evidence="run-1"),
               Option("pass", 2, p95_ms=3, evidence="run-1"),
               Option("fail", 1, p95_ms=3.1, evidence="run-1")]
    assert choose(options, ttft_slo_ms=3)["choice"] == "pass"
    assert choose(options, ttft_slo_ms=0)["choice"] is None
    assert choose([])["choice"] is None


@pytest.mark.parametrize("cold,warm,setup,expected", [
    (10, 2, 16, 3), (10, 2, 15.9, 2), (10, 2, 0, 1),
    (10, 10, 0, None), (10, 11, 0, None), (0, 0, 0, None),
])
def test_break_even_is_strictly_better_not_a_tie(cold, warm, setup, expected):
    assert break_even_requests(cold, warm, setup) == expected
    if expected:
        assert setup + expected * warm < expected * cold
        if expected > 1:
            assert setup + (expected - 1) * warm >= (expected - 1) * cold


@pytest.mark.parametrize("values", [(math.nan, 1, 0), (10, math.inf, 0), (10, 1, -1)])
def test_invalid_break_even_inputs(values):
    with pytest.raises(ValueError):
        break_even_requests(*values)


def test_pareto_preserves_tradeoffs_ties_and_input_order():
    rows = [{"id": "fast", "ms": 1, "bytes": 10, "quality": 0.9},
            {"id": "small", "ms": 2, "bytes": 1, "quality": 0.9},
            {"id": "dominated", "ms": 3, "bytes": 11, "quality": 0.8},
            {"id": "tied", "ms": 1, "bytes": 10, "quality": 0.9},
            {"id": "accurate", "ms": 4, "bytes": 12, "quality": 1.0}]
    frontier = pareto_frontier(rows, ("ms", "bytes"), ("quality",))
    assert [row["id"] for row in frontier] == ["fast", "small", "tied", "accurate"]
    assert len(rows) == 5


@pytest.mark.parametrize("rows,minimize,maximize", [
    ([{"ms": math.nan}], ("ms",), ()),
    ([{"ms": math.inf}], ("ms",), ()),
    ([{"quality": -math.inf}], (), ("quality",)),
    ([{"ms": 1}], (), ()),
    ([{"ms": 1}], ("missing",), ()),
])
def test_pareto_does_not_accept_incomplete_or_nonfinite_observations(rows, minimize, maximize):
    with pytest.raises((ValueError, KeyError)):
        pareto_frontier(rows, minimize, maximize)

"""Regressions for the audited cost-model and metric-reporting defects.

* ``gpt-4o-mini`` resolved to ``gpt-4o`` pricing via bidirectional substring
  matching -- a 16.7x overcharge on the planner's own default model.
* ``quality_retention_pct`` returned a hardcoded 100.0 whenever the baseline
  scored zero, which is how runs with 0% accuracy across every arm were
  published as "100% quality retention".
* MockProvider pass-rates were reported as "accuracy".
"""
from __future__ import annotations

import pytest

from benchmarks.metrics import (
    empirical_msc_efficiency,
    fmt_retention,
    retention_pct,
)
from npk.cost import (
    PRICING_TABLE,
    UnknownModelPricingError,
    estimate_cost,
    get_pricing,
    is_priced,
    resolve_model_id,
)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def test_gpt4o_mini_does_not_resolve_to_gpt4o():
    """The exact audited defect: a 16.7x overcharge via substring collision."""
    assert resolve_model_id("gpt-4o-mini") == "gpt-4o-mini"
    mini = get_pricing("gpt-4o-mini", provider="openai")
    full = get_pricing("gpt-4o", provider="openai")
    assert mini.input_per_million != full.input_per_million
    assert mini.input_per_million == pytest.approx(0.15)
    assert estimate_cost("gpt-4o-mini", 1_000_000, provider="openai") == pytest.approx(0.15)
    assert estimate_cost("gpt-4o", 1_000_000, provider="openai") == pytest.approx(2.50)


@pytest.mark.parametrize("model_id", sorted(PRICING_TABLE))
def test_every_model_resolves_to_itself(model_id):
    """No entry may be shadowed by another whose ID is a substring of it."""
    assert resolve_model_id(model_id) == model_id


def test_no_pricing_entry_shadows_another():
    for a in PRICING_TABLE:
        for b in PRICING_TABLE:
            if a != b and a in b:
                assert resolve_model_id(b) == b, f"{a!r} shadows {b!r}"


def test_unknown_model_is_not_silently_priced():
    assert is_priced("gpt-5") is False
    assert is_priced("some-unreleased-model") is False
    with pytest.raises(UnknownModelPricingError):
        estimate_cost("gpt-5", 1000, strict=True)


def test_every_pricing_entry_carries_provenance():
    for model_id, pricing in PRICING_TABLE.items():
        assert pricing.provider, f"{model_id} has no provider"
        assert pricing.source, f"{model_id} has no source"
        assert pricing.verified_on, f"{model_id} has no verification date"
        assert pricing.source.startswith("https://developers.openai.com/")


def test_cached_input_is_cheaper_than_uncached():
    plain = estimate_cost("gpt-4o", 100_000, provider="openai")
    cached = estimate_cost("gpt-4o", 100_000, cached_input_tokens=100_000, provider="openai")
    assert cached < plain


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_retention_is_undefined_when_baseline_is_zero():
    """Regression: this returned a fabricated 100.0."""
    assert retention_pct(0.0, 0.0) is None
    assert retention_pct(50.0, 0.0) is None
    assert fmt_retention(retention_pct(0.0, 0.0)) == "N/A"


def test_retention_is_a_real_ratio_when_defined():
    assert retention_pct(80.0, 100.0) == pytest.approx(80.0)
    assert retention_pct(100.0, 100.0) == pytest.approx(100.0)


def test_msc_efficiency_refuses_mismatched_granularity():
    """Regression: block-level MSC over line-level output gave 118-154%."""
    assert empirical_msc_efficiency(
        400, 300, msc_granularity="block", selection_granularity="line"
    ) is None


def test_msc_efficiency_at_matched_granularity_is_a_real_ratio():
    eff = empirical_msc_efficiency(
        300, 400, msc_granularity="block", selection_granularity="block"
    )
    assert eff == pytest.approx(75.0)
    assert eff <= 100.0, "a valid lower bound cannot exceed the selection it bounds"

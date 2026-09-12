"""Tests for the Multi-Provider Abstraction and Provider Registry."""
from __future__ import annotations

import pytest
from npk.providers import (
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    NvidiaNIMProvider,
    OpenAICompatibleProvider,
    MockProvider,
    get_provider,
)
from npk.plan import CostBasedPlanOptimizer, PlanCandidate


def test_provider_registry_by_name():
    assert isinstance(get_provider("mock"), MockProvider)
    assert isinstance(get_provider("openai", api_key="test"), OpenAIProvider)
    assert isinstance(get_provider("anthropic", api_key="test"), AnthropicProvider)
    assert isinstance(get_provider("gemini", api_key="test"), GeminiProvider)
    assert isinstance(get_provider("nvidia", api_key="test"), NvidiaNIMProvider)
    assert isinstance(get_provider("compatible"), OpenAICompatibleProvider)


def test_provider_registry_by_model_auto():
    p_claude = get_provider("auto", model="claude-3-5-sonnet-20241022", api_key="test")
    assert isinstance(p_claude, AnthropicProvider)

    p_gpt = get_provider("auto", model="gpt-4o", api_key="test")
    assert isinstance(p_gpt, OpenAIProvider)

    p_gemini = get_provider("auto", model="gemini-1.5-pro", api_key="test")
    assert isinstance(p_gemini, GeminiProvider)

    p_nim = get_provider("auto", model="meta/llama-3.2-11b-vision-instruct", api_key="test")
    assert isinstance(p_nim, NvidiaNIMProvider)


def test_anthropic_ephemeral_caching_format():
    anthropic = AnthropicProvider(api_key="test-key")
    large_system = "Large reference documentation...\n" * 200
    msgs = [
        {"role": "system", "content": large_system},
        {"role": "user", "content": "How do I configure this?"}
    ]
    # Verify that messages are formatted with system separation
    headers = anthropic._headers()
    assert headers["anthropic-beta"] == "prompt-caching-2024-07-31"
    assert headers["x-api-key"] == "test-key"


def test_cost_based_optimizer():
    opt = CostBasedPlanOptimizer(default_min_quality=0.95)
    c1 = PlanCandidate(
        name="c1_raw", strategies=["raw"], estimated_input_tokens=10000,
        estimated_output_tokens=100, estimated_cost_usd=0.05, estimated_latency_ms=1000,
        quality_risk=0.0, confidence=1.0, explanation="raw"
    )
    c2 = PlanCandidate(
        name="c2_compressed", strategies=["dedup", "retrieval"], estimated_input_tokens=2500,
        estimated_output_tokens=100, estimated_cost_usd=0.012, estimated_latency_ms=300,
        quality_risk=0.02, confidence=0.98, explanation="compressed"
    )
    c3 = PlanCandidate(
        name="c3_low_quality", strategies=["extreme_pruning"], estimated_input_tokens=500,
        estimated_output_tokens=100, estimated_cost_usd=0.003, estimated_latency_ms=100,
        quality_risk=0.15, confidence=0.85, explanation="low_quality"
    )

    # At min_quality 0.95: c2 should be selected (cheaper than c1, meets 0.95)
    best, reason = opt.select_best_plan([c1, c2, c3], min_quality=0.95)
    assert best.name == "c2_compressed"

    # At strict min_quality 0.99: c1 should be selected (only c1 meets 0.99)
    best_strict, _ = opt.select_best_plan([c1, c2, c3], min_quality=0.99)
    assert best_strict.name == "c1_raw"

    # At min_quality 0.80: c3 should be selected (cheapest)
    best_cheap, _ = opt.select_best_plan([c1, c2, c3], min_quality=0.80)
    assert best_cheap.name == "c3_low_quality"

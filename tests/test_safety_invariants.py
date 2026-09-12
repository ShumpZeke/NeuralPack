"""Permanent regressions for the defects found in the independent audit.

Every counterexample that broke the audited build lives here. These tests are
also the mutation-detection net for the three components whose defects
previously survived a full green run: dependency expansion, query preservation,
and the safety fallback.

Audit references: ``INDEPENDENT_AUDIT.md`` sections 2, 4.3 and 5.
"""
from __future__ import annotations

import pytest

from npk.context.analyzer import estimate_tokens
from npk.context.graph_slicer import ProgramGraphSlicer
from npk.context.info_gain import InformationGainSelector
from npk.context.retrieval import CodeContextRetriever
from npk.context.safety import check_invariants, extract_query
from npk.planner import ContextExecutionPlanner

SYSTEM = "You are a precise technical AI answering questions."


def _pad(n: int, tag: str = "d") -> list[str]:
    return [
        f"```File: surcharge_doc_{tag}{k}.py\n"
        f"# shipping surcharge resolve documentation for resolve_shipping_surcharge\n"
        f"SURCHARGE_NOTE_{k} = 'resolve shipping surcharge policy notes'\n"
        f"def resolve_shipping_surcharge_helper_{k}():\n    return None\n```"
        for k in range(n)
    ]


CHAIN_CONTEXT = "\n\n".join(
    [
        "```File: entry.py\nfrom alpha import compute_alpha\n\n"
        "def resolve_shipping_surcharge():\n    return compute_alpha()\n```",
        "```File: alpha.py\nfrom beta import BETA_CONSTANT\n\n"
        "def compute_alpha():\n    return BETA_CONSTANT\n```",
        "```File: beta.py\nBETA_CONSTANT = 60317\n```",
    ]
    + _pad(40)
)
CHAIN_QUERY = "What value does resolve_shipping_surcharge produce?"


def _messages(context: str, query: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{context}\n\nQUESTION: {query}"},
    ]


# ---------------------------------------------------------------------------
# 1. Reward hacking via context destruction (audit section 2)
# ---------------------------------------------------------------------------

def test_never_ships_empty_context_as_a_token_saving():
    """The central audited defect.

    The optimizer deleted 2,481 of 2,510 context tokens, shipped a bare
    question, and reported a 98.84% reduction with fallback_to_raw=False.
    """
    messages = _messages(CHAIN_CONTEXT, CHAIN_QUERY)
    out, plan = ContextExecutionPlanner().plan_and_optimize(out_model := messages, model="gpt-4o-mini")

    body = "\n".join(m["content"] for m in out if m["role"] == "user")
    body_wo_question = body.split("QUESTION:")[0]
    assert estimate_tokens(body_wo_question) > 8, (
        "optimizer emitted a context-free prompt; this is the audited "
        "reward-hacking failure"
    )
    assert plan.metadata["optimized_tokens"] > 8


def test_context_bearing_request_never_reduces_to_bare_question():
    """Property: for any context above the empty threshold, some context survives."""
    for n_pad in (5, 20, 60):
        ctx = "\n\n".join(_pad(n_pad, tag="p"))
        messages = _messages(ctx, "What is SURCHARGE_NOTE_3?")
        out, _plan = ContextExecutionPlanner().plan_and_optimize(messages, model="gpt-4o-mini")
        body = "\n".join(m["content"] for m in out if m["role"] == "user")
        assert estimate_tokens(body.split("QUESTION:")[0]) > 8, f"context destroyed at n_pad={n_pad}"


# ---------------------------------------------------------------------------
# 2. Seed failure must not be silently treated as a valid empty result
# ---------------------------------------------------------------------------

def test_failed_seed_stage_returns_original_context_not_empty():
    """Closure_D(emptyset) = emptyset -- expansion cannot rescue a failed seed."""
    retriever = CodeContextRetriever()
    out, stats = retriever.retrieve_relevant_context(
        CHAIN_CONTEXT, CHAIN_QUERY, max_token_budget=300, dependency_depth=1
    )
    assert out.strip(), "retriever returned an empty context"
    if stats.get("seed_failed"):
        assert out == CHAIN_CONTEXT, "failed seed stage must return the original context"


def test_selector_reports_seed_failure_rather_than_empty_selection():
    """A query matching nothing must raise the seed_failed flag, not return []."""
    blocks = [{"name": f"f{i}.py", "content": f"def g{i}(): return {i}",
               "text": f"def g{i}(): return {i}"} for i in range(10)]
    outcome = InformationGainSelector(enable_escalation=False).select(
        blocks, "zzzz_no_such_symbol_anywhere_qqq", {}, token_budget=500
    )
    assert outcome.seed_failed is True
    assert outcome.kept_indices == []
    assert "no block scored" in outcome.reason


def test_positively_scored_context_always_keeps_at_least_one_block():
    """Regression: the absolute 0.05 threshold returned [] on its first iteration."""
    blocks = [{"name": "target.py", "content": "RETRY_LIMIT = 918",
               "text": "```File: target.py\nRETRY_LIMIT = 918\n```"}]
    blocks += [{"name": f"n{i}.py", "content": f"def h{i}(): pass",
                "text": f"```File: n{i}.py\ndef h{i}(): pass\n```"} for i in range(60)]
    outcome = InformationGainSelector().select(blocks, "What is RETRY_LIMIT?", {}, token_budget=60)
    assert outcome.kept_indices, "selector returned an empty selection for a matching query"
    assert outcome.seed_failed is False


# ---------------------------------------------------------------------------
# 3. Dependency expansion must actually expand (mutation net)
# ---------------------------------------------------------------------------

def test_dependency_expansion_reaches_transitively_connected_block():
    """Fails if compute_transitive_closure degenerates to the identity."""
    slicer = ProgramGraphSlicer()
    retriever = CodeContextRetriever()
    blocks = retriever.parse_blocks(CHAIN_CONTEXT)
    edges, _ = slicer.build_dependency_graph(blocks)

    entry = next(i for i, b in enumerate(blocks) if b["name"] == "entry.py")
    reached = slicer.compute_transitive_closure({entry}, edges, max_depth=3)

    assert len(reached) > 1, "expansion returned only the seed set (identity mutation)"
    names = {blocks[i]["name"] for i in reached}
    assert "alpha.py" in names, "1-hop dependency not reached"


def test_expansion_depth_actually_bounds_reachability():
    slicer = ProgramGraphSlicer()
    blocks = CodeContextRetriever().parse_blocks(CHAIN_CONTEXT)
    edges, _ = slicer.build_dependency_graph(blocks)
    entry = next(i for i, b in enumerate(blocks) if b["name"] == "entry.py")

    d1 = slicer.compute_transitive_closure({entry}, edges, max_depth=1)
    d3 = slicer.compute_transitive_closure({entry}, edges, max_depth=3)
    assert len(d1) <= len(d3), "deeper traversal reached fewer nodes"
    assert len(d3) >= 2


def test_expansion_never_operates_on_empty_seed_set():
    slicer = ProgramGraphSlicer()
    assert slicer.compute_transitive_closure(set(), {0: {1}, 1: {2}}, max_depth=5) == set()


# ---------------------------------------------------------------------------
# 4. Budget enforcement (audit section 4.3)
# ---------------------------------------------------------------------------

def test_transitive_expansion_respects_token_budget():
    """Regression: expansion ran after budget selection and overshot it.

    Audited overshoot at budget=100: 113 / 135 / 156 / 192 tokens.
    """
    slicer = ProgramGraphSlicer()
    blocks = CodeContextRetriever().parse_blocks(CHAIN_CONTEXT)
    edges, _ = slicer.build_dependency_graph(blocks)
    costs = [max(1, estimate_tokens(b["text"])) for b in blocks]
    entry = next(i for i, b in enumerate(blocks) if b["name"] == "entry.py")

    budget = 60
    reached = slicer.compute_transitive_closure(
        {entry}, edges, max_depth=10, block_costs=costs, token_budget=budget
    )
    assert sum(costs[i] for i in reached) <= budget


@pytest.mark.parametrize("budget", [80, 200, 600])
def test_retrieved_context_stays_within_budget(budget):
    out, stats = CodeContextRetriever().retrieve_relevant_context(
        CHAIN_CONTEXT, CHAIN_QUERY, max_token_budget=budget, dependency_depth=3
    )
    if stats.get("seed_failed"):
        pytest.skip("seed failure returns original context by design")
    body = out.split("QUESTION:")[0]
    assert estimate_tokens(body) <= budget * 1.10, "selection exceeded its token budget"


# ---------------------------------------------------------------------------
# 5. Query and system-prompt preservation (mutation net)
# ---------------------------------------------------------------------------

def test_query_survives_optimization_verbatim():
    query = "What is the exact MAX_PARALLEL_WORKERS value?"
    ctx = "\n\n".join(_pad(30, tag="q") + ["```File: limits.py\nMAX_PARALLEL_WORKERS = 24\n```"])
    out, _plan = ContextExecutionPlanner().plan_and_optimize(_messages(ctx, query), model="gpt-4o-mini")
    assert query in "\n".join(m["content"] for m in out)


def test_system_instruction_survives_optimization():
    ctx = "\n\n".join(_pad(30, tag="s"))
    out, _plan = ContextExecutionPlanner().plan_and_optimize(
        _messages(ctx, "What is SURCHARGE_NOTE_2?"), model="gpt-4o-mini"
    )
    assert any(m["role"] == "system" and m["content"] == SYSTEM for m in out)


def test_query_actually_conditions_selection():
    """Direct retrieval must distinguish queries for two equally-sized blocks."""
    ctx = "\n\n".join([
        "```File: alpha_cfg.py\nALPHA_TIMEOUT = 111\n```",
        "```File: beta_cfg.py\nBETA_TIMEOUT = 222\n```",
    ] + _pad(20, tag="z"))

    retriever = CodeContextRetriever()
    out_a, _ = retriever.retrieve_relevant_context(ctx, "What is ALPHA_TIMEOUT?", max_token_budget=200)
    out_b, _ = retriever.retrieve_relevant_context(ctx, "What is BETA_TIMEOUT?", max_token_budget=200)

    assert "111" in out_a, "query did not steer selection toward ALPHA_TIMEOUT"
    assert "222" in out_b, "query did not steer selection toward BETA_TIMEOUT"
    assert out_a != out_b, "selection is independent of the query"


def test_planner_routes_the_current_question_to_retrieval(monkeypatch):
    planner = ContextExecutionPlanner()
    retrieve = planner.retriever.retrieve_relevant_context
    seen = []

    def record(text, query, *args, **kwargs):
        seen.append(query)
        return retrieve(text, query, *args, **kwargs)

    monkeypatch.setattr(planner.retriever, "retrieve_relevant_context", record)
    context = "\n\n".join(_pad(30, tag="routing") + [
        "```File: alpha.py\nALPHA_TIMEOUT = 111\n```",
        "```File: beta.py\nBETA_TIMEOUT = 222\n```",
    ])
    for query in ("What is ALPHA_TIMEOUT?", "What is BETA_TIMEOUT?"):
        seen.clear()
        # The question is a separate current message; a QUESTION suffix inside
        # the earlier source message must not be needed for correct routing.
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": context},
                    {"role": "assistant", "content": "Ready."},
                    {"role": "user", "content": query}]
        output, _ = planner.plan_and_optimize(messages, model="gpt-4o-mini")
        assert seen, "planner bypassed query-conditioned retrieval"
        assert set(seen) == {query}, "current question was lost before retrieval"
        assert query in "\n".join(m["content"] for m in output)


def test_extract_query_recovers_trailing_question():
    msgs = _messages("some context here", "What is the retry budget?")
    assert extract_query(msgs) == "What is the retry budget?"


# ---------------------------------------------------------------------------
# 6. Safety fallback (mutation net)
# ---------------------------------------------------------------------------

def test_invariant_checker_detects_destroyed_context():
    original = _messages("```File: a.py\nX = 1\n```" * 40, "What is X?")
    destroyed = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\nQUESTION: What is X?"},
    ]
    report = check_invariants(original, destroyed)
    assert report.ok is False
    assert any("context destroyed" in v for v in report.violations)


def test_invariant_checker_detects_lost_query():
    original = _messages("```File: a.py\nX = 1\n```" * 20, "What is X?")
    lost = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "```File: a.py\nX = 1\n```" * 20}]
    report = check_invariants(original, lost)
    assert report.ok is False
    assert any("query" in v for v in report.violations)


def test_invariant_checker_detects_lost_system_prompt():
    original = _messages("```File: a.py\nX = 1\n```" * 20, "What is X?")
    lost = [{"role": "user", "content": original[1]["content"]}]
    report = check_invariants(original, lost)
    assert report.ok is False
    assert any("system" in v for v in report.violations)


def test_planner_falls_back_when_a_stage_destroys_context(monkeypatch):
    """Forces an invariant violation and asserts the safety gate fires.

    Fails if the fallback is mutated away.
    """
    planner = ContextExecutionPlanner()

    def destroy(text, query, max_token_budget=4000, dependency_depth=2):
        return "", {"seed_failed": False, "original_tokens": estimate_tokens(text),
                    "optimized_tokens": 0, "dropped_fraction": 1.0,
                    "query_term_coverage": 1.0, "margin": 1.0, "top_score": 1.0}

    monkeypatch.setattr(planner.retriever, "retrieve_relevant_context", destroy)
    ctx = "\n\n".join(_pad(30, tag="f"))
    original = _messages(ctx, "What is SURCHARGE_NOTE_1?")
    expected = [dict(message) for message in original]
    out, plan = planner.plan_and_optimize(original, model="gpt-4o-mini")

    assert plan.fallback_kind == "safety", "safety fallback did not fire on a destroyed context"
    assert plan.invariant_violations, "violations were not recorded"
    assert out == expected, "raw context was not restored"


def test_safe_fallback_is_distinguishable_from_optimization():
    """A cost-based passthrough and a safety rejection must not look alike."""
    _out, plan = ContextExecutionPlanner().plan_and_optimize(
        _messages(CHAIN_CONTEXT, CHAIN_QUERY), model="gpt-4o-mini"
    )
    assert plan.fallback_kind in {
        "none", "cost_based_passthrough", "safety", "seed_failure_partial"
    }
    if plan.fallback_kind == "safety":
        assert plan.invariant_violations


# ---------------------------------------------------------------------------
# 7. Risk honesty
# ---------------------------------------------------------------------------

def test_quality_risk_responds_to_real_signals():
    """Risk must be derived from observable signals, not hardcoded constants.

    The audited build emitted a fixed 0.001/0.015/0.045 regardless of what was
    removed. Here a context whose control flow is hidden behind ``getattr`` /
    ``importlib`` must score strictly riskier than an equivalent static one,
    because static dependency expansion cannot see those edges.
    """
    from npk.context.safety import assess_risk

    common = dict(strategy="dependency_slice", original_tokens=2000, optimized_tokens=400,
                  retrieval_stats={"query_term_coverage": 1.0, "margin": 1.0, "top_score": 1.0})

    static_risk = assess_risk(**common, context_text="def f():\n    return CONST\n")
    dynamic_risk = assess_risk(
        **common,
        context_text="mod = importlib.import_module(name)\nreturn getattr(mod, 'X')\n",
    )
    assert dynamic_risk.score > static_risk.score, "dynamic indirection did not raise risk"

    # Partial coverage must be riskier than full coverage.
    low_cov = assess_risk(
        strategy="dependency_slice", original_tokens=2000, optimized_tokens=400,
        retrieval_stats={"query_term_coverage": 0.2, "margin": 1.0, "top_score": 1.0},
        context_text="def f(): pass",
    )
    assert low_cov.score > static_risk.score, "dropping query terms did not raise risk"

    # A failed seed stage is maximal risk.
    failed = assess_risk(strategy="dependency_slice", original_tokens=2000,
                         optimized_tokens=0, seed_failed=True)
    assert failed.score == 1.0
    assert failed.band == "uncalibrated:maximum"

    assert {round(r.score, 4) for r in (static_risk, dynamic_risk, low_cov, failed)} - {
        0.001, 0.015, 0.045
    }, "risk values look hardcoded"


def test_uncalibrated_risk_is_labelled_as_such():
    _out, plan = ContextExecutionPlanner().plan_and_optimize(
        _messages("\n\n".join(_pad(30, tag="u")), "What is SURCHARGE_NOTE_1?"),
        model="gpt-4o-mini",
    )
    for c in plan.candidates:
        if c.name == "raw_full_context":
            continue
        assert c.risk_calibrated is False
        assert c.risk_band.startswith("uncalibrated"), (
            "an uncalibrated ordinal score must not be presented as a probability"
        )


# ---------------------------------------------------------------------------
# 8. Cross-request isolation
# ---------------------------------------------------------------------------

def test_planner_reuse_does_not_leak_context_between_requests():
    planner = ContextExecutionPlanner()
    ctx_a = "\n\n".join(["```File: secret_a.py\nTOKEN_A = 'AAA111'\n```"] + _pad(20, tag="a"))
    ctx_b = "\n\n".join(["```File: secret_b.py\nTOKEN_B = 'BBB222'\n```"] + _pad(20, tag="b"))

    out_a, _ = planner.plan_and_optimize(_messages(ctx_a, "What is TOKEN_A?"), model="gpt-4o-mini")
    out_b, _ = planner.plan_and_optimize(_messages(ctx_b, "What is TOKEN_B?"), model="gpt-4o-mini")

    text_b = "\n".join(m["content"] for m in out_b)
    assert "AAA111" not in text_b, "context from a previous request leaked into this one"


def test_planner_does_not_mutate_caller_messages():
    ctx = "\n\n".join(_pad(25, tag="m"))
    messages = _messages(ctx, "What is SURCHARGE_NOTE_1?")
    snapshot = [dict(m) for m in messages]
    ContextExecutionPlanner().plan_and_optimize(messages, model="gpt-4o-mini")
    assert messages == snapshot, "planner mutated the caller's message list in place"


# ---------------------------------------------------------------------------
# 9. Seed-failure guard at the retriever boundary (mutation net)
# ---------------------------------------------------------------------------

def test_unmatchable_query_returns_original_context_never_empty():
    """Directly exercises the seed-failure guard in retrieve_relevant_context.

    Fails if the guard is removed: without it the retriever emits "" for a
    query that matches nothing, which is the audited context-destruction path.
    """
    ctx = "\n\n".join(_pad(25, tag="g"))
    out, stats = CodeContextRetriever().retrieve_relevant_context(
        ctx, "zzqqxx_no_such_symbol_anywhere_12345", max_token_budget=200, dependency_depth=2
    )
    assert stats["seed_failed"] is True
    assert out == ctx, "failed seed stage must return the ORIGINAL context, not empty"
    assert out.strip(), "retriever emitted an empty context"


def test_planner_keeps_context_when_seed_stage_fails():
    ctx = "\n\n".join(_pad(25, tag="h"))
    messages = _messages(ctx, "zzqqxx_no_such_symbol_anywhere_12345")
    out, plan = ContextExecutionPlanner().plan_and_optimize(messages, model="gpt-4o-mini")
    body = "\n".join(m["content"] for m in out if m["role"] == "user")
    assert estimate_tokens(body.split("QUESTION:")[0]) > 8
    assert plan.metadata["seed_failed"] is True

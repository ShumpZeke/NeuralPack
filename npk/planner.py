"""Cost-based context execution planner with hard safety invariants.

Post-audit rewrite. Behavioural changes versus the audited build:

* Generic text deduplication and message reordering were removed: neither
  preserves arbitrary code, document, or conversation semantics.
* ``quality_risk`` is derived from observable retrieval signals via
  :func:`npk.context.safety.assess_risk` instead of the hardcoded constants
  ``0.001 / 0.015 / 0.045``.
* Every emitted prompt is checked against hard invariants
  (:func:`npk.context.safety.check_invariants`). A violation forces a safety
  fallback to the raw context, and the plan records *why*.
* A safety fallback is distinguishable from a cost-based passthrough via
  :attr:`ExecutionPlanIR.fallback_kind`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .context.analyzer import ContextAnalyzer, estimate_tokens
from .context.compressor import ExtractiveCompressor
from .context.convo_compiler import ConversationCompiler
from .context.retrieval import CodeContextRetriever
from .context.safety import assess_risk, check_invariants, extract_query
from .context.trace_compiler import ToolTraceCompiler
from .cost import estimate_cost, get_pricing
from .plan import CostBasedPlanOptimizer, ExecutionPlanIR, PlanCandidate


class ContextExecutionPlanner:
    def __init__(
        self,
        max_acceptable_quality_risk: float = 0.05,
        target_model: str = "gpt-4o-mini",
        enable_retrieval: bool = True,
        enable_compression: bool = True,
        dependency_depth: int = 2,
        selection_strategy: str = "relative",
        use_local_embeddings: bool = False,
    ):
        self.max_risk = max_acceptable_quality_risk
        self.target_model = target_model
        self.enable_retrieval = enable_retrieval
        self.enable_compression = enable_compression
        self.dependency_depth = dependency_depth
        self.selection_strategy = selection_strategy

        self.analyzer = ContextAnalyzer()
        self.retriever = CodeContextRetriever(selection_strategy=selection_strategy,
                                              enable_escalation=use_local_embeddings)
        self.compressor = ExtractiveCompressor()
        self.trace_compiler = ToolTraceCompiler()
        self.convo_compiler = ConversationCompiler()
        self.cost_optimizer = CostBasedPlanOptimizer(
            default_min_quality=1.0 - max_acceptable_quality_risk
        )

    # ------------------------------------------------------------------
    def plan_and_optimize(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        quality_threshold: Optional[float] = None,
        provider: Optional[str] = None,
    ) -> Tuple[List[Dict[str, str]], ExecutionPlanIR]:
        effective_model = model or self.target_model
        min_quality = quality_threshold if quality_threshold is not None else (1.0 - self.max_risk)
        req_id = f"npk-{uuid.uuid4().hex[:12]}"

        analysis = self.analyzer.analyze_messages(messages)
        orig_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        query = extract_query(messages)
        full_context_text = "\n".join(m.get("content", "") for m in messages)

        # --- Candidate A: raw passthrough -----------------------------
        plan_a = PlanCandidate(
            name="raw_full_context",
            strategies=["passthrough"],
            estimated_input_tokens=orig_tokens,
            estimated_output_tokens=None,
            estimated_cost_usd=estimate_cost(effective_model, orig_tokens, provider=provider),
            estimated_latency_ms=None,
            quality_risk=0.0,
            confidence=1.0,
            explanation="Full unmodified context passthrough",
            risk_calibrated=False,
            risk_band="uncalibrated_passthrough",
            risk_signals={"dropped_context_fraction": 0.0, "context_unchanged": True},
        )

        # --- Candidate C: query-conditioned slicing --------------------
        c_msgs = [dict(m) for m in messages]
        strategies_c: List[str] = []
        c_dropped = 0
        agg_stats: Dict[str, Any] = {}
        seed_failed_any = False
        unmeasured_transform = False

        for m in c_msgs:
            if m.get('role') != 'user':
                continue
            content = m.get("content", "")
            if content == query or len(content) < 150:
                continue

            q_match = re.search(r"(\n\n(?:QUESTION|Question|Query):\s*.*)$", content, re.DOTALL)
            ctx_part = content[: q_match.start()] if q_match else content
            suffix_part = q_match.group(1) if q_match else ""
            m_query = query or re.sub(r"^\s*(QUESTION|Question|Query):\s*", "", suffix_part).strip()

            if self.trace_compiler.is_trace_context(ctx_part):
                opt_ctx, tstats = self.trace_compiler.compile_trace(ctx_part, m_query)
                if tstats.get("tokens_avoided", 0) > 0:
                    unmeasured_transform = True
                    c_dropped += tstats["tokens_avoided"]
                    m["content"] = opt_ctx + suffix_part
                    if "trace_compaction" not in strategies_c:
                        strategies_c.append("trace_compaction")

            elif self.convo_compiler.is_conversation_context(ctx_part):
                opt_ctx, cstats = self.convo_compiler.compile_conversation(ctx_part)
                if cstats.get("tokens_avoided", 0) > 0:
                    unmeasured_transform = True
                    c_dropped += cstats["tokens_avoided"]
                    m["content"] = opt_ctx + suffix_part
                    if "convo_compaction" not in strategies_c:
                        strategies_c.append("convo_compaction")

            elif self.enable_retrieval and bool(re.search(r"```|##", ctx_part)):
                opt_ctx, rstats = self.retriever.retrieve_relevant_context(
                    ctx_part, m_query,
                    max_token_budget=4000,
                    dependency_depth=self.dependency_depth,
                )
                agg_stats = rstats
                if rstats.get("seed_failed"):
                    # INVARIANT: expansion cannot recover from a failed seed set
                    # (Closure_D(empty) = empty). Keep the original context.
                    seed_failed_any = True
                    continue
                dropped = rstats.get("original_tokens", 0) - rstats.get("optimized_tokens", 0)
                if dropped > 0:
                    c_dropped += dropped
                    m["content"] = opt_ctx + suffix_part
                    if "symbol_dependency_slice" not in strategies_c:
                        strategies_c.append("symbol_dependency_slice")

        c_tokens = sum(estimate_tokens(m.get("content", "")) for m in c_msgs)
        risk_c = assess_risk(
            strategy="dependency_slice",
            original_tokens=orig_tokens,
            optimized_tokens=c_tokens,
            retrieval_stats=None if unmeasured_transform else agg_stats,
            context_text=full_context_text,
            seed_failed=seed_failed_any,
            context_unchanged=c_msgs == messages,
        )
        plan_c = PlanCandidate(
            name="symbol_dependency_slice",
            strategies=strategies_c or ["passthrough"],
            estimated_input_tokens=c_tokens,
            estimated_output_tokens=None,
            estimated_cost_usd=estimate_cost(
                effective_model, c_tokens, provider=provider,
            ),
            estimated_latency_ms=None,
            quality_risk=risk_c.score,
            confidence=1.0 - risk_c.score,
            explanation=f"Query-conditioned dependency slice avoiding {c_dropped} tokens",
            risk_calibrated=risk_c.calibrated,
            risk_band=risk_c.band,
            risk_signals=risk_c.signals,
        )

        # --- Candidate D: aggressive extractive compression ------------
        d_msgs = [dict(m) for m in c_msgs]
        d_avoided = 0
        if self.enable_compression and c_tokens > 1500 and query and not seed_failed_any:
            for m in d_msgs:
                if m.get('role') != 'user' or m.get('content') == query:
                    continue
                content = m.get("content", "")
                if len(content) > 800:
                    comp_text, cstats = self.compressor.compress_text(content, query, target_ratio=0.6)
                    d_avoided += cstats.get("avoided_tokens", 0)
                    m["content"] = comp_text

        d_tokens = sum(estimate_tokens(m.get("content", "")) for m in d_msgs)
        risk_d = assess_risk(
            strategy="aggressive_compress",
            original_tokens=orig_tokens,
            optimized_tokens=d_tokens,
            retrieval_stats=None if unmeasured_transform or d_avoided else agg_stats,
            context_text=full_context_text,
            seed_failed=seed_failed_any,
            context_unchanged=d_msgs == messages,
        )
        plan_d = PlanCandidate(
            name="aggressive_hybrid_compress",
            strategies=(strategies_c + ["extractive_compression"]) if d_avoided else (strategies_c or ["passthrough"]),
            estimated_input_tokens=d_tokens,
            estimated_output_tokens=None,
            estimated_cost_usd=estimate_cost(
                effective_model, d_tokens, provider=provider,
            ),
            estimated_latency_ms=None,
            quality_risk=risk_d.score,
            confidence=1.0 - risk_d.score,
            explanation=f"Extractive compression saving a further {d_avoided} tokens",
            risk_calibrated=risk_d.calibrated,
            risk_band=risk_d.band,
            risk_signals=risk_d.signals,
        )

        candidates = [plan_a, plan_c, plan_d]
        chosen, reason = self.cost_optimizer.select_best_plan(candidates, min_quality=min_quality)

        by_name = {
            "raw_full_context": messages,
            "symbol_dependency_slice": c_msgs,
            "aggressive_hybrid_compress": d_msgs,
        }
        final_messages = by_name[chosen.name]

        # --- HARD INVARIANT GATE --------------------------------------
        # Nothing below this line may ship a prompt that violates the
        # invariants. A violation forces a safety fallback to raw context.
        report = check_invariants(messages, final_messages)
        fallback_kind = "none"
        if chosen.name == "raw_full_context":
            fallback_kind = "cost_based_passthrough"

        if not report.ok:
            final_messages = messages
            chosen = plan_a
            fallback_kind = "safety"
            reason = (
                "SAFETY FALLBACK: optimized prompt violated hard invariants ("
                + "; ".join(report.violations)
                + "); dispatched raw context instead"
            )
        elif seed_failed_any and chosen.name != "raw_full_context":
            fallback_kind = "seed_failure_partial"

        pricing = get_pricing(effective_model, provider=provider)
        plan_ir = ExecutionPlanIR(
            request_id=req_id,
            workload_type=analysis.context_type,
            query_intent=query[:80],
            candidates=candidates,
            chosen_candidate=chosen,
            selection_reason=reason,
            quality_threshold=min_quality,
            fallback_to_raw=(chosen.name == "raw_full_context"),
            fallback_kind=fallback_kind,
            invariant_violations=report.violations,
            metadata={
                "original_tokens": orig_tokens,
                "optimized_tokens": chosen.estimated_input_tokens,
                "tokens_avoided": orig_tokens - chosen.estimated_input_tokens,
                "estimated_savings_usd": (plan_a.estimated_cost_usd - chosen.estimated_cost_usd)
                    if pricing is not None else None,
                "cost_basis": "hypothetical uncached text input only; excludes output, cache hits, local compute and other fees",
                "pricing_provider": provider,
                "pricing_source": pricing.source if pricing else None,
                "pricing_verified_on": pricing.verified_on if pricing else None,
                "token_basis": "planner_chars_div3_8_estimate",
                "strategies": chosen.strategies,
                "explanation": [chosen.explanation],
                "risk_band": chosen.risk_band,
                "risk_calibrated": chosen.risk_calibrated,
                "risk_signals": chosen.risk_signals,
                "seed_failed": seed_failed_any,
                "fallback_kind": fallback_kind,
            },
        )
        return final_messages, plan_ir

"""NeuralPack Context Optimization Runtime & Client Engine."""
from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, Generator, List, Optional
import uuid

from .planner import ContextExecutionPlanner
from .plan import ExecutionPlanIR
from .providers.base import BaseProvider, ChatResponse
from .providers.registry import get_provider
from .telemetry import TraceLogger, TraceRecord
from .context.analyzer import estimate_tokens


class NeuralPackClient:
    """
    Universal context optimization client for closed and open AI models.
    """
    def __init__(
        self,
        provider: str = "auto",
        mode: str = "optimized",  # baseline | optimized | shadow
        api_key: Optional[str] = None,
        default_model: str = "meta/llama-3.2-11b-vision-instruct",
        quality_threshold: float = 0.05,
        trace_path: str = "experiments/traces.jsonl",
        use_local_embeddings: bool = False,
    ):
        self.mode = mode
        self.default_model = default_model
        self.quality_threshold = quality_threshold
        self.planner = ContextExecutionPlanner(
            max_acceptable_quality_risk=quality_threshold,
            target_model=default_model,
            use_local_embeddings=use_local_embeddings,
        )
        self.logger = TraceLogger(trace_path)

        self.provider: BaseProvider = get_provider(
            provider_name=provider,
            model=default_model,
            api_key=api_key,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = 512,
        temperature: float = 0.7,
        stream: bool = False,
        mode_override: Optional[str] = None,
        **kwargs: Any,
    ) -> ChatResponse | Generator[Dict[str, Any], None, None]:
        target_model = model or self.default_model
        active_mode = mode_override or self.mode
        req_id = f"npk-{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc).isoformat()
        evidence_mode = "MOCK" if self.provider.name == "mock" else ("LOCAL" if self.provider.name.startswith("local") else "LIVE")

        if active_mode == "baseline":
            # Baseline mode: raw passthrough
            res = self.provider.chat_completion(
                messages=messages, model=target_model, max_tokens=max_tokens,
                temperature=temperature, stream=stream, **kwargs
            )
            if not stream and isinstance(res, ChatResponse):
                self.logger.log(TraceRecord(
                    request_id=req_id, timestamp_utc=timestamp, provider=self.provider.name,
                    model=target_model, mode="baseline", original_tokens=res.usage.prompt_tokens,
                    optimized_tokens=res.usage.prompt_tokens, tokens_avoided=0,
                    original_cost_est=None, optimized_cost_est=None, cost_saved_est=None,
                    token_basis="provider_adapter_reported", evidence_mode=evidence_mode, reported_usage=res.usage.to_dict(),
                    latency_ms=res.latency_ms, ttft_ms=res.ttft_ms,
                    plan_strategy=["baseline_passthrough"], plan_details={}
                ))
            return res

        elif active_mode == "shadow":
            # Shadow mode: execute baseline, evaluate optimized in background
            start = time.perf_counter_ns()
            res = self.provider.chat_completion(
                messages=messages, model=target_model, max_tokens=max_tokens,
                temperature=temperature, stream=stream, **kwargs
            )
            duration_ms = (time.perf_counter_ns() - start) / 1e6
            # Run planner to calculate what could have been saved
            _, plan = self.planner.plan_and_optimize(messages, model=target_model, quality_threshold=1-self.quality_threshold, provider=self.provider.name)
            self.logger.log(TraceRecord(
                request_id=req_id, timestamp_utc=timestamp, provider=self.provider.name,
                model=target_model, mode="shadow", original_tokens=plan.metadata["original_tokens"],
                optimized_tokens=plan.metadata["original_tokens"], tokens_avoided=0,
                original_cost_est=None, optimized_cost_est=None, cost_saved_est=None, latency_ms=duration_ms,
                ttft_ms=res.ttft_ms if isinstance(res, ChatResponse) else None, plan_strategy=plan.chosen_candidate.strategies,
                token_basis="planner_chars_div3_8_estimate", evidence_mode=evidence_mode,
                reported_usage=res.usage.to_dict() if isinstance(res, ChatResponse) else None,
                plan_details={"hypothetical_plan": plan.to_dict()}
            ))
            return res

        else:  # optimized mode
            optimized_msgs, plan = self.planner.plan_and_optimize(
                messages, model=target_model, quality_threshold=1-self.quality_threshold, provider=self.provider.name
            )
            res = self.provider.chat_completion(
                messages=optimized_msgs, model=target_model, max_tokens=max_tokens,
                temperature=temperature, stream=stream, **kwargs
            )
            if not stream and isinstance(res, ChatResponse):
                # Enrich response with optimization metadata
                res.raw["neuralpack_plan"] = {
                    "request_id": req_id,
                    "plan_name": plan.chosen_candidate.name,
                    "strategies": plan.chosen_candidate.strategies,
                    "original_tokens": plan.metadata["original_tokens"],
                    "optimized_tokens": plan.metadata["optimized_tokens"],
                    "tokens_avoided": plan.metadata["tokens_avoided"],
                    "estimated_input_savings_usd": plan.metadata["estimated_savings_usd"],
                    "explanation": plan.metadata["explanation"],
                    "plan_ir": plan.to_dict(),
                }
                self.logger.log(TraceRecord(
                    request_id=req_id, timestamp_utc=timestamp, provider=self.provider.name,
                    model=target_model, mode="optimized", original_tokens=plan.metadata["original_tokens"],
                    optimized_tokens=plan.metadata["optimized_tokens"],
                    tokens_avoided=plan.metadata["tokens_avoided"],
                    original_cost_est=None, optimized_cost_est=None, cost_saved_est=None, latency_ms=res.latency_ms,
                    token_basis="planner_chars_div3_8_estimate", evidence_mode=evidence_mode, reported_usage=res.usage.to_dict(),
                    ttft_ms=res.ttft_ms, plan_strategy=plan.chosen_candidate.strategies,
                    plan_details={"explanation": plan.metadata["explanation"], "chosen": plan.chosen_candidate.name}
                ))
            return res


# ADR 0002: Formal Execution Plan IR and Cost-Based Query Optimization

Status: Accepted; 2026-09-06.

## Context
Initial context optimization used hardcoded rules (e.g. `if tokens > 4000 then compress`). In real-world enterprise applications, context requests have varying latency SLOs, cost targets, and quality tolerance. Hardcoded rules cannot weigh whether the compute/latency cost of compressing a prompt exceeds the token savings from a cheap model, or whether a provider cache hit makes keeping a static prefix cheaper than re-extracting it.

## Decision
We implemented a formal **Execution Plan IR** (`npk/plan.py`) and a **Cost-Based Plan Optimizer** analogous to database query optimizers:
1. For every request, the optimizer generates multiple candidate execution plans:
   - `raw_full_context`: 100% tokens, 100% confidence, 0 risk.
   - `dedup_and_prefix_cache`: deduplicated boilerplate + prefix alignment for provider caching (99.9% confidence).
   - `symbol_dependency_slice`: query-conditioned symbol graph extraction + dependency expansion (98.5% confidence).
   - `aggressive_hybrid_compress`: retrieval + extractive compression (95.5% confidence).
2. Candidate plans are evaluated on a multi-objective frontier (cost, latency, quality risk).
3. The cheapest plan that meets the user''s quality threshold is selected.
4. If uncertainty is high or confidence is below threshold, the planner automatically falls back to raw full context.

## Evidence
On our multi-workload benchmark suite (`benchmarks/evaluation_suite.py`), the Cost-Based Plan Optimizer achieved 100% task accuracy across all categories, whereas blind top-K RAG suffered an accuracy drop to 88.9% due to missing cross-file import dependencies.

## Reversal Conditions
Revert to static pipelines only if plan generation latency exceeds token savings on high-throughput micro-requests (<200 tokens).

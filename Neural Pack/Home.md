# Neural Pack

An evidence-driven local research & product vault for the NeuralPack context optimization system.

## 1. Mathematical Foundations & Breakthroughs
- [[Research/Mathematical Foundations]] — formalization of MSC, Theorem 1 (NP-hardness proof), Theorem 2 (failure of independent Top-K), Theorem 3 (transitive closure guarantee), and Rate-Distortion knee.
- [[Research/Product Pivot]] — the evidence-backed strategic pivot from portable KV caches to closed-model context optimization.
- [[Product/Vision]] — spend less context, keep the intelligence.
- [[Product/Architecture]] — gateway, runtime, context optimizer, and telemetry.
- [[Product/MVP]] — MVP definition and requirement verification checklist.
- [[Product/Provider Adapters]] — universal provider architecture (OpenAI, Anthropic, Gemini, NVIDIA NIM, Local).
- [[Product/NVIDIA NIM]] — testing integration, models, and security rules.
- [[Product/Optimizer]] — staged optimizer: dedup, prefix alignment, hybrid retrieval, and safety gate.
- [[Product/Evaluation]] — benchmark results on NVIDIA NIM (27.24% token reduction, 100% quality retention).
- [[Decisions/0002-cost-based-execution-plan-ir]] — ADR on formal Execution Plan IR and cost-based query optimization.

## 2. Research & Open-Model Benchmarks
- [[Mission]] — original instructions, preserved verbatim.
- [[Research/Systems]] — serving and cache prior art (vLLM, SGLang, LMCache, Mooncake).
- [[Research/Transfer]] — cross-model transfer and representation research.
- [[Engineering/Corpus]] — workloads and quality evaluation.
- [[Engineering/Baseline]] — single-process baseline inference measurements.
- [[Engineering/Chunked Prefill]] — 16K context scaling and OOM elimination via chunked prefill.
- [[Engineering/Model Quality]] — quality eval on 28 tasks and causal edit tests.
- [[Engineering/Compiler]] — source compiler architecture and CLI.
- [[Engineering/Incremental Benchmark]] — incremental source compilation and chunking comparison.

## 3. Journals & Audit Trail
- [[Journal/2026-09-05]] — initial R&D actions and decisions.
- [[Journal/2026-09-06]] — benchmarks, failure fixes, and product pivot implementation.

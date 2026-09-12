# NeuralPack landscape and novelty test

Assessed 2026-09-05. Status: initial primary-source review; no literature speedup reproduced in this document. Detailed implementation evidence, immutable source revisions and research limitations are in [systems.md](systems.md). Cross-model and representation evidence belongs in [papers.md](papers.md).

## What is already occupied

| Proposed capability | Strong existing reference | Boundary that matters |
|---|---|---|
| Avoid re-reading an identical prompt prefix | [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/latest/design/prefix_caching/) | Identity includes preceding computation; full block matching |
| Share prefixes across branching requests | [SGLang radix cache](https://github.com/sgl-project/sglang/blob/6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da/python/sglang/srt/mem_cache/radix_cache.py) | Matching state and runtime semantics remain model-specific |
| Store/move cache beyond GPU memory | [LMCache](https://arxiv.org/abs/2510.09665) | Backend, runtime connector, layout and lifecycle determine valid reuse |
| Reuse documents outside their original prefix | [LMCache CacheBlend](https://docs.lmcache.ai/kv_cache_optimizations/cacheblend.html) | Selective repair is approximate; qualify with quality tests |
| Schedule computation near cached state | [Mooncake](https://arxiv.org/html/2407.00079v3) | Transfer, load and SLOs already influence placement |
| Separate prefill and decode workers | [DistServe](https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin) | Same-model phase placement; not portable semantic memory |
| Unify full/SWA/SSM cache management | [SGLang unified-cache design](https://github.com/sgl-project/sglang/blob/6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da/python/sglang/srt/mem_cache/unified_cache/components/README.md) | Common interface does not make representations interchangeable |
| Safe partial loading of tensor files | [Safetensors](https://huggingface.co/docs/safetensors/index) | Parsing safety does not prove producer authenticity or compatibility |

These references substantially defeat the simple novelty claim “compile a KV cache once and distribute it.” They also defeat presenting content hashes, storage tiers, a cache-control API or a basic transfer-versus-recompute cost calculation as sufficient differentiation.

The phrase “compile information once” covers several different products. It is useful to separate them before judging a result:

| Artifact level | Portable thing | Potentially avoided work | Validation question |
|---|---|---|---|
| L0 source | Exact source bytes and provenance | Reading, fetching and duplicate storage | Can every source span be recovered and verified? |
| L1 tokenization | Tokens plus tokenizer/template identity | Repeated text processing | Does the exact target rendering produce the same IDs? |
| L2 structure | Chunks, syntax, symbols and relationships | Parsing and repository traversal | How much rebuilding follows a small change? |
| L3 retrieval | Index plus embedding/scoring configuration | Re-embedding and index building | Does retrieval remain accurate after updates? |
| L4 compressed text/semantics | Summary or task-conditioned information | Shorter future model input | Which facts and instructions were lost? |
| L5 learned state | A trained adapter or family-specific latent | Some target-model processing, if established | Does training and translation amortize on held-out tasks? |
| L6 exact KV | Model- and derivation-specific activations | Recomputing a valid prefix | Are weights, tokens, positions and layout compatible? |
| L7 execution artifact | Kernel/backend-specific state | Compilation or data-layout setup | Does the hardware/runtime contract match? |

This table is an analytical decomposition, not a proposed requirement that every package contain every level. The more portable levels do not automatically avoid model prefill; the levels that avoid prefill carry stricter compatibility conditions.

## The core technical obstacle

For a causal transformer, an unchanged passage can follow a changed prefix. Its deeper-layer hidden states may change because attention sees different preceding content. Equal source hashes establish byte equality, not activation equality. A syntax dependency graph may correctly avoid re-parsing a function while failing to represent its attention dependencies.

Accordingly, track at least two independent kinds of reuse: source/index artifacts derived from a local content unit, and neural state derived from a complete valid prefix plus model/runtime configuration. The exact path should fail closed after an incompatible change. Arbitrary document reordering belongs to an explicitly approximate fusion experiment or full recomputation.

An apparent speedup can come from doing less work because the task changed. Retrieving fewer chunks, summarizing a document, omitting an instruction and reusing exact KV are four different interventions. Compare both answer quality and the precise context presented to the model.

## A defensible initial hypothesis

**A local incremental context compiler with an auditable reuse decision may be useful even if a new neural representation is not.**

The small candidate should preserve original source and spans; reuse unchanged structural/retrieval artifacts; bind tokenization and optional exact state to explicit derivation identities; explain what it reused and what it recomputed; and expose reproducible cold/warm measurements. Existing serving and cache backends should supply inference and transport where practical.

This hypothesis remains weak until tested against a much simpler pipeline: ordinary files, a persistent retrieval index and the runtime's native cache. A wrapper that adds manifest overhead without simplifying a real task or reducing total work should be discarded. A cost planner must beat a fixed best policy on held-out workload traces; naming that planner does not establish novelty.

## Cheap adversarial experiments

1. Compile a mixed code/document fixture, edit one line at the beginning, middle and end, and measure source bytes scanned, objects rebuilt and bytes rewritten. Compare full rebuild, file-level reuse, and chunk-level reuse.
2. Render identical prompts under the same tokenizer and compare fresh full prefill with cached-prefix continuation, including next-token boundary work. Repeat after prefix replacement and assert that incompatible later state is refused.
3. Reload a saved state in a new process. Check logits, source provenance and compatibility metadata, then measure the complete latency path. Include a corrupt artifact and an incompatible model revision.
4. Compare full-context cold inference, native prefix caching, retrieval preprocessing reuse and a hybrid on the same questions. Keep instruction adherence and rare details as separate gates.
5. Test partial-overlap repair only after the exact path works. Include reordered evidence, negation, conflicting instructions and small numerical differences. CacheBlend is an appropriate challenger/baseline, subject to local feasibility.
6. Train any adaptive planner on one workload split and evaluate it on a different split, with a clairvoyant oracle used only as an upper bound. Account for miss handling, build cost and prediction overhead.

These are experiment proposals, not completed results. A tiny random model can expose invalidation bugs but cannot validate useful language quality. A simulated network can test policy behavior but cannot establish measured RDMA throughput.

## Kill and pivot decisions

| Evidence | Decision |
|---|---|
| Native caching plus existing storage is equal or better in every useful tested regime | Stop implementing a competing KV store; contribute an adapter or pivot |
| Source/index incremental builds save work but inference does not improve | Publish an incremental preprocessing tool with accurately limited claims |
| Transfer and validation exceed recompute in observed workloads | Use recompute by default and lazy state materialization |
| Approximate fusion fails critical instruction/grounding gates | Keep it out of the exact runtime; archive the failure |
| Cross-model mapping needs more training/transfer work than target prefill saves | Stop that mapping configuration; retain it only as a research result |
| Package provenance or compatibility cannot be established | Reject the artifact and recompile from trusted source |
| A challenger improves latency only by sacrificing unacceptable quality | Reject promotion despite favorable average speed |

Do not set a marketing speedup target before measurement. Predeclare the operational meaning of a worthwhile improvement, the quality thresholds and uncertainty handling. Report regimes where the candidate loses alongside regimes where it wins.

## Scope of confidence

High confidence: the straightforward persistent/shared KV concept has major prior art; exact activation reuse is a stricter condition than source overlap; a serving-cache key alone is not an access-control or provenance scheme.

Medium confidence: an incremental provenance and compatibility layer could be a useful local integration. That is an engineering opportunity hypothesis, not a claim that no one has built it.

Not established: universal semantic portability, general cross-tokenizer state transfer, profitable distribution on this machine, production security, or a reproducibly superior NeuralPack architecture. Search coverage is intentionally bounded and should expand when the next experiment identifies a concrete bottleneck.

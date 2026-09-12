# NeuralPack Product Pivot

## 1. Context and R&D Conclusions

The initial phase of the NeuralPack project evaluated whether context could be compiled once into a portable `.npk` KV-cache file and distributed across machines and models.

### The Old Thesis
- "Compile context once into a portable `.npk` KV container to avoid redundant prefill computation everywhere."

### The Empirical Evidence Against It
1. **Saturated Prior Art**: Native runtimes (vLLM Automatic Prefix Caching, SGLang RadixCache, LMCache) already provide production-grade GPU/CPU/NVMe multi-tier KV caching and partial-document reuse.
2. **Causal Attention Invalidates Arbitrary Chunk Reuse**: In causal models, the key-value activation of any token depends strictly on all preceding tokens. If any token before a block changes, the neural state is invalidated.
3. **Cross-Model KV Transfer Degrades Without Guarantees**: Literature reviews of 14 papers (CacheBridge, KVComm, Prompt Cache, Attention Sinks) showed that cross-model KV mapping requires expensive retraining, degrades output quality, and fails across tokenizer boundaries.
4. **Chunking Overhead**: Our incremental source benchmark demonstrated that for standard code repositories, fine-grained Content-Defined Chunking (CDC) is 5x-8x slower and uses 2x the storage of a simple file-level hashing index with SQLite FTS5.

## 2. The New Product Thesis

# NEURALPACK
## A universal context optimization layer for expensive closed and open AI models.

Rather than attempting to move neural state between machines, NeuralPack operates upstream at the context boundary between client applications and frontier model providers (NVIDIA NIM, OpenAI, Anthropic, Gemini).

```text
APPLICATION
     │
     ▼
NEURALPACK CONTEXT OPTIMIZATION LAYER
     ├── request & context structure analysis
     ├── exact & structural deduplication
     ├── prompt prefix alignment (for provider caching)
     ├── query-conditioned symbol & dependency retrieval
     ├── extractive safe compression
     ├── execution planning & quality safeguards
     ├── cost estimation & verified savings tracking
     │
     ▼
MODEL PROVIDER (NVIDIA NIM, OpenAI, Anthropic, etc.)
```

## 3. What Was Retained vs What Changed

- **Retained**:
  - All research on attention mechanics, prompt caching, and serving prior art.
  - Baseline benchmarks and failure archives.
  - Incremental source compiler and FTS5 container (`.npk`) as a fast local indexing tool.
  - Open-model research as a secondary track (`NeuralPack Native`).
- **Changed**:
  - Primary product target is **NeuralPack Edge**: a drop-in context optimization proxy for closed-model APIs.
  - First live provider implementation is **NVIDIA NIM**.
  - Core capability is the **Automatic Context Execution Planner** that selects the cheapest safe context strategy.
  - Modes supported: `baseline` (passthrough), `optimized` (cost reduction), and `shadow` (observing production requests without risk).

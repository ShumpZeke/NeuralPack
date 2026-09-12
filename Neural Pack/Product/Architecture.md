# System Architecture

```text
+-------------------------------------------------------------+
|                        Client App                           |
|           (LangChain, LlamaIndex, OpenAI SDK, Curl)         |
+-------------------------------------------------------------+
                              |  OpenAI REST / JSON
                              v
+-------------------------------------------------------------+
|                 NeuralPack Gateway (Port 8000)              |
|         /v1/chat/completions  |  /v1/models  |  /health     |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                    NeuralPack Runtime                       |
|    Modes: [baseline]       [optimized]       [shadow]       |
+-------------------------------------------------------------+
                              |
          +-------------------+-------------------+
          |                                       |
          v                                       v
+-----------------------+              +----------------------+
|   Context Optimizer   |              |  Telemetry & Traces  |
| - Structure Analyzer  |              | - Secret Redaction   |
| - Deduplicator        |              | - Traces Logger      |
| - Prefix Optimizer    |              | - Savings Analytics  |
| - Hybrid Retriever    |              +----------------------+
| - Extractive Compress |                         |
| - Execution Planner   |                         |
+-----------------------+                         |
          |                                       |
          v                                       |
+---------------------------------------------+   |
|             Provider Adapter Layer          |   |
| - NVIDIA NIM Adapter                        |   |
| - OpenAI / Anthropic Adapters (Roadmap)     |   |
| - Mock Testing Adapter                      |   |
+---------------------------------------------+   |
          |                                       |
          v HTTPS JSON                            v
+---------------------------------------------+ JSONL
|        Model Provider (e.g. NVIDIA NIM)     | Audit Traces
+---------------------------------------------+
```

## Pipeline Stages
1. **Analysis**: Classifies context into code, documentation, dialogue, or agent traces.
2. **Deduplication**: Eliminates identical blocks and repetitive license/boilerplate.
3. **Hybrid Retrieval**: Extracts symbol/dependency graphs and lexical BM25 matching blocks for the query.
4. **Prefix Alignment**: Reorders static system context to the front to maximize downstream prompt-cache hits.
5. **Planning & Risk Gate**: Evaluates whether estimated quality risk exceeds user threshold; falls back safely to raw context if uncertainty is high.
6. **Provider Dispatch**: Sends optimized request via provider adapter with retry, exponential backoff, and latency tracking.
7. **Telemetry**: Records tokens received, sent, avoided, and dollar savings computed from verified model pricing tables.

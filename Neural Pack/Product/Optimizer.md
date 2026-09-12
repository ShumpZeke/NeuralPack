# Context Optimizer & Execution Planner

The NeuralPack Context Optimizer is modular and transparent. Rather than applying a single naive compressor, it chooses the most effective combination of strategies based on the request.

## 1. Context Analyzer (`npk/context/analyzer.py`)
- Evaluates prompt length, message roles, and structure.
- Categorizes context type: `code`, `document`, `conversation`, or `agent_trace`.
- Extracts symbols (functions, classes, imports) and markdown headings.

## 2. Context Deduplicator (`npk/context/dedup.py`)
- Eliminates repeated identical paragraphs and text blocks across multiple files.
- Strips redundant license/boilerplate headers while strictly preserving code definitions.
- Emits compact pointers for repeated sections: `<!-- [Duplicate block omitted (hash: ...)] -->`.

## 3. Prompt Prefix Optimizer (`npk/context/prefix.py`)
- Reorders messages so static reference materials and system instructions appear first.
- Moves dynamic user queries to the suffix.
- Maximizes cache hits on provider prompt-caching engines (NVIDIA NIM / Anthropic / OpenAI).

## 4. Code & Document Context Retriever (`npk/context/retrieval.py`)
- Breaks multi-file prompts into individual modules.
- Applies BM25 lexical relevance scoring against the user query.
- Performs symbol dependency expansion: if a function calls `verify_token`, the defining module is automatically retained.
- Prunes completely unrelated files (e.g. graphics assets, unrelated test fixtures).

## 5. Extractive Compressor (`npk/context/compressor.py`)
- When prompts exceed 12,000 tokens, safely prunes low-relevance paragraphs and docstrings while preserving syntax anchors and function signatures.

## 6. Execution Planner & Safety Gate (`npk/planner.py`)
- Synthesizes the optimized context and generates an explainable `ExecutionPlan`.
- Checks cumulative quality risk against user threshold (default 0.05).
- If uncertainty is high, automatically executes a **safety fallback to raw context** to prevent hallucinations or wrong answers.

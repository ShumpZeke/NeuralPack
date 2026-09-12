"""Competitor Baseline Implementations for Rigorous Benchmarking."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Set, Tuple

from npk.context.analyzer import estimate_tokens
from npk.context.retrieval import BM25Scorer, CodeContextRetriever


class DenseEmbeddingSim:
    """
    Deterministic dense semantic embedding representation using character/word n-gram
    feature hashing and normalized cosine similarity.
    """
    def __init__(self, documents: List[str], dim: int = 1024):
        self.documents = documents
        self.dim = dim
        self.doc_vectors = [self._embed(d) for d in documents]

    def _embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        words = re.findall(r"\w+", text.lower())
        for w in words:
            h = hash(w) % self.dim
            vec[h] += 1.0
        # 3-gram char hashing for morphological/subword semantics
        for i in range(len(text) - 2):
            h = hash(text[i:i+3].lower()) % self.dim
            vec[h] += 0.5
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def score(self, query: str, doc_idx: int) -> float:
        q_vec = self._embed(query)
        d_vec = self.doc_vectors[doc_idx]
        return sum(a * b for a, b in zip(q_vec, d_vec))


class BaselineRunner:
    def __init__(self):
        self.retriever = CodeContextRetriever()

    def run_full_context(self, context: str, query: str) -> Tuple[str, Dict[str, Any]]:
        return context, {"tokens": estimate_tokens(context), "strategy": "full_context"}

    def run_truncation(self, context: str, query: str, token_budget: int = 2000) -> Tuple[str, Dict[str, Any]]:
        words = context.split()
        # Approximate truncation to budget
        budget_words = int(token_budget * 0.75)
        truncated = " ".join(words[:budget_words])
        return truncated, {"tokens": estimate_tokens(truncated), "strategy": "truncation"}

    def run_bm25(self, context: str, query: str, top_k: int = 3) -> Tuple[str, Dict[str, Any]]:
        blocks = self.retriever.parse_blocks(context)
        if len(blocks) <= top_k:
            return context, {"tokens": estimate_tokens(context), "strategy": "bm25"}
        scorer = BM25Scorer([b["text"] for b in blocks])
        ranked = sorted(range(len(blocks)), key=lambda i: scorer.score(query, i), reverse=True)
        kept_indices = sorted(ranked[:top_k])
        selected_text = "\n\n".join(blocks[i]["text"] for i in kept_indices)
        return selected_text, {"tokens": estimate_tokens(selected_text), "strategy": "bm25", "top_k": top_k}

    def run_dense(self, context: str, query: str, top_k: int = 3) -> Tuple[str, Dict[str, Any]]:
        blocks = self.retriever.parse_blocks(context)
        if len(blocks) <= top_k:
            return context, {"tokens": estimate_tokens(context), "strategy": "dense"}
        scorer = DenseEmbeddingSim([b["text"] for b in blocks])
        ranked = sorted(range(len(blocks)), key=lambda i: scorer.score(query, i), reverse=True)
        kept_indices = sorted(ranked[:top_k])
        selected_text = "\n\n".join(blocks[i]["text"] for i in kept_indices)
        return selected_text, {"tokens": estimate_tokens(selected_text), "strategy": "dense", "top_k": top_k}

    def run_hybrid_rrf(self, context: str, query: str, top_k: int = 3) -> Tuple[str, Dict[str, Any]]:
        """Reciprocal Rank Fusion (RRF) combining BM25 and Dense scores."""
        blocks = self.retriever.parse_blocks(context)
        if len(blocks) <= top_k:
            return context, {"tokens": estimate_tokens(context), "strategy": "hybrid_rrf"}
        bm25_scorer = BM25Scorer([b["text"] for b in blocks])
        dense_scorer = DenseEmbeddingSim([b["text"] for b in blocks])

        bm25_ranks = {idx: rank for rank, idx in enumerate(sorted(range(len(blocks)), key=lambda i: bm25_scorer.score(query, i), reverse=True))}
        dense_ranks = {idx: rank for rank, idx in enumerate(sorted(range(len(blocks)), key=lambda i: dense_scorer.score(query, i), reverse=True))}

        # Reciprocal Rank Fusion: 1 / (60 + rank)
        rrf_scores = {}
        for i in range(len(blocks)):
            rrf_scores[i] = (1.0 / (60.0 + bm25_ranks[i])) + (1.0 / (60.0 + dense_ranks[i]))

        ranked = sorted(range(len(blocks)), key=lambda i: rrf_scores[i], reverse=True)
        kept_indices = sorted(ranked[:top_k])
        selected_text = "\n\n".join(blocks[i]["text"] for i in kept_indices)
        return selected_text, {"tokens": estimate_tokens(selected_text), "strategy": "hybrid_rrf", "top_k": top_k}

"""BM25 lexical scoring engine."""
from __future__ import annotations

import math
import re
from typing import Dict, List


class BM25Scorer:
    def __init__(self, documents: List[str]):
        self.documents = documents
        self.doc_lens = [len(d.split()) for d in documents]
        self.avg_len = sum(self.doc_lens) / max(1, len(self.doc_lens))
        self.vocab: Dict[str, int] = {}
        self.doc_freqs: Dict[str, int] = {}
        for d in documents:
            words = set(re.findall(r"\w+", d.lower()))
            for w in words:
                self.doc_freqs[w] = self.doc_freqs.get(w, 0) + 1

    def score(self, query: str, doc_idx: int, k1: float = 1.5, b: float = 0.75) -> float:
        query_terms = re.findall(r"\w+", query.lower())
        score = 0.0
        doc_text = self.documents[doc_idx].lower()
        doc_len = self.doc_lens[doc_idx]
        num_docs = len(self.documents)

        for term in query_terms:
            if term not in self.doc_freqs:
                continue
            df = self.doc_freqs[term]
            idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
            tf = len(re.findall(rf"\b{re.escape(term)}\b", doc_text))
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * (doc_len / self.avg_len))
            score += idf * (numerator / max(1e-5, denominator))
        return score

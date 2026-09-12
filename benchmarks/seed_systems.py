"""Competing seed-selection systems, evaluated at matched token budgets.

The audit's central finding was ``Closure_D(emptyset) = emptyset``: dependency
expansion cannot recover evidence that seed retrieval never found. Seed quality
is therefore the binding constraint, and this module makes seed systems
swappable so they can be compared head-to-head.

Every system implements :class:`SeedSystem` and answers the same question:
*given a block list, a query and a token budget, which blocks do you return?*
The budget is enforced identically for all of them, so a comparison is never the
audited apples-to-oranges "BM25 at 200 tokens vs NeuralPack at 1,000".

Real models are used where available (see :class:`DenseSeeds` and
:class:`CrossEncoderRerankSeeds`). Nothing here calls an n-gram vector a "dense
semantic embedding" -- that mislabelling was an audit finding.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from npk.context.analyzer import estimate_tokens
from npk.context.bm25 import BM25Scorer
from npk.context.graph_slicer import ProgramGraphSlicer
from npk.context.info_gain import InformationGainSelector, content_terms

MODEL_CACHE = Path(__file__).resolve().parents[1] / "experiments" / "models" / "hf_cache"


def _fill_budget(order: Sequence[int], blocks: Sequence[Dict[str, Any]], budget: int) -> List[int]:
    """Take blocks in ranked order until the budget is exhausted."""
    kept, used = [], 0
    for i in order:
        cost = max(1, estimate_tokens(blocks[i]["text"]))
        if used + cost > budget:
            continue
        kept.append(i)
        used += cost
    return sorted(kept)


class SeedSystem:
    name = "base"
    #: True when the system needs a model that may be unavailable offline.
    requires_model = False

    def available(self) -> bool:
        return True

    def select(self, blocks: List[Dict[str, Any]], query: str, budget: int) -> List[int]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Lexical
# ---------------------------------------------------------------------------

class BM25Seeds(SeedSystem):
    """Tuned BM25 top-k, filling the budget greedily by score."""

    name = "bm25_tuned"

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b

    def select(self, blocks, query, budget):
        scorer = BM25Scorer([b["text"] for b in blocks])
        scores = [scorer.score(query, i, k1=self.k1, b=self.b) for i in range(len(blocks))]
        order = sorted(range(len(blocks)), key=lambda i: -scores[i])
        return _fill_budget(order, blocks, budget)


class SymbolExactSeeds(SeedSystem):
    """Exact identifier lookup -- the 'competent grep' baseline."""

    name = "symbol_exact"

    def select(self, blocks, query, budget):
        idents = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", query))
        idents |= {t for t in content_terms(query)}
        scored = []
        for i, blk in enumerate(blocks):
            text = blk["text"]
            hits = sum(1 for ident in idents if ident in text)
            if hits:
                scored.append((hits, -estimate_tokens(text), i))
        scored.sort(reverse=True)
        return _fill_budget([i for *_x, i in scored], blocks, budget)


# ---------------------------------------------------------------------------
# Neural
# ---------------------------------------------------------------------------

class DenseSeeds(SeedSystem):
    """Real bi-encoder embeddings (all-MiniLM-L6-v2), mean-pooled.

    This is a genuine transformer embedding model running locally. Because
    NeuralPack targets expensive CLOSED models, spending local GPU/CPU here is
    nearly free relative to the closed-model input tokens it saves.
    """

    name = "dense_minilm"
    requires_model = True
    _model = None
    _tok = None

    MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

    def _load(self):
        if DenseSeeds._model is not None:
            return True
        try:
            import torch  # noqa: F401
            from transformers import AutoModel, AutoTokenizer
            kw = {"cache_dir": str(MODEL_CACHE)} if MODEL_CACHE.exists() else {}
            DenseSeeds._tok = AutoTokenizer.from_pretrained(self.MODEL_ID, **kw)
            DenseSeeds._model = AutoModel.from_pretrained(self.MODEL_ID, **kw).eval()
            return True
        except Exception:
            return False

    def available(self) -> bool:
        return self._load()

    _emb_cache: Dict[str, Any] = {}

    def _embed(self, texts: List[str]):
        import hashlib
        import torch
        key = hashlib.sha256("|NPKSEP|".join(texts).encode("utf-8", "ignore")).hexdigest()
        cached = DenseSeeds._emb_cache.get(key)
        if cached is not None:
            return cached
        out = []
        bs = 16
        with torch.no_grad():
            for s in range(0, len(texts), bs):
                batch = texts[s:s + bs]
                enc = DenseSeeds._tok(batch, padding=True, truncation=True,
                                      max_length=256, return_tensors="pt")
                hidden = DenseSeeds._model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).float()
                emb = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)
                out.append(emb)
        result = torch.cat(out, 0)
        # Budget sweeps re-embed the same blocks many times; cache by content.
        if len(DenseSeeds._emb_cache) > 64:
            DenseSeeds._emb_cache.clear()
        DenseSeeds._emb_cache[key] = result
        return result

    def select(self, blocks, query, budget):
        if not self._load():
            raise RuntimeError("dense model unavailable")
        import torch
        doc_emb = self._embed([b["text"][:2000] for b in blocks])
        q_emb = self._embed([query])
        sims = (doc_emb @ q_emb.T).squeeze(1)
        order = torch.argsort(sims, descending=True).tolist()
        return _fill_budget(order, blocks, budget)


class HybridRRFSeeds(SeedSystem):
    """Reciprocal-rank fusion of BM25 and real dense embeddings."""

    name = "hybrid_rrf"
    requires_model = True

    def __init__(self, k: int = 60):
        self.k = k
        self.bm25 = BM25Seeds()
        self.dense = DenseSeeds()

    def available(self) -> bool:
        return self.dense.available()

    def select(self, blocks, query, budget):
        scorer = BM25Scorer([b["text"] for b in blocks])
        bm_scores = [scorer.score(query, i) for i in range(len(blocks))]
        bm_rank = {i: r for r, i in enumerate(sorted(range(len(blocks)), key=lambda i: -bm_scores[i]))}

        import torch
        doc_emb = self.dense._embed([b["text"][:2000] for b in blocks])
        q_emb = self.dense._embed([query])
        sims = (doc_emb @ q_emb.T).squeeze(1)
        dn_rank = {i: r for r, i in enumerate(torch.argsort(sims, descending=True).tolist())}

        fused = sorted(range(len(blocks)),
                       key=lambda i: -(1.0 / (self.k + bm_rank[i]) + 1.0 / (self.k + dn_rank[i])))
        return _fill_budget(fused, blocks, budget)


class CrossEncoderRerankSeeds(SeedSystem):
    """BM25 candidate generation + a real cross-encoder reranker."""

    name = "bm25_plus_cross_encoder"
    requires_model = True
    _model = None
    _tok = None
    MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, candidates: int = 40):
        self.candidates = candidates

    def _load(self):
        if CrossEncoderRerankSeeds._model is not None:
            return True
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            kw = {"cache_dir": str(MODEL_CACHE)} if MODEL_CACHE.exists() else {}
            CrossEncoderRerankSeeds._tok = AutoTokenizer.from_pretrained(self.MODEL_ID, **kw)
            CrossEncoderRerankSeeds._model = AutoModelForSequenceClassification.from_pretrained(
                self.MODEL_ID, **kw).eval()
            return True
        except Exception:
            return False

    def available(self) -> bool:
        return self._load()

    def select(self, blocks, query, budget):
        if not self._load():
            raise RuntimeError("cross-encoder unavailable")
        import torch
        scorer = BM25Scorer([b["text"] for b in blocks])
        bm = [scorer.score(query, i) for i in range(len(blocks))]
        cand = sorted(range(len(blocks)), key=lambda i: -bm[i])[: self.candidates]

        pairs = [(query, blocks[i]["text"][:1500]) for i in cand]
        scores = []
        with torch.no_grad():
            for s in range(0, len(pairs), 16):
                batch = pairs[s:s + 16]
                enc = CrossEncoderRerankSeeds._tok(
                    [p[0] for p in batch], [p[1] for p in batch],
                    padding=True, truncation=True, max_length=384, return_tensors="pt")
                logits = CrossEncoderRerankSeeds._model(**enc).logits.squeeze(-1)
                scores.extend(logits.tolist())

        order = [i for _s, i in sorted(zip(scores, cand), key=lambda t: -t[0])]
        order += [i for i in range(len(blocks)) if i not in set(cand)]
        return _fill_budget(order, blocks, budget)


# ---------------------------------------------------------------------------
# NeuralPack
# ---------------------------------------------------------------------------

class NeuralPackSeeds(SeedSystem):
    """NeuralPack's information-gain selector, without graph expansion."""

    name = "npk_selector"

    def __init__(self, strategy: str = "relative"):
        self.strategy = strategy

    def select(self, blocks, query, budget):
        slicer = ProgramGraphSlicer()
        edges, _ = slicer.build_dependency_graph(blocks)
        sel = InformationGainSelector(strategy=self.strategy)
        outcome = sel.select(blocks, query, edges, token_budget=budget)
        if outcome.seed_failed:
            return []
        return outcome.kept_indices


class NeuralPackGraphSeeds(SeedSystem):
    """NeuralPack selector followed by budget-aware dependency expansion.

    Isolates the contribution of program-structure expansion over the same seeds.
    """

    name = "npk_selector_plus_graph"

    def __init__(self, strategy: str = "relative", depth: int = 3, seed_fraction: float = 0.6):
        self.strategy = strategy
        self.depth = depth
        #: Reserve part of the budget for expansion so the comparison is fair.
        self.seed_fraction = seed_fraction

    def select(self, blocks, query, budget):
        slicer = ProgramGraphSlicer()
        edges, _ = slicer.build_dependency_graph(blocks)
        costs = [max(1, estimate_tokens(b["text"])) for b in blocks]
        sel = InformationGainSelector(strategy=self.strategy)
        outcome = sel.select(blocks, query, edges, token_budget=int(budget * self.seed_fraction))
        if outcome.seed_failed:
            return []
        reached = slicer.compute_transitive_closure(
            set(outcome.kept_indices), edges, max_depth=self.depth,
            block_costs=costs, token_budget=budget,
        )
        return sorted(reached)


class GraphOnTopSeeds(SeedSystem):
    """Any seed system + budget-aware dependency expansion.

    Used to answer the differentiation question directly: does program-structure
    expansion add anything ON TOP OF a strong modern retriever?
    """

    def __init__(self, base: SeedSystem, depth: int = 3, seed_fraction: float = 0.6):
        self.base = base
        self.depth = depth
        self.seed_fraction = seed_fraction
        self.name = f"{base.name}+graph"
        self.requires_model = base.requires_model

    def available(self) -> bool:
        return self.base.available()

    def select(self, blocks, query, budget):
        seeds = self.base.select(blocks, query, int(budget * self.seed_fraction))
        if not seeds:
            return []
        slicer = ProgramGraphSlicer()
        edges, _ = slicer.build_dependency_graph(blocks)
        costs = [max(1, estimate_tokens(b["text"])) for b in blocks]
        reached = slicer.compute_transitive_closure(
            set(seeds), edges, max_depth=self.depth,
            block_costs=costs, token_budget=budget,
        )
        return sorted(reached)


def all_systems(include_models: bool = True) -> List[SeedSystem]:
    systems: List[SeedSystem] = [
        BM25Seeds(),
        SymbolExactSeeds(),
        NeuralPackSeeds(),
        NeuralPackGraphSeeds(),
        GraphOnTopSeeds(BM25Seeds()),
    ]
    if include_models:
        systems += [DenseSeeds(), HybridRRFSeeds(), CrossEncoderRerankSeeds(),
                    GraphOnTopSeeds(HybridRRFSeeds())]
    return systems

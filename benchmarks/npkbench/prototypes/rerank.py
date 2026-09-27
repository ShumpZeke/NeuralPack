"""E045 prototype: a neural cross-encoder reorders the product's top candidates.

At small budgets only the first few fused candidates fit, and the first gold
block is ranked first for only 38 of 103 dev-fast issues under the E039 default.
E011 showed that re-weighting the existing channels' features cannot fix this;
a cross-encoder reads the query and each candidate together, which is new
evidence. Here the top ``k`` fused blocks are re-scored by a cross-encoder and
reordered; every block below ``k``, the test mate (gated at 2K, placed after the
reordering) and the fill are the product's.

Models load offline from experiments/models/hf_cache (pinned revisions,
safetensors, no remote code): ``minilm`` = cross-encoder/ms-marco-MiniLM-L-6-v2
(Apache-2.0, 22M parameters), ``bge`` = BAAI/bge-reranker-base (MIT, 278M).
Opt-in material at best: scoring 10 pairs costs tens to hundreds of milliseconds.
"""
from __future__ import annotations

import importlib
import os
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

sel = importlib.import_module("npk.pack.select")
CACHE = Path(__file__).resolve().parents[3] / "experiments" / "models" / "hf_cache"
MODELS = {
    "minilm": ("cross-encoder/ms-marco-MiniLM-L-6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a"),
    "bge": ("BAAI/bge-reranker-base", "2cfc18c9415c912f9d8155881c133215df768a70"),
}
_LOADED: Dict[str, tuple] = {}


def _model(name: str):
    if name not in _LOADED:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        torch.set_num_threads(int(os.environ.get("NPK_DENSE_THREADS", "1")))
        repo, rev = MODELS[name]
        kw = {"local_files_only": True, "trust_remote_code": False, "cache_dir": str(CACHE), "revision": rev}
        tok = AutoTokenizer.from_pretrained(repo, **kw)
        model = AutoModelForSequenceClassification.from_pretrained(repo, use_safetensors=True, **kw).eval()
        _LOADED[name] = (tok, model)
    return _LOADED[name]


def scores(name: str, query: str, texts: Sequence[str]) -> List[float]:
    import torch
    tok, model = _model(name)
    q = query[:1200]
    with torch.no_grad():
        enc = tok([q] * len(texts), [t[:2000] for t in texts], padding=True, truncation="longest_first",
                  max_length=512, return_tensors="pt")
        logits = model(**enc).logits
    return logits.view(-1).tolist()


class RerankSelector(PackSelector):
    model_name = "minilm"
    k = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, enable_test_mate=True, **kwargs)
        self._budget = 0
        self._scores: Dict[tuple, float] = {}

    def _select_once(self, con, manifest, query, budget, limit):
        self._budget = budget
        return super()._select_once(con, manifest, query, budget, limit)

    def _place_test_mate(self, con, manifest, query, ordered_ids, fused, channels_of, deep=None):
        head = ordered_ids[:self.k]
        missing = [b for b in head if (query, b) not in self._scores]
        if missing:
            marks = ",".join("?" * len(missing))
            texts = dict(con.execute(f"SELECT id, text FROM blocks WHERE id IN ({marks})", missing).fetchall())
            for block_id, score in zip(missing, scores(self.model_name, query, [texts[b] for b in missing])):
                self._scores[(query, block_id)] = score
        order = sorted(range(len(head)), key=lambda i: (-self._scores[(query, head[i])], i))
        ordered_ids = [head[i] for i in order] + ordered_ids[self.k:]
        if self._budget >= sel.TEST_MATE_MIN_BUDGET:
            ordered_ids = super()._place_test_mate(con, manifest, query, ordered_ids, fused, channels_of, deep)
        return ordered_ids


def make(name: str, model: str, k: int) -> Arm:
    cls = type(f"Rerank_{model}_{k}", (RerankSelector,), {"model_name": model, "k": k})

    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        out: Dict[int, ArmResult] = {}
        with cls(str(pack), enable_cache=False) as selector:
            for budget in budgets:
                started = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e045_minilm_top10", "minilm", 10)
make("e045_bge_top10", "bge", 10)
make("e045_control", "minilm", 1)   # k=1 reorders nothing: must equal npk_default

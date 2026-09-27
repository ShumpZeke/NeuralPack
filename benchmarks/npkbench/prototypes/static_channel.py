"""E038 prototype: static (Model2Vec) embeddings as a semantic channel for code.

E012b found that a dense channel inside the product's RRF helps from 2K
(bge-small, dev-fast utility +4.3/+3.0/+8.0/+8.4 points at 2K-16K) but costs
too much on CPU: seconds per cold query, or 10+ minutes of compile time per
Django snapshot. Static embeddings (Model2Vec ``potion`` models, distilled from
bge-base: a token-embedding table, mean-pooled and normalized) need no
transformer at all; encoding a block is a tokenizer call and an average.

Arms (all keep the product's lexical, definition and relation channels, fill,
trimming and gated test mate; the static order enters the RRF as one channel,
through the hybrid-mode hook, with the symbol channel disabled, as in E012b):

* ``e038_pool8m`` / ``e038_pool32m``: rank the product's top-100 pool with
  potion-base-8M (256-d) / potion-retrieval-32M (512-d), E012b's form.
* ``e038_full32m``: rank every block in the pack with potion-retrieval-32M
  (a compile-time index in product form), so candidates outside the lexical
  pool can enter.

Models load offline from experiments/models/hf_cache (MIT licence; pinned
revisions), safetensors only.
"""
from __future__ import annotations

import contextlib
import importlib
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from npk.pack import PackSelector
from npk.pack.format import open_pack

from ..arms import Arm, ArmResult, _span, register
from ..data import Task

select_module = importlib.import_module("npk.pack.select")
CACHE = Path(__file__).resolve().parents[3] / "experiments" / "models" / "hf_cache"
MODELS = {
    "potion8m": ("minishlab/potion-base-8M", "bf8b056651a2c21b8d2565580b8569da283cab23"),
    "potion32m": ("minishlab/potion-retrieval-32M", "6fc8051fab2a1e0ee76689cf08c853792ac285e7"),
}
_LOADED: Dict[str, tuple] = {}
_PACK_INDEX: Dict[Tuple[str, str], tuple] = {}


def _model(name: str):
    if name not in _LOADED:
        from safetensors.numpy import load_file
        from tokenizers import Tokenizer
        repo, rev = MODELS[name]
        root = CACHE / ("models--" + repo.replace("/", "--")) / "snapshots" / rev
        table = load_file(str(root / "model.safetensors"))["embeddings"]
        tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        _LOADED[name] = (table, tokenizer, tokenizer.token_to_id("[UNK]"))
    return _LOADED[name]


def encode(name: str, texts: Sequence[str]):
    import numpy as np
    table, tokenizer, unk = _model(name)
    out = np.zeros((len(texts), table.shape[1]), dtype=np.float32)
    for start in range(0, len(texts), 512):
        batch = tokenizer.encode_batch(list(texts[start:start + 512]), add_special_tokens=False)
        for offset, enc in enumerate(batch):
            ids = [i for i in enc.ids if i != unk]
            if ids:
                out[start + offset] = table[ids].mean(axis=0)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(norms, 1e-12)


def _pack_index(pack: Path, name: str):
    key = (str(pack), name)
    if key not in _PACK_INDEX:
        with open_pack(pack) as con:
            rows = con.execute("SELECT id, text FROM blocks ORDER BY id").fetchall()
        _PACK_INDEX.clear()   # one pack at a time per worker
        _PACK_INDEX[key] = ([r[0] for r in rows], encode(name, [r[1] for r in rows]))
    return _PACK_INDEX[key]


@contextlib.contextmanager
def _dense_hooks(dense_ids: List[int]):
    original = (select_module._embedding_channel, select_module._symbol_channel)
    select_module._embedding_channel = lambda con, query, limit, manifest: (list(dense_ids[:limit]), None)
    select_module._symbol_channel = lambda con, query, limit: []
    try:
        yield
    finally:
        select_module._embedding_channel, select_module._symbol_channel = original


def make(name: str, model: str, *, pool: int = 100, full: bool = False) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        query_vec = encode(model, [task.query])[0]
        if full:
            ids, matrix = _pack_index(pack, model)
            sims = matrix @ query_vec
            top = sims.argsort()[::-1][:pool]
            dense_ids = [ids[i] for i in sorted(top, key=lambda i: (-sims[i], ids[i]))]
        else:
            with PackSelector(str(pack), enable_cache=False, candidate_limit=pool) as selector:
                ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence[:pool]
            sims = encode(model, [e.text for e in ranked]) @ query_vec if ranked else []
            dense_ids = [ranked[i].block_id for i in sorted(range(len(ranked)), key=lambda i: (-sims[i], i))]
        prep_ms = (time.perf_counter() - started) * 1000
        out: Dict[int, ArmResult] = {}
        with _dense_hooks(dense_ids), PackSelector(str(pack), enable_cache=False, retrieval="hybrid") as selector:
            for budget in budgets:
                t0 = time.perf_counter()
                selection = selector.select(task.query, budget_tokens=budget)
                out[budget] = ArmResult(
                    spans=[_span(e) for e in selection.evidence], tokens=selection.total_tokens,
                    latency_ms=prep_ms + (time.perf_counter() - t0) * 1000,
                    status="fallback_required" if selection.seed_failed or not selection.evidence else "selected",
                    n_blocks=len(selection.evidence))
        return out

    return register(Arm(name, runner=runner))


make("e038_pool8m", "potion8m")
make("e038_pool32m", "potion32m")
make("e038_full32m", "potion32m", full=True)

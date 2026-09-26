"""H11/E012 prototype: dense similarity as a new evidence channel over the pool.

E011 showed that reweighting existing channels cannot close the ranking gap
(gold is first for 36% of issues but in the top-100 pool for 79%). Dense
query-block similarity is evidence those channels do not contain. To keep the
experiment cheap and product-shaped, only the product's fused pool (top 100)
is embedded, with a content-addressed vector cache (model, SHA-256 of text)
so unchanged blocks across snapshots of one repository are embedded once.
The dense rank joins the pool's RRF as one more channel.

Models load offline from experiments/models/hf_cache, safetensors only, no
remote code (the product's encoder policy).
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Sequence

from npk.pack import PackSelector
from npk.pack.select import RRF_K

from ..arms import Arm, ArmResult, register
from ..data import HOME, Task

CACHE_DIR = Path(__file__).resolve().parents[3] / "experiments" / "models" / "hf_cache"
MODELS = {
    "minilm": ("sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41", 256, ""),
    "bge_small": ("BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", 512,
                  "Represent this sentence for searching relevant passages: "),
}
VECTORS = HOME / "vectors.sqlite"
_LOCAL = threading.local()
_MODELS: Dict[str, tuple] = {}


def _db():
    con = getattr(_LOCAL, "db", None)
    if con is None:
        VECTORS.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(VECTORS, timeout=60)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS v(model TEXT, sha TEXT, vec BLOB, PRIMARY KEY(model, sha))")
        _LOCAL.db = con
    return con


def _model(name: str):
    if name not in _MODELS:
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(int(os.environ.get("NPK_DENSE_THREADS", "1")))
        repo, rev, max_len, _prefix = MODELS[name]
        kw = {"local_files_only": True, "trust_remote_code": False, "cache_dir": str(CACHE_DIR), "revision": rev}
        tok = AutoTokenizer.from_pretrained(repo, **kw)
        model = AutoModel.from_pretrained(repo, use_safetensors=True, **kw).eval()
        _MODELS[name] = (tok, model, max_len)
    return _MODELS[name]


def _encode(name: str, texts: List[str]):
    import numpy as np
    import torch
    tok, model, max_len = _model(name)
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 16):
            enc = tok(texts[i:i + 16], padding=True, truncation=True, max_length=max_len, return_tensors="pt")
            hidden = model(**enc).last_hidden_state
            if name == "bge_small":  # CLS pooling, as trained
                pooled = hidden[:, 0]
            else:
                mask = enc["attention_mask"].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            out.append(torch.nn.functional.normalize(pooled, p=2, dim=1).numpy().astype(np.float32))
    return np.vstack(out)


def vectors(name: str, texts: Sequence[str]):
    import numpy as np
    shas = [hashlib.sha256(t.encode("utf-8", "surrogatepass")).hexdigest() for t in texts]
    db = _db()
    found = {}
    for i in range(0, len(shas), 500):
        chunk = shas[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for sha, vec in db.execute(f"SELECT sha, vec FROM v WHERE model=? AND sha IN ({marks})", (name, *chunk)):
            found[sha] = np.frombuffer(vec, dtype=np.float32)
    missing = [i for i, s in enumerate(shas) if s not in found]
    if missing:
        fresh = _encode(name, [texts[i] for i in missing])
        rows = [(name, shas[i], fresh[j].tobytes()) for j, i in enumerate(missing)]
        db.executemany("INSERT OR IGNORE INTO v(model, sha, vec) VALUES(?,?,?)", rows)
        db.commit()
        for j, i in enumerate(missing):
            found[shas[i]] = fresh[j]
    return np.vstack([found[s] for s in shas])


def make(name: str, model: str, *, dense_k: int = RRF_K, pool: int = 100) -> Arm:
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        started = time.perf_counter()
        with PackSelector(str(pack), enable_cache=False, candidate_limit=pool) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence[:pool]
        prefix = MODELS[model][3]
        q = vectors(model, [prefix + task.query])[0]
        docs = vectors(model, [e.text for e in ranked])
        sims = docs @ q
        dense_order = sorted(range(len(ranked)), key=lambda i: (-sims[i], i))
        fused = {i: 1.0 / (RRF_K + i) for i in range(len(ranked))}
        for r, i in enumerate(dense_order):
            fused[i] += 1.0 / (dense_k + r)
        order = sorted(fused, key=lambda i: (-fused[i], i))
        elapsed = (time.perf_counter() - started) * 1000
        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for i in order:
                ev = ranked[i]
                extra = len(ev.text) + (2 if n else 0)
                if max(1, (used + extra) // 4) > budget:
                    continue
                used, n = used + extra, n + 1
                lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
                spans.append((ev.path, lo, hi))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, elapsed,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


def make_pool_control(name: str, pool: int = 100) -> Arm:
    """Same pool and whole-block fill without the dense channel."""
    def runner(pack: Path, task: Task, budgets: Sequence[int]) -> Dict[int, ArmResult]:
        with PackSelector(str(pack), enable_cache=False, candidate_limit=pool) as selector:
            ranked = selector.select(task.query, budget_tokens=10**9, allow_escalation=False).evidence[:pool]
        out = {}
        for budget in budgets:
            spans, used, n = [], 0, 0
            for ev in ranked:
                extra = len(ev.text) + (2 if n else 0)
                if max(1, (used + extra) // 4) > budget:
                    continue
                used, n = used + extra, n + 1
                lo, hi = map(int, ev.span.rsplit(":", 1)[1].split("-"))
                spans.append((ev.path, lo, hi))
            out[budget] = ArmResult(spans, max(1, used // 4) if n else 0, 0.0,
                                    "selected" if n else "fallback_required", n)
        return out

    return register(Arm(name, runner=runner))


make_pool_control("e012_pool_control")
make("e012_minilm", "minilm")
make("e012_bge", "bge_small")
make("e012_bge_k30", "bge_small", dense_k=30)

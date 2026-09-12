"""Optional offline sentence encoder. No generative model or runtime downloads.

Old headline retention/cost claims are withdrawn; see EVOLUTION_LOG.md. An
encoder is an experimental retrieval channel, not evidence-sufficiency proof.
Missing local weights leave the deterministic path available. Install weights
separately; runtime loading never enables remote code or fetches missing files.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
import os
from pathlib import Path
import threading
import re
from typing import Any, Dict, List, Optional, Sequence

#: Small, permissively licensed, widely used sentence embedding model.
DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DOCUMENT_CHAR_LIMIT = 2000

#: Where the repo caches downloaded weights.
MODEL_CACHE = Path(__file__).resolve().parents[2] / "experiments" / "models" / "hf_cache"

#: Set to "0" to disable escalation entirely (e.g. in constrained deployments).
ENV_ENABLE = "NPK_ENABLE_EMBEDDINGS"


class LocalEmbeddingBackend:
    """Lazily-loaded local sentence embedder.

    Model, failure state and bounded cache belong to this instance. The default
    factory reuses one instance; separately configured encoders never share state.
    """

    _CACHE_LIMIT = 64
    _CACHE_BUDGET_BYTES = 16 * 1024 * 1024

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, max_length: int = 256,
                 *, revision: Optional[str] = None):
        if not isinstance(model_id,str) or not model_id.strip():
            raise ValueError("model_id must be a nonempty string")
        if type(max_length) is not int or max_length <= 0:
            raise ValueError("max_length must be a positive integer")
        if revision is not None and (not isinstance(revision,str) or not re.fullmatch(r"[0-9a-f]{40}",revision)):
            raise ValueError("revision must be an exact 40-character commit hash")
        self._model_id = model_id
        self._max_length = max_length
        self._revision = revision or (DEFAULT_MODEL_REVISION if model_id==DEFAULT_MODEL_ID else None)
        self._resolved_revision = None
        self._lock = threading.RLock()
        self._model = self._tokenizer = None
        self._load_attempted = False
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._cache_bytes = 0

    @property
    def model_id(self):
        return self._model_id

    @property
    def max_length(self):
        return self._max_length

    def identity(self) -> Optional[Dict[str, Any]]:
        """Describe the embedding space, or None if revision identity is unknown.

        Commit identity assumes the installed local model cache is trusted; this
        does not authenticate external weight bytes or the installed libraries.
        """
        if not self.available() or not re.fullmatch(r"[0-9a-f]{40}",self._resolved_revision or ""):
            return None
        return {"version":1,"model_id":self.model_id,"revision":self._resolved_revision,
                "max_length":self.max_length,"pooling":"mask_mean_l2_v1",
                "document_char_limit":DOCUMENT_CHAR_LIMIT}

    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        return os.environ.get(ENV_ENABLE, "1") not in {"0", "false", "False"}

    def available(self) -> bool:
        """True when the model can actually be used. Never raises."""
        if not self.enabled():
            return False
        return self._load()

    def _load(self) -> bool:
        with self._lock:
            if self._model is not None:
                return True
            if self._load_attempted:
                return False
            self._load_attempted = True
            try:
                import torch  # noqa: F401
                from transformers import AutoModel, AutoTokenizer

                kwargs = {"local_files_only":True,"trust_remote_code":False}
                if MODEL_CACHE.exists():
                    kwargs["cache_dir"] = str(MODEL_CACHE)
                if self._revision:
                    kwargs["revision"] = self._revision
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id, **kwargs)
                self._model = AutoModel.from_pretrained(
                    self.model_id, use_safetensors=True, **kwargs).eval()
                self._resolved_revision = getattr(self._model.config,"_commit_hash",None)
                if self._revision and self._resolved_revision != self._revision:
                    raise ValueError("loaded model revision disagrees with requested revision")
                return True
            except Exception:
                self._model = self._tokenizer = None
                self._resolved_revision = None
                return False

    # ------------------------------------------------------------------
    def _embed(self, texts: Sequence[str]):
        with self._lock:
            return self._embed_locked(texts)

    def _cache_key(self, texts: Sequence[str]) -> str:
        # JSON frames every list element and preserves escaped Unicode; a text
        # containing the old delimiter cannot alias a different batch shape.
        framed=json.dumps([self.model_id,self._resolved_revision,self.max_length,list(texts)],
                          ensure_ascii=True,separators=(",",":"))
        return hashlib.sha256(framed.encode("ascii")).hexdigest()

    def _embed_locked(self, texts: Sequence[str]):
        import torch

        key = self._cache_key(texts)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        chunks = []
        batch_size = 16
        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = list(texts[start:start + batch_size])
                enc = self._tokenizer(
                    batch, padding=True, truncation=True,
                    max_length=self.max_length, return_tensors="pt")
                hidden = self._model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                chunks.append(torch.nn.functional.normalize(pooled, p=2, dim=1))

        result = torch.cat(chunks, 0)
        size=result.numel()*result.element_size()
        if size <= self._CACHE_BUDGET_BYTES:
            while self._cache and (len(self._cache)>=self._CACHE_LIMIT or self._cache_bytes+size>self._CACHE_BUDGET_BYTES):
                _, evicted=self._cache.popitem(last=False)
                self._cache_bytes -= evicted.numel()*evicted.element_size()
            self._cache[key] = result
            self._cache_bytes += size
        return result

    def score_blocks(self, block_texts: Sequence[str], query: str,
                     char_limit: int = 2000) -> Optional[List[float]]:
        """Cosine similarity of each block to *query*, or ``None`` if unavailable."""
        if not block_texts or not self.available():
            return None
        try:
            doc = self._embed([t[:char_limit] for t in block_texts])
            qry = self._embed([query])
            sims = (doc @ qry.T).squeeze(1)
            return [float(x) for x in sims]
        except Exception:
            return None


    def embed_matrix(self, texts: Sequence[str]) -> Optional[List[List[float]]]:
        """Embed *texts* into plain float rows, or ``None`` if unavailable.

        Used at COMPILE time to populate a ``.npk`` embedding index, so query
        time never has to embed the corpus again.
        """
        if not texts or not self.available():
            return None
        try:
            matrix = self._embed(list(texts))
            return [[float(x) for x in row] for row in matrix]
        except Exception:
            return None

    def embed_query(self, query: str) -> Optional[List[float]]:
        """Embed a single query. This is the only per-query model call, and it
        is a small local encoder -- never a generative model."""
        rows = self.embed_matrix([query])
        return rows[0] if rows else None


#: Module-level default instance.
_DEFAULT_BACKEND: Optional[LocalEmbeddingBackend] = None
_DEFAULT_LOCK = threading.Lock()


def get_backend() -> LocalEmbeddingBackend:
    global _DEFAULT_BACKEND
    with _DEFAULT_LOCK:
        if _DEFAULT_BACKEND is None:
            _DEFAULT_BACKEND = LocalEmbeddingBackend()
    return _DEFAULT_BACKEND


def embeddings_available() -> bool:
    return get_backend().available()

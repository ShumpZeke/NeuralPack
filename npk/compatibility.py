"""Conservative context-state identity. No implied cross-model translation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import struct
from typing import Sequence


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ModelIdentity:
    weights_sha256: str
    tokenizer_sha256: str
    architecture: str
    layers: int
    kv_heads: int
    head_dim: int
    rope: str
    quantization: str
    dtype: str
    runtime: str
    attention_implementation: str
    adapter_sha256: str = "none"
    layout: str = "batch,kv_head,sequence,head_dim"

    def __post_init__(self):
        for name in ("weights_sha256", "tokenizer_sha256"):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a full lowercase SHA-256 digest")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
               for value in (self.layers, self.kv_heads, self.head_dim)):
            raise ValueError("Invalid model dimensions")
        if any(not str(value) for value in asdict(self).values()):
            raise ValueError("Identity fields must be explicit")

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))


def prefix_key(model: ModelIdentity, token_ids: Sequence[int], *, namespace: str,
               attention_mask_hash: str = "full-causal", position_offset: int = 0) -> str:
    """Rendered system/user tokens must be included; source chunk hashes are insufficient.

    A namespace is part of identity, not an ACL or encryption mechanism. The caller
    must authorize access at the backing store as well.
    """
    if (not isinstance(namespace, str) or not namespace or not isinstance(attention_mask_hash, str)
            or not attention_mask_hash or isinstance(position_offset, bool)
            or not isinstance(position_offset, int) or position_offset < 0):
        raise ValueError("Explicit namespace and nonnegative positions required")
    tokens = hashlib.sha256()
    for token in token_ids:
        if isinstance(token, bool) or not isinstance(token, int) or token < 0 or token > 2**32 - 1:
            raise ValueError("Tokens must be unsigned 32-bit integers")
        tokens.update(struct.pack("<I", token))
    return digest({"model": model.fingerprint, "tokens": tokens.hexdigest(), "count": len(token_ids),
                   "namespace": namespace, "mask": attention_mask_hash, "offset": position_offset})


def reusable_prefix_tokens(old: Sequence[int], new: Sequence[int]) -> int:
    """Causal full-attention lower bound: discard neural state from first changed token.

    Assumes an otherwise identical identity, mask and positions. Append can reuse all
    old tokens. Text-byte overlap says nothing about these token boundaries.
    """
    for index, (left, right) in enumerate(zip(old, new)):
        if left != right:
            return index
    return min(len(old), len(new))

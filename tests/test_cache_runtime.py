"""CPU-only cache-format/restart checks; no model load or download."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from benchmarks.model_baseline import as_cache, cache_tensors, quantize, save_cache
from benchmarks.model_quality import (
    cache_identity, common_token_prefix, crop_tensors,
    load_validated_cache, tensor_schema,
)


@pytest.fixture
def tiny_cache():
    return {f"{layer:03d}.{kind}": torch.arange(40, dtype=torch.float32).reshape(1, 2, 5, 4) / 10 + layer
            for layer in range(2) for kind in ("k", "v")}


def test_fresh_process_reads_cache_and_validates_dimensions(tmp_path, tiny_cache):
    path = tmp_path / "cache.safetensors"
    identity = cache_identity("checkpoint-A", torch.tensor([[1, 2, 3, 4, 5]]))
    manifest = save_cache(path, tiny_cache, identity)
    schema = tensor_schema(tiny_cache)
    script = """
import json, sys
from pathlib import Path
from benchmarks.model_quality import load_validated_cache, tensor_schema
values = load_validated_cache(Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]))
print(json.dumps({'schema': tensor_schema(values), 'sum': sum(float(t.sum()) for t in values.values())}))
"""
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "HF_HUB_OFFLINE": "1"}
    result = subprocess.run([sys.executable, "-c", script, str(path), identity, json.dumps(schema)],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, check=True, timeout=45)
    actual = json.loads(result.stdout)
    assert actual["schema"] == schema
    assert actual["sum"] == sum(float(value.sum()) for value in tiny_cache.values())
    assert manifest["bytes"] == path.stat().st_size
    assert len(manifest["sha256"]) == 64


@pytest.mark.parametrize("model,tokens", [("checkpoint-B", [1, 2, 3, 4, 5]),
                                          ("checkpoint-A", [1, 2, 9, 4, 5])])
def test_wrong_model_or_prefix_rejected(tmp_path, tiny_cache, model, tokens):
    path = tmp_path / "cache.safetensors"
    identity = cache_identity("checkpoint-A", torch.tensor([[1, 2, 3, 4, 5]]))
    save_cache(path, tiny_cache, identity)
    wrong = cache_identity(model, torch.tensor([tokens]))
    with pytest.raises(ValueError, match="identity"):
        load_validated_cache(path, wrong, tensor_schema(tiny_cache))


@pytest.mark.parametrize("mutation", ["flip", "truncate"])
def test_corrupt_cache_rejected_before_tensor_load(tmp_path, tiny_cache, mutation):
    path = tmp_path / "cache.safetensors"
    save_cache(path, tiny_cache, "identity")
    data = bytearray(path.read_bytes())
    if mutation == "flip":
        data[-1] ^= 1
    else:
        data = data[:-7]
    path.write_bytes(data)
    with pytest.raises(ValueError, match="Corrupt"):
        load_validated_cache(path, "identity", tensor_schema(tiny_cache))


def test_valid_hash_but_wrong_expected_dimensions_rejected(tmp_path, tiny_cache):
    path = tmp_path / "cache.safetensors"
    schema = tensor_schema(tiny_cache)
    schema["000.k"]["shape"][2] = 6
    save_cache(path, tiny_cache, "identity")
    with pytest.raises(ValueError, match="schema"):
        load_validated_cache(path, "identity", schema)


def test_nonfinite_cache_rejected(tmp_path, tiny_cache):
    path = tmp_path / "cache.safetensors"
    tiny_cache["000.k"][0, 0, 0, 0] = float("nan")
    save_cache(path, tiny_cache, "identity")
    with pytest.raises(ValueError, match="Nonfinite"):
        load_validated_cache(path, "identity", tensor_schema(tiny_cache))


def test_fresh_wrappers_do_not_grow_shared_prefix(tiny_cache):
    cache = as_cache(tiny_cache, "cpu", dtype=torch.float32)
    original = tiny_cache["000.k"].clone()
    cache.update(torch.ones(1, 2, 1, 4), torch.ones(1, 2, 1, 4), 0)
    assert cache.get_seq_length() == 6
    fresh = as_cache(tiny_cache, "cpu", dtype=torch.float32)
    assert fresh.get_seq_length() == 5
    assert torch.equal(tiny_cache["000.k"], original)


def test_quantized_roundtrip_uses_requested_dtype(tiny_cache):
    q = quantize(tiny_cache)
    restored = cache_tensors(as_cache(q, "cpu", quantized=True, dtype=torch.float32))
    assert all(value.dtype == torch.float32 for value in restored.values())
    assert max(float((restored[key] - value).abs().max()) for key, value in tiny_cache.items()) < 0.03


def test_causal_prefix_and_crop(tiny_cache):
    source = torch.tensor([[1, 2, 3, 4, 5]])
    assert common_token_prefix(source, torch.tensor([[1, 2, 9, 4, 5]])) == 2
    assert common_token_prefix(source, torch.tensor([[1, 2, 3, 4, 5, 6]])) == 5
    assert common_token_prefix(source, torch.tensor([[8]])) == 0
    cropped = crop_tensors(tiny_cache, 2)
    assert all(value.shape == (1, 2, 2, 4) for value in cropped.values())
    assert all(value.shape[-2] == 5 for value in tiny_cache.values())
    with pytest.raises(ValueError, match="dimensions"):
        crop_tensors(tiny_cache, 6)
    with pytest.raises(ValueError, match="unquantized"):
        crop_tensors(quantize(tiny_cache), 2)


def test_unknown_artifact_version_rejected(tmp_path, tiny_cache):
    path = tmp_path / "cache.safetensors"
    save_cache(path, tiny_cache, "identity")
    metadata = json.loads(path.with_suffix(".json").read_text())
    metadata["format"] = 999
    path.with_suffix(".json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        load_validated_cache(path, "identity", tensor_schema(tiny_cache))

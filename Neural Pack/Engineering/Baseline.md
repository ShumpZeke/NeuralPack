# Local baseline measurements

## Actions and setup

- Created project `.venv` with uv; installed PyTorch 2.8.0+cu126 from the official
  PyTorch wheel index and pinned Transformers 4.57.6, SafeTensors and analysis/test tools.
- Saved a full environment freeze in `experiments/requirements-lock.txt`.
- Downloaded public Qwen/Qwen2.5-0.5B-Instruct revision
  `7ae557604adf67be50417f59c2c2f167def9a775` using normal static HTTPS, with no credentials.
  The weight file is 988,097,824 bytes. All file checksums are recorded in
  `experiments/model-provenance.json` and revalidated during experiment startup.
- Read the pinned Qwen2 attention and DynamicCache implementations in Transformers.
  New request wrappers share immutable prefix tensors; append allocates concatenations.
- Implemented matched cold prefill, hot prefix, CPU KV, persisted KV, and per-head int8
  storage paths. The int8 path reconstructs full-precision KV before ordinary attention.
- First smoke invocation failed at Windows fsync on a read-only descriptor. See
  `research/failures/0001-windows-fsync.md`; changed the handle to `r+b` and reran.
- The fixed smoke run completed 20 trials across 256/1024 token contexts. Its early
  implementation retained an extra GPU cache; it is development evidence only.
- Independent review identified and corrected resident-cache fairness, dtype handling,
  logical-vs-physical byte counters, codec metadata, and baseline/incremental memory fields.
- CPU-only SDPA profiler probe confirmed `aten::_scaled_dot_product_efficient_attention`
  on this Windows build. Flash attention is not compiled, despite the enable flag being true.

## Exact commands

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe torch==2.8.0 --index-url https://download.pytorch.org/whl/cu126
uv pip install --python .venv/Scripts/python.exe transformers==4.57.6 safetensors==0.6.2 numpy==2.2.6 psutil==7.0.0 matplotlib==3.10.6 pytest==8.4.2 ruff==0.12.12
python scripts/download_model.py
.venv/Scripts/python.exe -m benchmarks.model_baseline --config experiments/smoke.json
.venv/Scripts/python.exe -m benchmarks.model_baseline --config experiments/smoke-fixed.json
```

## Interpretation boundaries

This is a batch-1 Transformers baseline, not vLLM, SGLang or LMCache. No cross-model
translation is active. No physical cold-disk, RDMA, PCIe-link saturation or power claim
is supported. Persistent files are checksummed then memory-mapped; logical payload bytes
are not physical disk I/O. Warm-cache and cold-prefill labels refer to prefix state.

The raw smoke text is deliberately repetitive and does not establish useful task quality.
The quality runner and causal-edit negative controls are separate experiments.

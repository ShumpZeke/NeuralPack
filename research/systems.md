# Systems review: where reusable computation already exists

Review date: **2026-09-05**. Evidence is primary-source documentation, paper body sections, and selected source code at the revisions below. This is a bounded static review, not an exhaustive novelty search or a reproduction. No serving stack was installed or benchmarked for this review. No paid compute was used.

## Decision supported by the review

Saving, indexing, offloading, sharing, and moving model-specific KV state are established capabilities. Non-prefix reuse with selective recomputation and cache-aware execution planning also have substantial prior art. NeuralPack should not describe any of those capabilities alone as its invention. A useful integration remains possible, but superiority must be measured against existing runtimes and storage backends.

The most tractable candidate is a small, inspectable artifact and benchmark layer that preserves source provenance, distinguishes source/index reuse from valid neural-state reuse, and refuses incompatible state. Its value is a hypothesis: it must reduce a real developer's repeated work or latency beyond configuring existing systems. It is not yet a systems research contribution.

## Exact prefix reuse: vLLM

Automatic Prefix Caching reuses computed prompt prefixes. Its design hashes the preceding block identity, current token IDs, and additional identity inputs. Only full blocks are cached. The design describes LoRA, multimodal hashes, cache salting, and cryptographic hash options. APC saves work on the shared prefill; it does not remove generation's attention over that context. [APC design](https://docs.vllm.ai/en/latest/design/prefix_caching/), [APC feature scope](https://github.com/vllm-project/vllm/blob/f4eccdadefc6501fafeb1a0bf7f171ff24f984b0/docs/features/automatic_prefix_caching.md).

The inspected implementation makes the prefix dependency explicit: `hash_block_tokens` hashes a tuple containing the parent hash; `generate_block_hash_extra_keys` includes the request salt only at the first block and adds multimodal, LoRA, and prompt-embedding identity. This is concrete evidence against identifying neural state solely by the bytes of the current independent document chunk. [Pinned implementation, functions around lines 543–649](https://github.com/vllm-project/vllm/blob/f4eccdadefc6501fafeb1a0bf7f171ff24f984b0/vllm/v1/core/kv_cache_utils.py#L543).

Inference for NeuralPack: exact cached state needs a derivation identity. Reuse before an edit can remain valid; a same-length replacement does not make later full-attention states valid merely because their token positions are unchanged. Source-file or AST dependency graphs do not represent all attention dependencies. A raw-content DAG may share bytes across reordered documents while an exact KV artifact cannot automatically share the corresponding states.

Native vLLM is the appropriate stronger serving baseline when the machine can run its selected model and backend. Explicitly pin options and reset caches between cold trials rather than assuming runtime defaults.

## Beyond a process's GPU memory: LMCache

LMCache's technical report describes extraction and insertion connectors, batched data movement, overlap of I/O with computation, cache tiers, and a control API. These cover much of the proposed persistent-context infrastructure. The report's performance findings are authors' results, not local NeuralPack measurements. [Technical report](https://arxiv.org/abs/2510.09665), [report PDF](https://lmcache.ai/tech_report.pdf).

The inspected `token_database.py` has two paths. `ChunkedTokenDatabase` chains preceding chunk hashes. `SegmentTokenDatabase` hashes separator-delimited segments independently. `CacheEngineKey` construction includes model name, logical world size, worker ID, KV dtype, and request configuration. The module normalizes byte digests into an integer using their first eight bytes; an internal cache key is therefore not a substitute for a full artifact integrity digest. Its compatibility fallback can select Python hashing and warns about consistent cross-process seeds. These are observations about this file, not an audit of every key-generation route. [Pinned token database](https://github.com/LMCache/LMCache/blob/ce08eea76ce5898200efee55f4932fd07a7cabeb/lmcache/v1/token_database.py).

Local disk offload is available, with chunk size, capacity, direct I/O, and device-path configuration. However, the inspected legacy `LocalDiskBackend` initializes a metadata mapping, checks that mapping for `contains`, and reads/writes raw buffers, despite a `.pt` suffix. Shape/dtype/position metadata comes from the mapping. Those observations do not establish recovery of a standalone file after restart. Do not equate disk offloading with independently portable, restart-safe artifacts without an experiment against the selected backend. [Disk configuration](https://docs.lmcache.ai/kv_cache/storage_backends/local_storage.html), [pinned backend, initialization and I/O](https://github.com/LMCache/LMCache/blob/ce08eea76ce5898200efee55f4932fd07a7cabeb/lmcache/v1/storage_backend/local_disk_backend.py).

Version caveat: current documentation separates multiprocess mode from deprecated in-process mode. The older controller already exposes lookup, movement, pinning, cleanup, and compression operations. Its page is useful evidence of prior art, but its commands should not be copied as the current default integration. [Controller documentation and deprecation notice](https://docs.lmcache.ai/kv_cache_management/index.html).

Inference for NeuralPack: integrate existing transport/storage APIs before writing a competing cache server. A manifest should bind model-weight revision, tokenizer/chat template, attention configuration, layout and dtype; a model's display name alone is insufficient evidence of compatible mathematics. Compatibility and serialization-layout conversion are separate checks.

## Non-prefix document blocks: CacheBlend

The paper's Sections 4–5 describe repairing cross-chunk effects through selective recomputation and pipelining that work with loading; its controller chooses recomputation and storage using latency estimates. Its evaluation uses Mistral-7B, Yi-34B and Llama-70B on A40 hardware and QA/summarization datasets. Reported quality comparisons are task-metric comparisons, not exact-logit guarantees. Section 9 qualifies applicability outside transformers. The reported TTFT improvements must not be transferred to the user's hardware or an instruction-adherence workload. [Paper, method, implementation, evaluation and limitations](https://arxiv.org/html/2405.16444v2).

Current LMCache documents a multiprocess blend engine. Its inspected module is more general than the older separator-based token database: `BlendTokenRangeMatcher` probes for registered chunks at arbitrary token offsets; `BlendModule` coordinates store, lookup and retrieve; `_CBRopeState` carries per-group position-rotation geometry. This is model/layout-aware cache composition, not evidence of a tokenizer- or model-independent semantic state. Selected declarations and matcher/store paths were read, not the entire 3,301-line module. [Current usage](https://docs.lmcache.ai/kv_cache_optimizations/cacheblend.html), [pinned MP blend implementation](https://github.com/LMCache/LMCache/blob/ce08eea76ce5898200efee55f4932fd07a7cabeb/lmcache/v1/multiprocess/modules/blend.py).

Inference for NeuralPack: an arbitrary-chunk reuse candidate must compare to CacheBlend, not only exact prefix caching. Rotating cached keys into a new position does not by itself restore the hidden-state changes caused by a different preceding context. Approximate fusion must remain a separate experimental path with adversarial quality gates.

## Radix reuse and heterogeneous state: SGLang

The current unified cache design describes a shared radix structure with separate full-attention, sliding-window and Mamba/SSM components. Matching requires component validators; state has distinct device/host ownership and eviction behavior. This is prior art for supporting multiple state types under a common cache interface. It does not make those states interchangeable between model families. [Pinned unified-cache design](https://github.com/sgl-project/sglang/blob/6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da/python/sglang/srt/mem_cache/unified_cache/components/README.md).

The `hiradix_cache.py` initialization configures host memory, optional external storage, prefetch thresholds and timeout policies. Only initialization and selected transfer/prefetch-related declarations were inspected. The implementation gives a stronger tiered-cache baseline than an in-memory dictionary. [Pinned hierarchical radix cache](https://github.com/sgl-project/sglang/blob/6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da/python/sglang/srt/mem_cache/hiradix_cache.py).

A specific security boundary appears in `RadixKey`: the salt separates the in-process radix tree and KV events, while the comment explicitly excludes token-only external L3/remote storage keys from that contract. This warrants a per-backend isolation test; it is not, by itself, proof of an exploitable vulnerability in a deployed service. [Pinned boundary, lines 74–80](https://github.com/sgl-project/sglang/blob/6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da/python/sglang/srt/mem_cache/radix_cache.py#L74).

## Moving state and separating inference phases

Mooncake combines a disaggregated KV cache with prefill/decode separation. Sections 3–6 discuss DRAM/SSD/RDMA resources, prefix hashes, transfer overlap, hot-block replication, and placement based on cache hits, transfer, queuing and prefill time. Thus a generic cache-aware planner is already prior art. Its released trace carries lengths and remapped prefix-block identifiers rather than prompt text: useful for policy simulation, insufficient for output-quality evaluation. [Mooncake paper](https://arxiv.org/html/2407.00079v3).

In the current repository, selected `TransferEngine` methods expose memory registration, batched submission and transfer-status querying, with implementation dispatch between backends. This is reusable transport infrastructure, not cross-model translation. The README links a dated FAST'25 release and traces, which should be distinguished from the evolving main branch. [Pinned transfer entry points](https://github.com/kvcache-ai/Mooncake/blob/c329f1941cba35ed1f12cb3bfba5751898e29b15/mooncake-transfer-engine/src/transfer_engine.cpp), [pinned repository overview](https://github.com/kvcache-ai/Mooncake/blob/c329f1941cba35ed1f12cb3bfba5751898e29b15/README.md).

DistServe independently optimizes phase placement and parallelism for TTFT and time-per-output-token SLOs. The body describes bandwidth-aware placement and evaluation on OPT models using 32 A100-80GB GPUs. Its low measured transfer overhead relies on placement enabling intra-node NVLink and cannot be presumed for a commodity laptop. [DistServe Sections 3–6](https://arxiv.org/html/2401.09670v2), [OSDI publication](https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin).

The inspected `engine.py` constructs context and decoding engines connected by a bridge queue and registers the context engine's KV memory handles with decoding. The code confirms a same-model phase handoff rather than a universal context artifact. [Pinned DistServe orchestration](https://github.com/LLMServe/DistServe/blob/82831f1604cc6b10bebd360f6c437a07790dde9f/distserve/engine.py).

## Security and format implications

vLLM documents a timing side channel in shared prefix caches and recommends unpredictable salts scoped to the required sharing boundary. Salt omission preserves shared-prefix behavior. A hash, even a cryptographic one, is neither an access-control decision nor a proof that a producer ran the claimed model. [vLLM security guidance](https://docs.vllm.ai/en/latest/usage/security/).

Safetensors provides a data-only tensor format and supports selective tensor access. Its metadata can be fetched separately using byte ranges. These are useful building blocks; the format does not supply the application's tenant authorization, provenance authenticity or semantic compatibility. [Safetensors format/use](https://huggingface.co/docs/safetensors/index), [metadata parsing](https://huggingface.co/docs/safetensors/metadata_parsing).

Proposed NeuralPack gates, not claims about existing implementation:

1. Parse declarative metadata with strict version, count, length, dtype and shape limits. Reject traversal paths, duplicate entries, overlapping offsets, truncation and hash mismatches before exposing artifacts.
2. Keep a full content digest and a full derivation digest. The latter includes exact producer inputs and model/runtime identity; shortened serving-cache keys remain internal hints.
3. Separate integrity from authenticity. A self-consistent attacker-produced cache can have valid hashes. Private artifacts remain scoped to their owner; signed public sharing requires an explicit trust policy and revocation design.
4. Require authorization before cache lookup, transfer, loading or event disclosure at each tier. A GPU-cache salt alone cannot establish this across a remote store.
5. Avoid loading untrusted pickle or arbitrary plugins from a package. A package must not silently download or execute a mapper named in its metadata.
6. For transport, validate bounded metadata, expected tensor layout, authenticated peer and namespace before accepting bytes. Test interrupted writes and absent blocks. Do not expose a local transport service publicly for a benchmark.

## A practical baseline ladder on constrained local hardware

Run the cheapest valid experiment first; use discovered hardware, installed libraries and model licenses to choose the actual model. These are proposed experiments, not completed work.

| Baseline | What it establishes | Required control |
|---|---|---|
| Raw source read, chunk/hash/index construction | Cost of reusable preprocessing | Same sources, ordering and parser versions |
| Reuse compiled source/index artifacts | Whether non-neural compilation has value | Report bytes read/written and invalidation amplification |
| Small causal model, fresh prefill | Local timing reference | Identical weights, dtype, device, prompt and generation settings |
| Native in-memory KV continuation | Exact-prefix upper bound | Compare suffix logits and outputs to fresh full prefill |
| Safe disk serialization and a new process | Actual persistence and compatibility | Prove hit after restart; count load, validation and transfer |
| vLLM APC / SGLang radix | Strong runtime baseline when feasible | Same model, cache capacity, concurrency and batching |
| Runtime plus LMCache selected backend | Strong offload/distribution baseline | Pin MP/in-process mode and backend; establish real hit metrics |
| CacheBlend | Strong partial-overlap baseline | Same ordering changes and per-task quality gates |

A tiny model with random weights is useful for testing invalidation mathematics and serialization equality. It cannot establish useful instruction following, realistic serving throughput, or cross-model semantic translation. A CPU proxy validates algorithms; it must not be presented as an A100/RDMA reproduction. Do not force 32K inputs beyond a chosen model's context support merely to fill a chart.

Correctness cases should include append, replacement, deletion and document reorder; mutations to system prompt, tokenizer, weights, RoPE, quantization and runtime identity; instruction positions at beginning/middle/end; numerical negation and tool/format restrictions. Tokenization may change around a text append boundary, so decide reusable length from token IDs and full prompt rendering, not character-prefix equality.

For a cached prefix, the next-token distribution can require the last cached token's logits or a deliberately recomputed boundary token. Time all required boundary work. Separate skipped prefill, suffix prefill, first-token selection, subsequent decode, packaging, and file I/O.

## Cost model and kill criteria

For sequential local reload, begin with the measured critical path:

`T_reuse = lookup + compatibility/integrity checks + read + deserialize/layout conversion + host/device copy + required suffix/boundary prefill`.

Compare that to the same request's fresh prefill critical path. If layers overlap transfer and compute, measure the resulting schedule; do not simply add overlapped durations or use theoretical link bandwidth. Report cold application cache and warm application cache separately, and label OS file-cache state as controlled, warm, or unknown. Include initial compilation cost and expected reuse count; zero requests amortize nothing.

Keep, pivot or discard using predeclared tests:

- **Redundancy:** discard claims of algorithmic novelty if a configuration of native caching plus an existing backend provides the same behavior. Integration usefulness remains separately testable.
- **Correctness:** fail the exact-state path on any unexplained output/logit discrepancy outside a declared numerical tolerance, any accepted incompatible artifact, or any tenant-boundary violation. Approximation requires separate quality thresholds.
- **Economics:** discard eager state materialization for a workload if measured avoided work does not pay back construction, validation, storage and reload within its observed reuse frequency.
- **Pareto value:** do not promote a challenger that is dominated by a correctly configured baseline on quality, latency, memory and storage. Report uncertainty and all tested workload regimes; a single improvement is not universal superiority.
- **Product scope:** if source/index reuse is the only demonstrated gain, call the result an incremental context compiler and report preprocessing savings. Do not report neural prefill savings from byte deduplication.

## Evidence ledger and limitations

All URLs above were retrieved on 2026-09-05. Heads were resolved through GitHub's public commits API; code URLs use the returned immutable revision. No private repository, browser profile, credential store or authenticated endpoint was inspected.

| Repository | Inspected revision | What was actually read |
|---|---|---|
| vllm-project/vllm | `f4eccdadefc6501fafeb1a0bf7f171ff24f984b0` | Selected `kv_cache_utils.py` functions at 543–649, hash initialization comments and request hashing call site; current APC/security documentation |
| LMCache/LMCache | `ce08eea76ce5898200efee55f4932fd07a7cabeb` | `token_database.py` class/hash/key/segment paths; `local_disk_backend.py` initialization, lookup, parallel reads and raw I/O; selected MP blend matcher/store/RoPE declarations; current and legacy docs |
| sgl-project/sglang | `6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da` | `RadixKey` construction/slicing; selected HiCache initialization and prefetch configuration; unified-cache README's goals, matching, insertion, locking and eviction descriptions |
| kvcache-ai/Mooncake | `c329f1941cba35ed1f12cb3bfba5751898e29b15` | TransferEngine registration/submission/status entry points and selected README links; paper Sections 3–6 and trace description |
| LLMServe/DistServe | `82831f1604cc6b10bebd360f6c437a07790dde9f` | Selected `engine.py` queue, engine construction and memory-handle registration; paper placement, implementation and evaluation sections |

GitHub heads from the first four repositories were dated 2026-09-05; DistServe's inspected head was dated 2025-04-06. A first guessed DistServe repository URL returned 404 and was discarded; the author's publication artifact identified `LLMServe/DistServe`. No claim in this review uses the failed lookup.

Unresolved: production support matrices for the final chosen hardware/model; all remote-backend isolation and persistence paths; exact source revision corresponding to every paper result; independent quality reproduction; comprehensive newer literature. Cross-model transfer, compression and representation research are covered by the separate paper review. The source-code samples establish mechanisms and boundaries, not whole-project correctness or absence of alternatives.

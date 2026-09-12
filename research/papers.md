# Research papers and implementation audit

Reviewed 2026-09-05. This is a bounded primary-source review, not a replication. Paper numbers below are authors' measurements. No pretrained models were downloaded, no external training jobs ran, and no paper result was reproduced by this review. Methods, evaluation conditions, limitations and relevant implementation paths were inspected; the review does not claim to have audited every line or experiment.

The practical distinction is **exact reuse**, **approximate reuse with measured quality loss**, and **new models trained to expose a shared interface**. A matching tensor shape establishes none of these by itself. See [unsolved problems and experiment designs](unsolved-problems.md) for our deductions and proposed local tests.

## Cross-model transfer

### P01 — Closed-form KV transfer within model families

[Heo et al., arXiv:2608.03893v1](https://arxiv.org/html/2608.03893v1), sections 2–4 and appendices C–E. This fits directional, centered affine ridge maps from selected source layers to each target KV head. Source heads are concatenated; K and V receive independent maps. Keys have RoPE removed before fitting and target RoPE applied afterward. Calibration uses 500 × 1,024-token FineWeb-Edu sequences with stride-four sampling. Evaluated pairs share tokenizer and KV geometry and use dense attention; the algebra's ability to resize matrices is broader than the validated regime. Four of six pairs retain 73–98% of target accuracy; two fail substantially. Attention-output similarity is a more useful diagnostic than coordinate reconstruction alone. Headline mapper speed excludes the cost of initially producing the source cache. Source-layer count is selected using four accuracy benchmarks, so those are not untouched selection holdouts. No author implementation link was found in the inspected paper. Independent code was inspected below.

### P02 — CacheBridge, correctly identified

[Qu et al., *CacheBridge: Efficient Cross-Model KV Cache Transfer*, arXiv:2609.00891v1](https://arxiv.org/html/2609.00891v1), sections 2–6. **This is the September 2026 cross-model affine mapper**, distinct from CacheBlend and similarly named repositories. Head-local support, attention-sensitivity-weighted regression and fused sufficient-statistic construction improve P01's approach. All three evaluated directions are same-family dense GQA with eight matched KV heads. Qwen3 14B→32B mapper storage falls from 4.296 to 0.538 GB; mean task-wise target retention is 99.83%. Application speedup up to 3.0× is against the full-head mapper, not end-to-end inference. The 8.63-second fit stage on four H800s excludes trace collection, source-layer selection and attention-weight construction. Runtime timings exclude source prefill, transfer, loading and decoding. Sensitivity weighting is a local first-order surrogate, not an exact downstream-error objective. Open-ended multi-turn quality, mismatched attention and cross-family transfer remain unestablished. No author code link was found in the paper or targeted search during this review.

### P03 — Universal context reuse claim

[Li et al., *A Universal Context-Reuse Layer for Cross-Model KV Sharing*, arXiv:2608.30963v1](https://arxiv.org/html/2608.30963v1), sections 4–7. Reports within-family and cross-family transfers, including tokenizer differences. Sections 4–5 specify a generic translation function and possible KV/downstream losses; they do not provide a sufficiently concrete translator architecture, tokenizer-alignment algorithm, fitting recipe or complete reproducibility package to implement the reported experiment faithfully. The reported Qwen2.5-1.5B→Gemma-2-2B target-side saving reaches 67.05% at 4K. Treat this as preliminary evidence to investigate, not an implemented universal interface. No executable implementation link was identified in the inspected paper. A demo is not a substitute for code, pinned configurations and raw evaluation data.

### P04 — A learned shared latent space

[Dery et al., *Latent Space Communication via K-V Cache Alignment*, arXiv:2601.06123v1](https://arxiv.org/html/2601.06123v1), sections 2–6. Per-model transformer adapters map KV into and out of a shared space, mixing source layers with cross-attention. Frozen base models are paired with trained adapters; suffix-language-model loss avoids relying solely on KV reconstruction. Experiments use Gemma-2-style models of 100–400M non-embedding parameters, sequences up to 512 tokens and 50K translator-training steps. Each translator is approximately one-quarter of its base model size in the default setup. Adding a model requires learning its adapters; some untrained pair paths then generalize. Same-vocabulary experiments dominate; a cross-vocabulary loss argument does not constitute broad tokenizer interoperability. This supports a learned model-pool interface, not an inference-free universal semantic IR. No author implementation was located in the inspected primary page/search.

### P05 — Cache-to-Cache (C2C)

[Fu et al., arXiv:2510.03215v1](https://arxiv.org/html/2510.03215v1), sections 3.3 and appendix A.1; [official implementation](https://github.com/thu-nics/C2C). C2C projects and fuses source and receiver caches using learned residual modules and per-layer gates. Its ordinary path **also computes receiver context KV**. Its benefit over text communication therefore must not be reported as elimination of all receiver prefill. Layer alignment proceeds from the ends of the models; token alignment decodes receiver tokens and chooses a source token when segmentation differs. This is an approximation that can discard information, not lossless token conversion. Training optimizes communication quality, so native output equivalence is not the objective. Code inspection confirms these boundaries; see I02.

### P06 — Mixture-of-Translators (MoT)

[Lee et al., arXiv:2607.28979v1](https://arxiv.org/html/2607.28979v1), sections 2–4, appendices B–C. Token-gated translator modules map selected layer channels; target context replay reconstructs the remaining trajectory. This includes target computation and is not a pure all-layer KV replacement. Its analysis is conditional: the residual Lipschitz bound `(1+δ)^depth` does not establish contraction for δ≥0. The final hidden-state bound assumes a full-column-rank stacked K/V projection; that needs a geometry check (see U08). No detailed tokenizer alignment rule or author implementation link was identified in the inspected v1. Reported heterogeneous transfer is promising, but we have not replicated it.

### P07 — DroidSpeak

[Liu et al., arXiv:2411.02820v4](https://arxiv.org/html/2411.02820v4), sections 3–5. Studies fine-tuned variants of the same base architecture. An offline profile chooses sensitive layer groups to recompute; other layer KV and transition input states are reused. Its runtime overlaps transfer with partial prefill, with implementations described over vLLM and LMCache. This is approximate cross-checkpoint reuse under close architectural correspondence, not a general family translator. The evaluated cluster uses A100 GPUs and InfiniBand; performance should not be imported into a consumer GPU/NVMe setting. Different revisions report different ranges, so this review cites v4 rather than combining abstract numbers across versions.

## Context changes and partial reuse

### P08 — CacheBlend

[Yao et al., arXiv:2405.16444v2](https://arxiv.org/html/2405.16444v2), sections 3–5. Reuses independently cached chunks and selectively recomputes tokens to restore some cross-chunk interactions. Selected token queries attend to a mixture of recomputed and reused K/V. Early-layer deviations guide token selection. The source chunk hash alone cannot establish exact validity in a different preceding context. Results support a quality–recomputation tradeoff, not exact causal equivalence. This is directly relevant to reordered repository/document blocks and is a strong challenger to any new partial-reuse algorithm. Serving integration is covered in [systems](systems.md).

### P09 — KVCOMM / Ye et al. (context offsets)

[Ye et al., arXiv:2510.12872v1](https://arxiv.org/html/2510.12872v1), sections 3.1–3.4 and appendix 6.2; [official repository](https://github.com/FastMAS/KVCOMM). A placeholder-specific anchor pool stores base caches and context-induced offsets. Embedding/length matching chooses anchors; weighted offsets adjust reusable caches, after positional alignment. Misses invoke normal prefill and update the pool. The Lipschitz arguments assume bounded similarities of input sequences, not a guarantee that any semantically similar token is safe. This is approximate context adaptation in same-model multi-agent workflows. The inspected paper contains a correction note that an earlier TTFT calculation omitted first-token decoding; use explicit first-token timing in reproduction. No paper speed figure is adopted as a NeuralPack result.

### P10 — KVComm / Shi et al. (selective layers)

[Shi et al., arXiv:2510.03346v1](https://arxiv.org/html/2510.03346v1), section 3 and appendix B; [author code](https://github.com/Zephyroam/KVComm). Selects source cache layers using attention importance and a Gaussian depth prior, then concatenates their KV into receiver attention while the receiver processes its query. The method explicitly limits pairs to identical models or fine-tuned variants of the same base LLM, with one-to-one layer matching. It is distinct from P09 despite the nearly identical name. Heterogeneous models appearing across the benchmark do not mean arbitrary cross-family pairs were translated.

## Compression and interfaces created during training

### P11 — KIVI

[Liu et al., arXiv:2402.02750v2](https://arxiv.org/html/2402.02750v2), section 3; [official code](https://github.com/jy-yuan/KIVI). Asymmetric quantization uses channel-wise keys and token-wise values, retaining a recent full-precision residual region. The implementation packs cache groups and uses specialized low-bit matrix operations during decoding. This reduces cache memory/bandwidth; it does not make a cache model-independent. Scale, minimum, grouping and residual data count toward serialized size. The inspected model code computes native prefill attention before storing a quantized cache, so quality evaluation must actually consume that cache in subsequent continuation steps.

### P12 — Palu

[Chang et al., arXiv:2407.21118v2](https://arxiv.org/html/2407.21118v2), section 3 and appendices B–D; [official code](https://github.com/shadowpa0327/Palu). Low-rank projection weights create smaller latent KV states. Grouped-head decomposition trades reconstruction work against approximation quality; rank allocation and quantization are further choices. Positional operations constrain which reconstruction matrices can be fused into attention, motivating specialized kernels. This is a model-specific changed computation, not generic SVD serialization of an untouched cache. A stored low-rank factorization alone proves neither decoding speed nor semantic preservation. Inspected code separates projection, reconstruction and optional fake quantization; physical packed byte savings need a real storage/kernel measurement.

### P13 — Activated LoRA

[Greenewald et al., paper](https://arxiv.org/abs/2504.12397); [PEFT aLoRA documentation](https://huggingface.co/docs/peft/main/package_reference/lora). An adapter changes computation only after its activation position, so the preceding base-model prefix can remain reusable. This creates compatibility by construction instead of estimating a translation. It requires adapters trained with that usage pattern. Reuse permission is position-dependent: cache after activation cannot casually be labeled base cache. The former [IBM implementation](https://github.com/IBM/activated-lora) points users to PEFT; inspect and pin the actual supported runtime before adopting it.

### P14 — ICaRus

[Woo et al., arXiv:2603.13281v1](https://arxiv.org/html/2603.13281v1). Separates a shared cache-producing component from specialized decoders so identical cache reuse becomes an architectural interface. This is a different research direction from translating independently trained arbitrary models. It requires training/co-design and is not a drop-in artifact for existing checkpoints. It is a relevant longer-term alternative if training a controlled family is within scope; no local claim is made here.

## Implementation inspections and revision ledger

All revisions were resolved with GitHub's public API on 2026-09-05; only source text was retrieved. These are static inspections, not executed reproductions.

### I01 — Independent `spotta85/kvbridge`

Revision: `fdc11d31f005d7d4cec949b72e9032f2093dd6b8`.

- [fit.py](https://github.com/spotta85/kvbridge/blob/fdc11d31f005d7d4cec949b72e9032f2093dd6b8/kvbridge/fit.py): sequential model loading, stride-sampled cache collection, source-layer ranking and streaming sufficient statistics. **Observed discrepancy:** it divides centered moments by N before adding λ; P01 writes the unnormalized objective. To match an unnormalized λ, use λ/N in this convention, or explicitly state the changed objective. The same source tokenizer is used to feed both models without an identity check.
- [rope.py](https://github.com/spotta85/kvbridge/blob/fdc11d31f005d7d4cec949b72e9032f2093dd6b8/kvbridge/rope.py): reconstructs a theta-only, full-head, half-rotation convention. This does not implement every scaled/partial RoPE variant. Its broad comments about positional generality exceed what that helper establishes for arbitrary configurations.
- [transfer.py](https://github.com/spotta85/kvbridge/blob/fdc11d31f005d7d4cec949b72e9032f2093dd6b8/kvbridge/transfer.py): batch-one source cache; strip rotation, gather layers, affine transform, restore target rotation, construct `DynamicCache`. No authoritative model-checkpoint identity is verified by the tensor input.
- [mapper.py](https://github.com/spotta85/kvbridge/blob/fdc11d31f005d7d4cec949b72e9032f2093dd6b8/kvbridge/mapper.py): SafeTensors plus versioned JSON. Metadata contains model names and KV geometry but is not a full immutable checkpoint/tokenizer/runtime fingerprint.

These are adoption cautions; they are not evidence that the independent author's experiments are invalid. The repository's README reports nontrivial small-model quality loss, making it especially useful as a counterexample to universal-retention marketing.

### I02 — Official C2C

Revision: `113c3a9b2538cbf096a0477e1ec99ae2a2e0d12a`.

[aligner.py](https://github.com/thu-nics/C2C/blob/113c3a9b2538cbf096a0477e1ec99ae2a2e0d12a/rosetta/model/aligner.py) decodes individual base tokens, re-encodes each string and selects `FIRST` or `LONGEST` when there are multiple candidates. Its chat path pads structural sections and aligns message sections separately. This creates an aligned source input stream, which can differ from the source tokenizer's ordinary full-text stream. The trained recipe needs to be preserved; arbitrary pre-existing native source caches are not automatically drop-in equivalents.

[wrapper.py](https://github.com/thu-nics/C2C/blob/113c3a9b2538cbf096a0477e1ec99ae2a2e0d12a/rosetta/model/wrapper.py) prefills base sections, computes source caches and calls projectors with both base and source cache slices. Static inspection confirms receiver prefill in this path. This is important baseline accounting, not a criticism of its stated communication objective.

### I03 — Official KIVI

Revision: `876b4d2d08e3b1d5f70d0969c299d8c7c42ddfb6`.

[models/llama_kivi.py](https://github.com/jy-yuan/KIVI/blob/876b4d2d08e3b1d5f70d0969c299d8c7c42ddfb6/models/llama_kivi.py) keeps packed and full-precision cache regions plus scale/minimum metadata, and uses quantized CUDA matrix products on cache-consuming paths. Its first prefill attention uses current unquantized values. A single no-cache forward pass would not measure the error of subsequent reads from compressed history. Custom legacy tuple structure also means a serializer cannot treat all Hugging Face cache classes alike.

### I04 — Official Palu

Revision: `bb22666e2ef96707e8dd21d93fc00146c2e0d615`.

[svd_linear.py](https://github.com/shadowpa0327/Palu/blob/bb22666e2ef96707e8dd21d93fc00146c2e0d615/palu/model/modules/svd_linear.py) constructs grouped low-rank modules, supports whitening-based decomposition, separately exposes latent projection/reconstruction, and can fuse a Hadamard transform. `quantize_latent` returns fake-quantized tensors in the inspected path. Read [kernel implementations](https://github.com/shadowpa0327/Palu/tree/bb22666e2ef96707e8dd21d93fc00146c2e0d615/kernel) and measure real bytes/latency before claiming packed inference savings.

### I05 — KVCOMM source resolved, not fully audited

`FastMAS/KVCOMM` revision `48ca0b376c7f4fbf1c24042c1709a6fe4148c959`; [engine path](https://github.com/FastMAS/KVCOMM/blob/48ca0b376c7f4fbf1c24042c1709a6fe4148c959/KVCOMM/llm/kvcomm_engine.py). Tree/entry point resolved; detailed algorithm review here is based on P09. Do not describe this as a code reproduction.

## What can be concluded now

- Storing and transporting same-model KV is prior art. Generic packaging is not a novel inference algorithm.
- Cross-model cache reuse is technically plausible under measured restrictions. A shared shape, a good R² value, or a plotted latent cluster is not a behavioral compatibility certificate.
- The closest feasible contribution is a truthful compatibility and cost planner plus reproducible evaluations, with exact reuse enabled by default and approximate routes admitted only after workload-specific evidence.
- A source/structure/retrieval package is more portable than neural state but usually saves preprocessing, not full model interpretation. Keep these cost categories separate.
- Revisit the literature before any public novelty claim. These September 2026 results are recent preprints, and absence of code in this bounded search is not proof code does not exist.

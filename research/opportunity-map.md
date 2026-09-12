# Opportunity map

Assessed 2026-09-05; provisional. See [systems](systems.md), [papers](papers.md), and
[unsolved problems](unsolved-problems.md) for primary-source evidence and read depth.

| Candidate | Existing competition | Local falsification test | Current status |
|---|---|---|---|
| Another persistent KV container | LMCache, serving runtime cache tiers | Complete load cost versus native hot prefix and recompute | No novelty; storage baseline only |
| Universal context state | Trained transfer/latent-space research | Held-out tokenizer/model/architecture changes with full costs | No general exactness evidence |
| Incremental source/retrieval package | Persistent file indexes, content-addressed stores | Small edits versus file-level FTS5 reuse and full rebuild | Candidate implementation underway |
| Provenance/compatibility checks | Runtime keys, manifests, cache salts | Mutate weights, tokens, masks, positions, namespace and bytes | Conservative helpers tested; not a security product |
| Measured execution planner | Mooncake, CacheBlend and runtime policies | Held-out trace versus best fixed policy including setup | Cost primitive implemented; adaptive value unproven |
| Local model handoff tooling | CacheBridge, KVComm/C2C variants | Ridge baseline plus target prefill and quality gates | Research track; no local reproduction yet |

## First gate

Native hot prefix reuse is the exact-context inference champion until a measured
challenger beats it without unacceptable quality loss. Persisted caches must be judged
in cold-start, memory-pressure or cross-process regimes, not marketed as better hot reuse.

Source preprocessing must beat a competent persistent file-level index on workload
regimes that developers care about. If it only saves packaging/storage, say so. Query
latency and retrieval correctness matter alongside compile/update time.

## Adjacent hypotheses to test cheaply

1. **Context as build artifacts:** source objects are portable, while neural objects have
   a full derivation dependency. Measure invalidation amplification separately.
2. **Lazy artifact materialization:** compile neural state after repeated demand; compare
   setup amortization against always-compile and never-cache controls.
3. **Progressive evidence loading:** retrieval returns exact source spans first and optional
   valid KV second. Quality must survive instruction/rare-detail tests.
4. **Layered context packages:** deduplicate source objects across versions without assuming
   the same applies to attention state. Compare to a conventional content-addressed store.
5. **Bandwidth-aware omission:** deliberately recompute small prefixes when validation/load
   cost dominates. Derive decisions from measurements, not fixed folklore thresholds.

None of these names establishes novelty. Keep only measured Pareto improvements, and
archive negative results. Hosted infrastructure and multimodal extensions are premature.

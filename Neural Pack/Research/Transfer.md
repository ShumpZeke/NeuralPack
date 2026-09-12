---
date: 2026-09-05
track: cross-model-transfer
status: bounded-review-complete
type: research-action-log
---

# Cross-model transfer research

This note records the delegated literature/code review. It is part of the **Neural Pack** Obsidian vault. The broader mission is [[../Mission|Mission]].

Canonical deliverables:

- [Paper and source-code audit](../../research/papers.md)
- [Unsolved questions and local experiment designs](../../research/unsolved-problems.md)

These relative links are ordinary Markdown paths from this note; Obsidian readers can also open the project research files directly. No training run or pretrained-model evaluation was performed in this research track.

## Action ledger

1. Read the supplied mission attachment, including its $0 capital constraint, cross-model progression, tokenizer-independent representation question, delta-KV question and request to document actions in this vault.
2. Searched primary literature for the exact CacheBridge title, within-family KV translation and universal context reuse. Opened versioned arXiv HTML rather than relying on abstract summaries.
3. Read the closed-form transfer method, calibration, selection procedure, timing boundary and failure cases. Sent an early recommendation to the coordinating agent: exact source artifacts and same-model caching first; translation remains a gated research candidate.
4. Read CacheBridge's affine interface, support rule, weighted fitting, fused statistics, evaluated pairs and limitations. Recorded its precise identity to prevent confusion with CacheBlend.
5. Inspected the universal-reuse paper's translation sections and identified a reproducibility gap; did not invent an implementation for its reported results.
6. Followed primary references to learned shared latent spaces, C2C, MoT, DroidSpeak, CacheBlend and two distinct projects with the name KVComm. Read their relevant method sections and recorded the different assumptions in the paper ledger.
7. Inspected low-bit and low-rank compression methods and traced the code paths that determine whether compressed history is actually consumed during decoding.
8. Resolved immutable public GitHub revisions for an independent ridge implementation, official C2C, KIVI, Palu and KVCOMM. Retrieved source as text. No third-party code was executed.
9. Read ridge collection/selection/solve, RoPE helpers, transfer and serialization code. Flagged normalized-versus-unnormalized regularization, tokenizer identity and generalized RoPE as reproduction hazards. Sent these findings to the coordinating agent.
10. Read C2C tokenizer alignment and wrapper execution. Distinguished native full-text caches from the aligned token stream its runtime constructs. Confirmed receiver prefill in the inspected fusion path.
11. Read KIVI cache packing/continuation and Palu projection/reconstruction paths. Identified why single-forward evaluation or fake quantization alone cannot establish cache-use quality or physical byte savings.
12. Derived conservative exact causal reuse conditions, the limits of RoPE relocation, a finite-bit universal-compression counterexample, low-rank storage break-even and full-path mapper economics. Labeled these as deductions with assumptions.
13. Wrote the canonical research files and this vault note. Proposed local experiments with destructive controls, holdouts and decision criteria; did not label proposals as completed experiments.
14. At the coordinating agent's request, performed a read-only audit of `benchmarks/model_baseline.py` and its configuration. Confirmed the matched token-ID inputs and cache-wrapper approach; flagged shared resident-cache memory accounting, fixed-fp16 reconstruction, byte-counter labels, quantizer scope and codec metadata. Sent the findings to the coordinating agent for fixes. This audit did not execute a model or edit the benchmark; subsequent harness changes and validation are owned by the main track.

## Decisions and next work

Research recommendation: keep exact, auditable source artifacts as the portable truth. Attach any neural state as an explicitly typed artifact whose validity is specific to weights, tokenization, positions and runtime semantics. Admit approximate translation only when measured quality and complete-path costs support it.

The next cheapest independent checks are a tiny causal-mutation experiment, tokenizer byte-span/causality tests and measured cache transport accounting. Pretrained cross-model calibration can follow if a suitable local model pair and memory budget exist. Synthetic affine recovery is only an implementation sanity check; it does not establish actual model transfer.

## Review scope and limitations

No purchases, credentials, browser sessions, model downloads or remote compute were used. Public pages, paper methods and selected source files were read. Search did not locate every author's implementation; the audit states absence from the inspected sources, not global nonexistence. The September 2026 papers are especially recent and should be rechecked before asserting novelty or publishing performance claims.

The journal above records actions and discoveries from this delegated track. Raw benchmark measurements, later implementation actions and the main project's decisions belong in their corresponding vault notes and repository logs.

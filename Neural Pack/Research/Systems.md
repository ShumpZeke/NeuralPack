---
type: research-journal
date: 2026-09-05
status: static-review-complete
tags: [research, systems, prior-art, security]
---

# Systems research journal

This note records the systems research subtask. It makes no benchmark or reproduction claim. The repository evidence is in [systems.md](../../research/systems.md) and [landscape.md](../../research/landscape.md). The paths in those links are relative to this note's location in the project; the full project review lives outside the vault's `Research` directory.

## Request and boundaries

Read the mission attachment at `C:\Users\vardh\.codex\attachments\2f9b0b6b-130e-4253-81b6-af3d2fe97bee\pasted-text-1.txt`. The assigned scope was existing prefix caches, offload/persistent KV, disaggregated inference, partial reuse, transport and serialization safety. The objective was to attack novelty before extensive construction. File ownership was restricted to the two repository reviews and this journal. No shared README, research log, runtime or benchmark file was changed by this subtask.

## Actions and discoveries

1. Read the supplied mission and inspected the initially nearly empty workspace. A large first output was truncated, so the middle mission sections on representation, partial reuse, evolutionary research and security were read again explicitly.
2. Used web search to locate primary official documentation and papers. Search results from secondary explainers and social forums were not used as technical evidence. No browser was required, so Steel and authenticated sessions were not started.
3. Queried the public GitHub commits API for vLLM, LMCache, SGLang and Mooncake. Resolved source trees and selected implementation paths. Each subsequently cited code file uses the immutable returned revision.
4. The first guessed DistServe repository returned 404. Corrected it through the authors' published artifact, then resolved `LLMServe/DistServe`. A shell loop retained the previous result after the failed request; that stale row was discarded and never treated as a DistServe revision. Later calls used stop-on-error behavior.
5. Read vLLM prefix hashing functions and current design/security documents. Sent the coordinator an early finding that persistence and tiering already exist and that source equality does not establish neural-state validity.
6. Read LMCache token-database hash/key paths, chunk and segment processing, and the local-disk backend's metadata lookup and raw-buffer I/O. Identified that a `.pt` suffix is not evidence of pickle serialization. Recorded the need to test restart recovery independently from disk offloading.
7. Inspected current LMCache multiprocess blend declarations and matching/store paths. The token-range matcher supports arbitrary offsets, so the older special-separator path cannot describe all current partial reuse. Noted that current docs distinguish MP mode from legacy in-process mode.
8. Read CacheBlend paper method, controller, implementation, evaluation setup and limitations. Recorded its approximate-quality scope, its strong partial-overlap baseline status and the need to test instruction adherence beyond its published task metrics.
9. Read SGLang `RadixKey`, selected hierarchical-cache configuration and unified-cache design. Sent the coordinator the concrete salt-contract limitation for remote L3 storage. This was a static boundary observation, not an exploit or a claim that every deployment leaks data.
10. Read Mooncake paper architecture, cache scheduling and trace sections, plus transport entry points. Sent the coordinator a correction to the initial opportunity: a generic cost planner is itself established prior art. A planner candidate needs specific measured advantages.
11. Read DistServe placement/evaluation sections and engine orchestration. Recorded why its large-cluster transfer findings are not laptop measurements and why phase handoff is not cross-model transfer.
12. Checked official Safetensors material for safe tensor data and partial loading. Converted this into proposed package-parser and authenticity gates, explicitly separate from transport/runtime compatibility.
13. Wrote the systems review, landscape and journal. Verified the intended files exist and checked their links and scope wording. The review's experiment table is future work; it is not a completed experiment ledger.

## Revision record

| Project | Revision resolved on 2026-09-05 |
|---|---|
| vLLM | `f4eccdadefc6501fafeb1a0bf7f171ff24f984b0` |
| LMCache | `ce08eea76ce5898200efee55f4932fd07a7cabeb` |
| SGLang | `6a0c55fd6c48f79ff48008cbcd849a54b6ccc0da` |
| Mooncake | `c329f1941cba35ed1f12cb3bfba5751898e29b15` |
| DistServe | `82831f1604cc6b10bebd360f6c437a07790dde9f` |

The evidence ledger in the repository review names the paths and parts actually read. Some broad raw-file outputs were truncated; only the displayed sections and later targeted reads support claims. No whole-repository code audit is implied.

## Interpretation

The original broad artifact vision overlaps heavily with mature systems. An initial tool can still be useful if it demonstrably makes incremental preprocessing or valid reuse easier, but a new extension and content hashes do not establish an inference breakthrough. Preserve separate labels for measured preprocessing savings, exact model-state reuse, approximate fusion and untested translation.

## Next evidence needed

- Actual local hardware and software inventory, supplied by the coordinator's parallel track.
- A small exact-prefix correctness experiment and process-restart reload comparison.
- Incremental source/index work with controlled edits and bytes-rewritten measurements.
- Native-runtime and LMCache baseline feasibility for the selected model/backend.
- Held-out workload evidence before promoting any adaptive cache policy.

No services, models or paid infrastructure were started. No credentials or private data were accessed. All research HTTP requests targeted public documentation, papers and public repository metadata/source files.

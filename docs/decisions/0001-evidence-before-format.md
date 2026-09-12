# ADR 0001: Keep source reuse and neural-state validity separate

Status: provisional; 2026-09-05.

## Decision

Start with a local, experimental source/index compiler and an explicit same-model baseline.
Do not stabilize a universal context format or promise cross-model exactness. Treat each
claim as a hypothesis until measured against its strongest practical baseline.

## Alternatives

- Monolithic portable KV package: known storage functionality; highly model-specific.
- Universal latent IR: research track without evidence of general lossless portability.
- Native cache alone: the initial performance champion for exact hot prefixes.
- Incremental source/index artifacts plus runtime planner: candidate to test.

## Evidence and reason

See `research/systems.md` and `research/papers.md` as the reviews complete. CPU preprocessing
and neural attention have different dependency graphs; reusing a content hash never proves
that a contextualized KV block remains valid after a preceding edit.

## Reversal conditions

Keep a new architecture only if controlled measurements show useful savings after compile,
lookup, movement, storage and quality costs. Discard any candidate dominated by an existing
baseline; redirect the effort to the strongest remaining unmet need.

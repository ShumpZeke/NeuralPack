# Corpus engineering journal

## 2026-09-05 — Initial bounded diagnostic

Read the NeuralPack mission from the supplied attachment, including corpus, correctness, instruction-location, adversarial, reproducibility, and documentation requirements. The main agent assigned the corpus and evaluator as an independent work stream while it handles the model runner. This note records the work stream's actions; model and performance outcomes belong to the experiment records.

Selected a standard-library implementation compatible with the discovered Windows/Python 3.12 environment. The corpus does not require GPU memory, paid services, downloads, or external datasets. Chose 28 explicitly synthetic tasks to keep initial model experiments bounded. This choice does not satisfy the mission's eventual large real-repository/general-quality coverage.

Created `benchmarks/corpus.py` with the `Task` dataclass, deterministic seeded generation, prompt rendering, reference-answer serialization, byte-prefix measurements, and a fingerprinted manifest. Built four workload groups (source code, manual, conversation, and mixed agent context), each with base, exact repeat, shared prefix, append, interior edit, deletion, and block reorder. Kept provenance explicit in task metadata and source prose. Added beginning/middle/end/multiple instruction probes, exact rare keys, numeric near misses, negation, multi-hop lookup, deleted facts, quoted hostile instructions, and constrained JSON/tool intents.

Created `benchmarks/quality.py` with exact text and strict JSON/serialized-tool validators. Key ordering and outside whitespace are allowed; duplicate keys, extra keys, wrong types, changed digits, prose wrappers, NaN/Infinity, and wrong tool names/arguments fail. No generated code or tool intent is executed. Summary results retain category counts, and empty aggregates report unavailable accuracy rather than 0%.

Created `tests/test_corpus.py` to check reproducibility, variant relationships, metadata, reference-answer acceptance, stale answer rejection, JSON parser edge cases, near-miss numbers, instruction coverage, and tool constraints. Created `benchmarks/CORPUS.md` with the integration API, benchmark-pair ordering, byte/token/KV distinction, prompt/output handling, measurement requirements, and explicit limitations. Added `benchmarks/__init__.py`.

Validation results are appended below after execution. Next decision: integrate with the raw/prefix/persistent model runner, preserve every response, and compare paired quality regressions. Use this as a diagnostic gate while building larger independent workloads. Do not interpret passing evaluator unit tests as evidence of model competence or neural-state reuse quality.

Ran `python -m unittest discover -s tests -p test_corpus.py -v`: all 17 tests passed (0.054 seconds on the first run). Review found that padding consumed the same RNG sequence as the rare facts, confounding context-length sweeps. Split filler generation into separate deterministic RNGs so each seed retains the same answers across padding sizes, and strengthened the test to assert this. Moved the mixed workload's read-only policy into the middle of the context so the multiple-position label corresponds to the actual applicable instruction. These changes are included in the initial v1 corpus.

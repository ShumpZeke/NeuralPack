# Cycle 22: large-file updates and identical block reuse

**EMPIRICAL.** This is a LOCAL update-cost experiment, with zero generative calls.
The compiler/runtime remains unchanged. The research adapter is not promoted.

Three exact files from CPython 3.12.10 commit
`0cc81280367df838c4b199f8f0378837165071c2` were compiled as separate artifacts:
`Lib/test/test_typing.py` (351,572 bytes), `Objects/unicodeobject.c` (467,971),
and `Doc/library/typing.rst` (121,424). They provide approximately 88K, 117K
and 30K chars/4 tokens per request, respectively. These are individual files,
not whole repositories or cumulative context-size claims. Exact source hashes,
the license and the modified bytes are retained in the cycle archive.

Each file received either an appended comment or one leading blank line.
The leading-line experiment does not claim semantic equivalence: line-sensitive
program behavior can change. An update must agree with a fresh build of the
same modified source.

The initial three-trial stage profile found Python splitting used about 96 ms
of a 206–208 ms update. Deletion and index insertion were also material. A
subsequent comparison used five shuffled repetitions per case and method,
without stage instrumentation. Only this second run defines the paired speed
ratios below; timings from the two runs must not be mixed.

| File / edit | Baseline median ms | Reuse median ms | Ratio | Reused blocks |
| --- | ---: | ---: | ---: | ---: |
| Python / append | 313.20 | 232.17 | 1.35× | 179 / 180 |
| Python / leading blank | 313.06 | 221.77 | 1.41× | 179 / 180 |
| C / append | 360.20 | 169.21 | 2.13× | 262 / 263 |
| C / leading blank | 371.57 | 363.14 | 1.02× | 0 / 263 |
| RST / append | 113.82 | 63.96 | 1.78× | 26 / 27 |
| RST / leading blank | 117.16 | 117.53 | 1.00× | 0 / 27 |

The adapter retains rows only when kind, name and exact text match, using a
multiset to preserve duplicate occurrences. It updates ownership, ordinal,
line spans and token metadata. Source scanning, parsing, transaction handling
and integrity sealing still run. It admits deterministic artifacts with graph
indexing disabled. Its temporary helper patches require a single thread;
semantic encoders, graph updates and concurrent use are not supported.

All 60 comparison artifacts passed full verification and matched the fresh
reference block representation. All 300 paired query outputs, token counts
and source spans agreed at an identical 2,048 estimated-token cap. The initial
profile separately passed 18 artifact comparisons and 90 query checks. These
source-derived queries test update equivalence, not answer quality. Source
and artifact copying, reference compilation and verification are outside update
timing. Tests, archive compression and LIVE calls did not overlap timing runs;
host load and filesystem cache were not controlled.

Eight regression cases cover source changes, insertions, duplicates, removal,
rename, transaction rollback, unsupported graph mode and repeated updates with
tied searches at tight budgets. A mutation that reinserts retained payloads
alongside their originals must fail the representation check.

Final acceptance: **726 tests passed, two skipped, and all 58 mutation
tripwires were killed**, including the three original critical mutants.

**PROVED UNDER ASSUMPTIONS:** with fixed index derivation, the maximum number
of payload-identical reusable occurrences is the multiset intersection. See
[the qualified statement](math/EXACT_BLOCK_REUSE.md). This does not bound update
latency or establish equivalence for all queries.

**Decision:** keep the measured adapter as a research challenger; do not add it
to the runtime. The best measured gain is 2.13× on one edit type, not 10× or a
repository-wide speedup. Fixed windows lose all reuse after a leading-line edit
in the C and RST cases. Python's parsing cost remains even when 179 blocks match.
There is no new answer-quality or dollar-savings result.

**CONJECTURE / next experiment:** content-anchored boundaries might resist
insertions better than positional windows. Compare reuse, compilation cost,
block sizes and matched-budget retrieval before considering adoption. Repeated
lines and long lines are counterexamples to easy universal guarantees. RST
structure and ordinary C function definitions are also not fully represented
by the current Markdown/regex handling. Do not add a parser without measuring
its benefit and cost.

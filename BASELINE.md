# Baseline (start of the autonomous research loop)

Recorded 2026-09-26 against commit `6b90748` (the snapshot as received), before any
product change. Architecture as found: [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md).
Every later change is compared against the numbers here; the running record is
[experiments/npkbench/EXPERIMENTS.md](experiments/npkbench/EXPERIMENTS.md).

## Environment

Linux 6.18, 4 vCPU, 15 GiB RAM, Python 3.12.3, SQLite 3.45.1, CPU-only torch 2.8.0.
No generative model or API credential is used anywhere in this loop.

## Test suite

`python -m pytest tests/ -q`: **1,219 passed, 28 skipped, 2 failed** as received.

- `test_source_scan_failures.py::...[directory-compile]` — a Linux-only test-harness bug
  (the monkeypatched `os.scandir` received an int file descriptor from `shutil.rmtree`).
  Fixed.
- `test_click_tasks.py::test_click_oracles_match_the_frozen_prospective_dataset` — needs
  `experiments/results/cycle10-click-tasks.json`, which is not in this snapshot. Left as is.
- `test_query_caching_and_ordering.py::test_repeated_query_cache_hit_and_identity` asserts
  wall-clock ordering (`cached latency <= uncached latency`) and flakes under CPU load.

## Existing benchmarks

The project's headline evidence (246 CRISP needles, the Cycle 28-37 replays) depends on
`experiments/runs/*`, which was not published with this snapshot, so it cannot be
reproduced here. The questions were also developer-written and inspected. The urllib3
executable oracles (12 tasks) remain reproducible but are too small to rank variants.

## NPK-Bench (built for this loop)

`benchmarks/npkbench/` — see its package docstring for the full protocol.

- **Query:** a SWE-bench issue's text, verbatim (median 134 words). Written by real
  users; never seen or tuned by NeuralPack's developers.
- **Corpus:** the whole repository at the issue's base commit, compiled by the product.
- **Gold:** the lines the maintainers' fix edits (original coordinates). Insertions are
  located by their nearest non-blank neighbours (bench version `npkbench-1.1`).
- **Score:** *hunk recall@B* — the fraction of the fix's hunks whose lines appear in the
  selected spans when at most B tokens are selected (product accounting: chars/4 with
  separators). Also file recall, all-hunks-found, line recall, and a budget-free
  rank-order *tokens-to-find* cost.
- **Splits (fixed before any result):** `dev` = SWE-bench Lite test (300 tasks, 12
  repositories); `dev-fast` = 103-task repository-stratified subset of `dev`; `heldout`
  = SWE-bench Verified minus Lite (407 tasks), used only to confirm promotions;
  `ood` = Lite dev (23 tasks, 6 other repositories).
- Pinned by HuggingFace revision + SHA-256 and git commit. No dataset content is committed.

This measures localization evidence, not patch or answer correctness. It is Python-only
and issue-shaped; it favours implementation code by construction (fixes never edit tests),
which matters when judging path priors (see H6 below).

## Retrieval baseline (E000/E000b, dev-fast, 103 tasks, gold v1.1)

| Arm | 1K | 2K | 4K | 8K | 16K | median tokens to first gold |
|---|---:|---:|---:|---:|---:|---:|
| **Product default** (BM25 fields + raise relations) | **0.209** | **0.301** | **0.408** | **0.474** | **0.544** | 6,427 |
| without raise relations | 0.209 | 0.291 | 0.398 | 0.464 | 0.534 | 6,880 |
| `--python-members` (method-level blocks) | 0.277 | 0.316 | 0.384 | 0.461 | 0.532 | 6,526 |
| oracle (smallest block set covering all hunks) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | — (931 tokens mean) |

Hunk recall. File recall for the product default: 0.369 / 0.476 / 0.592 / 0.680 / 0.777.
Repository-macro hunk recall: 0.178 / 0.277 / 0.380 / 0.477 / 0.510. All gold hunks are
reachable within the top-1,000 candidates for 88/103 tasks; the median task needs
19,299 rank-order tokens before every gold hunk is covered.

### Where evidence is lost (product default)

| Budget | selected | ranked below the budget cut | not in top-1,000 | skipped by packing |
|---:|---:|---:|---:|---:|
| 2K | 43 | **83** | 19 | 8 |
| 8K | 67 | **64** | 19 | 3 |

(Counts of the 153 gold hunks.) **Ranking**, not packing, is the dominant loss. Of the
selected tokens, only 56% (2K) / 51% (8K) are implementation code; documentation takes
21-25%, tests 21-22%, examples 2%.

Concrete failure pattern: the issue *names* the code it concerns
(`django.core.exceptions.ValidationError`, `StaticFilesHandlerMixin`, `Signal.send_robust()`,
check id `models.E028`), but a flat OR over ~30-100 prose terms lets documentation and
tests that repeat the issue's vocabulary outrank the definition. 287/300 dev issues contain
code identifiers; 90/300 name the gold file or module; 64/300 contain a traceback.

## Compile and query costs (product as received)

Django @ `965d2d9` (3,164 files, 16,372 blocks), single process, under cProfile:

| Stage | Time | Share |
|---|---:|---:|
| `analyzed_text` (pure-Python field analysis) | 12.8 s | 30% |
| `_python_raise_sites` (second AST parse + full `ast.walk`) | 11.9 s | 28% |
| splitting incl. first AST parse | 7.2 s | 17% |
| scan / seal / inserts | ~11 s | 25% |
| **total** | **43.2 s** | |

Across the 103 dev-fast snapshots (4 concurrent builds): median compile 22.9 s (Django),
57.2 s (Sympy), 14.9 s (Matplotlib); packs average 38 MB. A long-issue query costs ~29 ms
uncontended on Django, of which ~21 ms is FTS5 scoring: common OR-terms make 58% of all
blocks match.

### Robustness

**46 of 103 snapshots cannot be compiled as received**: the build aborts on a single
NUL-containing, non-UTF-8 or credential-pattern file. That covers every Django (38/38),
Pylint (2/2) and Sphinx (5/5) snapshot and one scikit-learn snapshot (a false-positive
"OpenAI key" match). The benchmark removes those files before compiling and records them
per task, so baseline retrieval numbers are measurable at all.

## Ranked hypotheses (initial)

Ranked by expected value × probability ÷ cost; information gain breaks ties. "Cost"
includes the pack rebuilds a compile-side change forces on the benchmark.

| Rank | ID | Hypothesis | Lever | Expected effect | Cost | Info |
|---:|---|---|---|---|---|---|
| 1 | H1/E001 | Parse Python once, walk statements for `raise`, memoize term analysis | compile speed | ≥2× faster, logically identical packs | low | low, but multiplies experiment throughput |
| 2 | H3/E002 | Code-entity-aware queries: resolve identifiers the issue names against the definition index; up-weight them; resolve paths/traceback frames | ranking | +5-15 pts at 1-4K | low (runtime) | high |
| 3 | H2/E004 | Skip-and-report never-indexed unindexable files instead of aborting | robustness | 46/103 → 0/103 blocked snapshots | low | medium |
| 4 | H7/E003 | File-level evidence aggregation | ranking | + where several gold-file blocks match | low | medium |
| 5 | H4/H5 | Method-level granularity; structure-aware splitting of oversized classes | unit cost | better at ≥4K? | medium (rebuild) | high |
| 6 | H6/E006 | Implementation-first role prior (demote, never drop, tests/docs/examples) | budget composition | large here; **gaming risk** — needs justification beyond SWE-bench | low | medium |
| 7 | H10 | Query-conditioned trimming of large blocks with recoverable elision markers | unit cost | more regions per budget | medium | high |
| 8 | H9 | Multi-resolution context: skeletons for lower-ranked files, full text for top leaves | representation | file recall at fixed budget | medium | high |
| 9 | H8 | Drop very-high-df terms from long queries | latency (+ranking?) | ~2× faster long queries | low | medium |
| 10 | H14 | Incremental integrity / faster updates on large repos | update latency | seconds → sub-second | medium | medium |
| 11 | H13 | Collapse structurally near-duplicate siblings (same method across backends) | budget composition | small here | medium | medium |
| 12 | H17 | Conversation-memory workload (LongMemEval, MIT): compile chat histories; evidence recall; knowledge updates | new workload | tests generality beyond code | medium-high | high |
| 13 | H11 | Dense code embeddings with content-addressed vector reuse across commits | ranking | semantic-gap cases; CPU-heavy | high | medium |
| 14 | H12 | Pseudo-relevance feedback | ranking | small for long queries | low | low |
| 15 | H16 | Remove the abandoned proxy product (Product B, 4.1K LOC) | complexity | no metric change | medium | low |

### Outcomes of the initial ranking (see EXPERIMENTS.md for numbers)

| Rank | ID | Outcome |
|---:|---|---|
| 1 | H1/E001 | **Kept**: compiles 1.49x faster, identical artifacts (the term-memo part, E001b, rejected: no real gain) |
| 2 | H3/E002 | **Kept**: definition channel, held-out fix +5.7 to +10.3 points. Path/traceback resolution measured later: no headroom (the product already finds them) |
| 3 | H2/E004 | **Kept**: 46/103 -> 0/103 blocked snapshots |
| 4 | H7/E003 | Rejected: no gain |
| 5 | H4/H5 | E005 (every large block) rejected; E005c (top block only) **kept**: +13.9/+7.3 points at 512/1K |
| 6 | H6/E006 | Rejected as gaming: tests collapse, docs -14 to -40 points (docs-3) |
| 7 | H10 | Folded into E005c (member spans instead of elision markers) |
| 8 | H9/E017 | **Kept as opt-in** context map: a 25% map at 2K locates as much as full text at 4K |
| 9 | H8/E010, E043 | E010 inconclusive (speed gain small, ranking unchanged); for pathological lengths a 512-term cap (E043) is **kept**: 20,000 pasted identifiers 114 s -> 4 s on Django |
| 10 | H14/E014, E024 | E014 **kept** (updates 1.5-2.5x faster); bulk integrity (E024) rejected: ~2% in real compiles |
| 11 | H13/E013 | Rejected |
| 12 | H17/M000-M006 | Workload built; lexical tweaks rejected (M001-M003, M005); dense via the shipped semantic/hybrid mode **kept** as the documented memory configuration (+4 to +7 points) |
| 13 | H11/E012, E012b, E038 | Equal-weight fusion rejected for code (-9 to -11 fix at 1-2K); one-channel bge form passes the rule barely but needs dense vectors (inconclusive, cost); cheap static Model2Vec vectors lose fix recall (E038, rejected) |
| 14 | H12 | Not run; superseded by query-side experiments: segmentation and entities (E022, E023: no gain), then issue-form cleaning (E031, **kept**) and title/repetition weighting (E039, **kept**; held-out fix +2.3 to +9.9 points) |
| 15 | H16 | Not done: removing Product B is a user-visible deletion outside the evidence loop |

Added during the loop and kept: the docs-3 target and decision rule (E015/E015b), the
budget-gated test mate (E016b/E016c), issue-form cleaning (E031), title and repetition
weighting (E039) and the query-term cap (E043).

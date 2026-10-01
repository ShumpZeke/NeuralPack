# Evolution Log

An AlphaEvolve-style improvement loop over the repaired NeuralPack baseline:
OBSERVE → HYPOTHESIZE → IMPLEMENT → TEST → ATTACK → MEASURE → KEEP/DISCARD → REPEAT.

Current evidence rule: a promotion requires reproducible public-runtime
measurements, matched budgets and counterexamples. The old bootstrap rule below
did not establish generalization: the observations share inspected templates.
Cycle 1/2 significance, general quality and economic claims are withdrawn as
product evidence. Their entries are retained as a record of failed reasoning.

---

## Cycle 1 — Measurement was broken; conflict resolution was missing

### What I discovered

**1. The evaluation harness was degenerate.** 13 of 18 sealed tasks shared a
query string with a *different* correct answer. Per-task evaluation hides this
(each task is its own corpus); mixed-corpus evaluation does not — the question is
underspecified, so the metric rewarded luck. Every mixed-corpus number produced
before this cycle is void.

**2. There was no statistical power.** At n=15–18 a single task is worth 5.6–6.7
points. Measured directly: the same `seed_fraction` scored **−20.0** on one
budget and **+33.3** on another. Conclusions like the earlier "+11.1 from graph
expansion" were noise.

**3. The real bottleneck was not retrieval.** Four families scored *exactly* 0%.
On **15 of 15** such tasks the selector **retrieved the correct evidence** and
then also pulled in the contradicting variant — the deprecated version, another
service's config. Retrieval was fine. The missing capability was deciding which
of two disagreeing blocks the query wants.

```
gold found, no contradiction   :  0  (0%)   would PASS
gold found, BUT also forbidden : 15 (100%)  retrieval OK, no conflict resolution
gold not retrieved at all      :  0  (0%)   genuine retrieval miss
```

**4. Dependency expansion was doing literally nothing.** `no_expansion` measured
delta `+0.0` with CI `(0.0, 0.0)` — zero discordant pairs. Cause: at
`seed_fraction=1.0` the seed stage consumes the whole budget, so no expanded
block can fit. Expansion was dead code at the default configuration.

### What improved

**Evidence conflict resolution** (`npk/pack/conflict.py`, schema v3
`assignments` table). Constant assignments are extracted at compile time; when
several selected blocks assign *different* values to the same symbol, the one
whose path best matches the query's scope tokens wins, and variants under
deprecation markers (`legacy/`, `deprecated/`, `old/`) are demoted. It is
deliberately conservative: when the signals do not clearly prefer one variant,
everything is kept — a missing answer is worse than a redundant block.

Measured, paired bootstrap, **sealed** split (n=45), both budgets:

| | recall before | recall after | delta | 95% CI | significant |
|---|---:|---:|---:|---|---|
| budget 1500 | 40.0% | 62.2% | **+22.2** | (11.11, 35.56) | **YES** |
| budget 3000 | 44.4% | 66.7% | **+22.2** | (11.11, 35.56) | **YES** |

Confirmed independently on dev (+13.9, CI (4.65, 25.58), both budgets).

Per family at budget 3000:

| family | before | after |
|---|---:|---:|
| symbol_collision | 0.0% | **100.0%** |
| version_conflict | 0.0% | **100.0%** |
| config_indirection | 100.0% | 100.0% |
| distractor | 100.0% | 100.0% |
| multi_fact | 100.0% | 100.0% |
| multi_hop | 60.0% | 60.0% |
| dynamic_indirection | 0.0% | 0.0% |
| negative_constraint | 0.0% | 0.0% |
| semantic_gap | 0.0% | 0.0% |

### What failed / was discarded

| Candidate | Result | Disposition |
|---|---|---|
| `seed_fraction` tuning (0.6–0.9) | Sign flips between splits and budgets; no CI consistently excludes zero | **DISCARDED** — noise |
| `expansion_depth=4` | +2.3 to +7.0, CI always spans zero | **DISCARDED** |
| `candidate_limit=200` | −7.0 to +4.7, CI spans zero | **DISCARDED** |
| Supersession (recency) | Exactly +0.0 everywhere | **NOT PROMOTED — untested, not disproven** (see below) |

**Supersession deserves care.** It measured +0.0, but investigation showed the
mechanism *never fired*: conversations compile to a single block (`main.py`, 1
block), so there was nothing to drop. That is an untested idea, not a refuted
one. Kept unwired with unit tests; retested in cycle 2 once conversations split
into turns.

### Infrastructure built

* `benchmarks/evolve.py` — champion/challenger harness with **paired** bootstrap
  CIs and McNemar-style discordant counts. Pairing removes task-difficulty
  variance, which dominates at small n.
* `benchmarks/tasks_hard.py` — every family now scoped by business domain, so no
  two tasks share a query with different answers. `assert_unambiguous()` guards
  it, and the semantic-gap families still never name their target symbol.
* `tests/test_conflict_resolution.py` — 14 regressions, including that
  resolution stays conservative without a scope signal and can never empty the
  context.

### Corrections to earlier claims

ADR 0004 claimed dependency expansion earned +11.1 points. **Retracted.** That
measurement came from the degenerate benchmark at n=18. Re-measured with CIs at
n=43–45, expansion's effect is `+0.0 (0.0, 0.0)` at the default configuration
because the seed stage leaves it no budget. It is retained but is *not* a
demonstrated improvement.

### Next highest-value hypotheses

1. **`semantic_gap` is 0% and the compiled pack has no embedding index.** The
   deterministic mode cannot bridge a query/answer vocabulary gap by
   construction. `--mode semantic` exists but has never been measured in the
   compiled architecture. Expected to be the single largest remaining win.
2. **`dynamic_indirection` is 0% and conflict resolution cannot help it.** Both
   `policies/aggressive.py` and `policies/conservative.py` sit under the same
   domain path, so path affinity ties and resolution correctly abstains. The
   disambiguating fact is *in the text*: `ACTIVE_POLICY = "aggressive"`.
   Hypothesis: **value-directed resolution** — follow an indirection variable to
   pick the live variant.
3. **`negative_constraint` is 0% because conversations are one block.**
   Hypothesis: turn-aware splitting, which would also finally test supersession.
4. **Recall is 66.7%, not the 72% the degenerate benchmark reported.** Every
   headline number in the README and ADR 0004 needs re-deriving on the fixed
   harness.

---

## Cycle 2 — Embeddings promoted; expansion demoted; two scaling walls removed

### What I discovered

**1. The embedding index was never measured in the compiled architecture.**
`--mode semantic` existed since the compiler landed but had never been run
through the evaluation harness. It is the single largest remaining win.

**2. Dependency expansion is subsumed by embeddings.** With an embedding index
present, expansion's per-family effect is **identically zero at every budget**,
and embeddings alone take `multi_hop` to 100% (expansion only reached 60%).

**3. The embedding channel was an O(N) Python loop.** `struct.unpack` plus a
scalar dot product per block: **81.7 ms** on 1,587 blocks against 1.3 ms for the
lexical channel. On a real repository that is seconds per query.

**4. The test suite had a 439-second test.** `test_no_secrets_in_git_history`
re-read identical blobs once per commit via a subprocess per file. It dominated
the suite and made the evolution loop painfully slow.

### What improved

| Change | Before | After | Evidence |
|---|---|---|---|
| Embedding channel (semantic mode) | 62.2% | **82.2%** | +20.0, CI (8.89, 31.11) @1500; +15.6, CI (6.67, 26.67) @3000 — **SIGNIFICANT** |
| Embedding scan latency | 81.7 ms | **11.5 ms** | 7.1× — columnar read + one BLAS matmul |
| Git-history secret scan | 439 s | **0.74 s** | 593× — one `cat-file --batch` over unique objects |
| Full test suite | 492 s | **32 s** | 15× faster iteration |

Per family at budget 800, semantic mode: `semantic_gap` 0% → **100%**,
`multi_hop` 60% → **100%**.

The faster secret scan is also *more* thorough: it walks all 344 objects in the
store including unreachable ones, where the old version only saw blobs reachable
from a commit. It was verified not to have become a no-op.

### Negative control

`no_conflict_resolution` measured **−22.2, CI (−35.56, −11.11)** at both budgets.
Removing cycle 1's promotion costs exactly what adding it gained — the effect is
real and stable across cycles, not drift.

### What failed / was discarded

| Candidate | Result | Disposition |
|---|---|---|
| `seed_fraction` 0.6/0.8 (retested with conflict resolution) | +2.2 to +4.4, CI always spans zero | **DISCARDED again** |
| Dependency expansion as a general win | +0.0 with embeddings; +4.4 without, CI spans zero | **DEMOTED to mode-dependent** |

**Dependency expansion is now enabled only for packs without an embedding
index.** Measured justification: on a deterministic pack it lifts `multi_hop`
40% → 60% and moves no other family, which is worth its 2.8× compile cost
(2.20 s → 6.22 s) because nothing else can follow an import chain. On a semantic
pack it changes nothing at all, so it is skipped.

### Corrections to earlier claims

ADR 0004's "+11.1 general win" for dependency expansion is **retracted** in the
code itself, not only in prose: the docstring now carries the measured table and
the mode-dependent policy.

### Next highest-value hypotheses

1. **`dynamic_indirection` is still 0%.** Conflict resolution correctly abstains:
   `policies/aggressive.py` and `policies/conservative.py` share a domain path,
   so path affinity ties. The disambiguating fact is in the text —
   `ACTIVE_POLICY = "aggressive"`. Hypothesis: **value-directed resolution**,
   following an indirection variable to the live variant.
2. **`negative_constraint` is still 0%.** Conversations compile to one block, so
   supersession cannot fire. Hypothesis: turn-aware splitting, which would also
   finally test the cycle-1 supersession mechanism.
3. **Semantic-mode compile costs 69 s for 1,587 blocks** (~23 blocks/s). That is
   the next scaling wall: batch size, ONNX/quantized encoder, or embedding only
   blocks that survive a cheap pre-filter.
4. **`semantic_gap` scored 100% at budget 800 but 75% at 3000.** A larger budget
   made it *worse* — more budget admits more near-miss noise. Worth attacking:
   the budget may want to be chosen per query rather than fixed.


## Cycle 3 — Public-runtime repair and pivot to competent retrieval

Evidence mode: **LOCAL**. Status: **PIVOT REQUIRED** for a differentiated
optimizer; compiler/runtime infrastructure retained. No generative API calls.
The historical comparator is commit `2e39d6926404bcc0421dcc54c93bee69e39b1f3f`.

### What was discovered

1. The economics corpus builder flattened folders and wrote fenced Markdown
   into `.py` files. Python parsing, lexical scope and dependency extraction were
   therefore evaluated on different source than the fixtures described.
2. `evolve.py` used a second implementation of selection. Its substring checks
   allowed a gold value in unrelated code to count as evidence, while treating
   every contradictory passage as an error. A comparison question can need both
   variants. These metrics do not establish answer quality.
3. The public runtime omitted separators from budget accounting, silently
   enlarged explicit budgets, accepted zero/invalid budgets, and called empty
   failed selections 100% savings. Fourteen new parameter-expanded counterexample
   tests initially failed across these contracts and the proposed splitter.
4. Conflict filtering removed historical/comparison evidence and could delete a
   separate requested fact sharing a block with a conflicting constant.
5. The interrupted turn-splitting candidate lost preambles, misclassified code
   examples and separated corrections from facts. Even after source-preservation
   repairs it reduced required fixture retention. Source-order supersession
   blindly discarded earlier facts when the final turn was just a question.
6. Failed compilation deleted an existing artifact before validating its source.
   An output pointing at an ordinary source file also overwrote that source.
   Three failure-atomicity counterexamples initially failed.
7. A fallback test asserted `out == identity(out)`. A query mutation was initially
   paired with a direct-retrieval test that bypassed extraction. The planner also
   had a second suffix-based extraction path. New regression coverage uses the
   current question in a separate message and checks its delivery to retrieval.

### What changed

- Budget accounting includes joined-context separators under the documented
  chars/4 estimator. Explicit budgets are never enlarged. Failed retrieval reports
  `fallback_required` and undefined reduction; callers must obtain more evidence.
- Conflict filtering abstains on comparisons/history and other named facts.
  It is now disabled by default. These safeguards are heuristics, not a proof of
  completeness. Graph expansion is also disabled by default.
- **BM25 became the default runtime.** Hybrid symbol/lexical/local-embedding
  fusion remains an explicit experimental option, including a CLI flag. No model
  is loaded by the default selector, even for a semantic artifact.
- Removed independent turn splitting, source-order supersession, literal-to-path
  voting, silent budget escalation and a model-pricing lookup that did nothing.
- Compilation builds a private artifact and publishes by same-filesystem rename.
  Failed builds preserve previous bytes; source outputs and active SQLite sidecars
  block replacement. Updates use a rollback journal, avoiding WAL sidecar work on
  reads. This does not promise power-loss recovery or concurrent writer safety.
- Compiler-rule changes require recompilation before incremental update. The
  Git-history scan now fails if its batch-read subprocess fails.
- Corrected corpus materialization and paired public-runtime diagnostics record
  source hashes, provenance, source-scoped fixture retention and actual estimated
  budget usage. The independent BM25 baseline loads its selected rows from SQLite,
  rather than receiving a preloaded block cache unavailable to the runtime.

### Matched-budget measurements

The corrected diagnostic has 45 previously inspected template tasks in one pack:
468 files, 2,220 blocks, **703,108 estimated available tokens per request**.
460 file contents are unique (2,770,691 unique source bytes). Most context is
installed public-library source; the questions themselves remain synthetic.
These are correlated observations, not 45 independent real-world tasks. No
answer accuracy, confidence interval or dollar-savings claim is made.

| Context budget | Historical default fixture retention | Repaired default (BM25) | BM25 baseline | Historical budget violations | Repaired violations |
|---:|---:|---:|---:|---:|---:|
| 800 | 64.4% | 91.1% | 91.1% | 30/45 | 0/45 |
| 1,500 | 73.3% | 91.1% | 91.1% | 23/45 | 0/45 |
| 3,000 | 71.1% | 91.1% | 91.1% | 30/45 | 0/45 |

At budget 1,500, median public query time was **12.77 ms → 4.38 ms**.
The direct BM25 baseline on the repaired artifact took 1.99 ms. Compilation was
1.160 s → 1.191 s in this paired run; the small difference is not a robust speed
claim. Repaired default selection matches the baseline's evidence, rather than
beating it. The infrastructure still adds reporting/accounting overhead.

Before the journal-mode change, the repaired local MiniLM hybrid achieved
88.9% / 91.1% / 93.3% at budgets 800 / 1,500 / 3,000, versus BM25's 91.1% at all
three budgets. At 1,500, hybrid took 19.13 ms and BM25 6.44 ms; semantic compile
cost about 50.3 s. A one-fixture advantage at the largest budget is insufficient
for a general promotion. Local embeddings do solve a separate vocabulary-gap
regression, so the explicit option remains available.

The discarded independent-turn candidate achieved 60.0% / 60.0% / 57.8% with
fusion, versus 64.4% / 68.9% / 66.7% after restoring source windows. Its BM25
retention was 82.2%, versus 91.1% with windows. It did not earn its complexity.

### Verification and reproducible evidence

- Full suite: **305 passed, 1 skipped** in 24.63 s. The skip remains explicit.
- Mutation checks: **5/5 killed by assertions**, including dependency identity,
  query erasure, fallback bypass, budget override and public query erasure.
  Mutants run in disposable snapshots; no checkout/reset touches the worktree.
- No provider calls were made. Local semantic evaluation uses cached encoder
  weights with model downloads disabled. Old NIM answers are not reused as
  evidence for this changed runtime.
- `experiments/results/cycle3-summary.json` contains paired summaries and exact
  source hashes; full per-task records are losslessly compressed in matching
  `.json.gz` files. `cycle3-mutations.json` and `cycle3-tests.xml` record checks.
- Reproduce with `python -m benchmarks.compiled_validation --output <file>` and
  `python -m benchmarks.contract_mutations`.

### Disposition and next highest-value hypotheses

**Keep:** portable compilation, provenance, explicit failures, hard estimated
budgets, correct source materialization and competent BM25 selection.
**Discard:** superiority claims from the old harness, automatic conflict deletion,
automatic graph traversal, turn splitting and recency-based evidence deletion.
**Experimental:** hybrid retrieval and graph/context reasoning, pending stronger
source-grounded tasks and real target-model answers at matched budgets.

1. Query accounting still scans the block table to compute available tokens.
   Move reusable totals into compiled metadata and profile across corpus sizes;
   this may remove a remaining query-time scaling cost.
2. `verify()` hashes stored hash fields rather than rehashing block text or derived
   indexes. Add corruption regressions and establish a genuine artifact-integrity
   contract before calling it an integrity guarantee.
3. Build independently reviewed tasks from actual repository behavior and docs.
   Evaluate missing evidence, misleading variants and answer correctness, not
   just positive fixture retention. BM25's remaining vocabulary-gap failures are
   a useful starting point; template tuning is not a breakthrough search.


Final semantic rerun, after the default-policy and journal changes:
`cycle3-final-semantic.json.gz` confirms 91.1% for the new lexical default at all
three budgets. Opt-in hybrid retains 88.9% / 91.1% / 93.3%. At 1,500, default /
hybrid / direct BM25 median times are 4.86 / 15.58 / 2.43 ms; semantic compilation
is 53.53 s. The one-fixture advantage at 3,000 remains an experimental observation.
All candidate arms have zero measured budget violations. No component earns a
general quality-superiority claim from this result.


## Cycle 4 — Real artifact integrity and cached context accounting

Evidence mode: **LOCAL**. General retrieval verdict remains **PIVOT REQUIRED**;
this is an infrastructure improvement, not a differentiated selection algorithm.
Comparator: cycle 3 commit `cbf7c4f`.

### Discovery and counterexamples

The verifier hashed saved hash strings, not block text, and omitted symbols,
provenance, FTS postings, dependencies, embeddings and metadata. Nine content/index
changes passed as intact. Old version checks also accepted 0, negative and older
incompatible versions. Available tokens used a sum of individually rounded block
estimates, omitting separators (a 21-token source was reported as 19).

The first new test batch reproduced **14 failures / 15 cases**. The permanent
integrity suite now has 19 cases including FTS storage corruption, trusted-root
comparison, read-only verification, VACUUM stability and failed-update rollback.

### Implementation and an unsuccessful first attempt

Artifact **v4** requires recompiling older packs. Its canonical digest covers
schema plus typed, length-framed real data, including the FTS storage tables.
Verification also checks SQLite structure, foreign keys and actual block hashes.
The read-only verifier returns an explicit invalid result on malformed/truncated
artifacts. `verify(path, expected_root=...)` accepts a separately trusted digest.
A self-recorded hash cannot authenticate a publisher who can rewrite that hash.
The query fast path does not silently perform a full verification on every call.

The first full-data hash was unstable: FTS5 buffered postings until commit, so a
new artifact failed its own check. An `integrity-check` command did not fix that.
A savepoint flushed the pending postings inside the existing transaction, before
computing the root. This behavior was reproduced on SQLite 3.49.1 and is supported
by SQLite's [FTS5 xSavepoint implementation](https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_main.c).
No early commit is needed; failed updates roll back data and digest together.

Available-context accounting now runs at compile/update and is stored in the
manifest, with separators and Unicode counted by the same chars/4 estimator as
selection. Per-query accounting no longer scans the whole block table.

### Paired public-runtime evaluation

Same corrected 703,108-token available corpus and 45 reused template tasks,
with budgets 800 / 1,500 / 3,000. Required-source fixture retention remains
**91.1% at every budget**, with **zero budget violations**, matching direct BM25.
There is no new answer-quality claim and no generative model call.

At budget 1,500, median runtime latency improved **4.50 → 2.01 ms**.
Compilation increased **1.30 → 1.89 s** because contents and indexes are now
hashed. The direct BM25 baseline was 2.06 → 2.12 ms; the runtime's prior extra
accounting cost is largely gone. Small differences near 2 ms are measurement
noise, not evidence that one implementation has superior retrieval.

### Scale-dependent costs

Actual installed public-library sources; each row is its own per-request corpus.
Sizes are measured after compilation, not claimed from requested/cumulative totals.
Both arms build dependency indexes. Times are milliseconds; single build/update
observations and repeated warm queries are diagnostic, not performance guarantees.

| Available tokens | Compile before → after | Warm query before → after | One-file update before → after | Full verification after |
|---:|---:|---:|---:|---:|
| 2,002 | 145.8 → 144.5 | 0.70 → 0.66 | 19.0 → 16.9 | 4.4 |
| 31,063 | 169.4 → 213.2 | 0.85 → 0.74 | 22.3 → 41.3 | 28.5 |
| 51,307 | 193.9 → 240.2 | 0.93 → 0.83 | 23.7 → 73.2 | 50.1 |
| 94,582 | 253.9 → 337.1 | 1.19 → 0.99 | 37.9 → 104.5 | 86.2 |
| 236,175 | 462.8 → 726.3 | 2.29 → 1.55 | 77.2 → 244.7 | 233.0 |

At 236K, 1% (2 files) and 10% (11 files) updates took **255.4 / 386.8 ms**,
versus **71.8 / 175.8 ms** before. Files not changed were not reparsed, but the
integrity root and dependency work still scale with the repository. This is an
explicit remaining bottleneck. Profile-process RSS was about 27–34 MB and the
largest artifact about 5.36 MB; process RSS includes interpreter and earlier work,
not just artifact memory. Full data are in `cycle4-scale.json`.

### Verification, disposition and next hypotheses

- Full suite: **324 passed, 1 skipped** in 27.34 s.
- Mutation checks: **6/6 killed by assertions**, including a new digest-bypass
  mutant. Existing query, fallback and dependency tripwires remain effective.
- Full per-task paired records: `cycle4-integrity-deterministic.json.gz`;
  summaries and hashes: `cycle4-summary.json`; tests/mutants: `cycle4-tests.xml`
  and `cycle4-mutations.json`.
- Reproduce the scale test with `python -m benchmarks.compiled_scale --output <file>`.

**Keep:** actual integrity verification, atomic data/digest updates, supported
version enforcement and cached context totals. **Discard:** metadata-only
integrity claims and digesting unflushed FTS storage. No 10x general performance
or answer-quality claim is justified.

Next highest-value hypotheses:

1. Use a measured hierarchical or incremental digest to avoid rehashing unrelated
   data on every edit, while retaining complete independent verification.
2. Remove the dependency-index rebuild cost from the default compiler unless a
   real retrieval workload proves it useful. Keep explicit experimental support.
3. Expand from synthetic templates to actual repository questions, with scoped
   evidence requirements and target-model answer checks. Investigate selective
   deterministic/local-semantic escalation for BM25's semantic-gap failures.
4. Audit source admission (including aliases/symlinks and secrets in ordinary
   source files) and local model loading before strengthening privacy claims.


## Cycle 5 — Idempotent updates, persisted graph policy, real-code oracles

Evidence mode: **LOCAL**, plus one authenticated NIM model-catalog read (zero
new generative calls). Status remains **PIVOT REQUIRED** for differentiated
retrieval. Comparator: `3bd73e7`.

Five initial policy tests failed: graph construction was still a compiler
default, updates forgot a disabled graph setting, graph enabling without source
changes did nothing, and a no-change update rehashed the entire artifact.
Two CLI tests also failed: empty failed retrieval and failed verification both
returned exit status zero.

The compiler now omits dependency indexing by default, persists its setting,
and applies explicit enable/disable changes independently of source edits.
`compile --deps` enables the experiment; `update --deps` / `--no-deps` changes
it, while an ordinary update preserves the saved policy. Earlier v4 artifacts
without a policy marker retain the historical enabled assumption unless the
caller explicitly changes it. A true no-change update does no reindexing,
sealing or artifact rewrite. It still reads/hashes the source tree: this is
not constant-time change detection. CLI failure exit codes now match their JSON.

### Measured costs

Per-request available sizes; milliseconds. Each update timing is one diagnostic
observation, not a performance guarantee. Compare identical source material.

| Available tokens | No-change update before → after | One-file edit before → after |
|---:|---:|---:|
| 2,002 | 7.84 → 1.57 | 27.74 → 25.67 |
| 31,063 | 33.21 → 3.65 | 48.36 → 40.72 |
| 51,307 | 54.42 → 9.95 | 65.46 → 61.50 |
| 94,582 | 84.78 → 8.30 | 110.83 → 94.42 |
| 236,175 | 204.84 → 23.40 | 257.78 → 198.94 |

The measured no-change speedup spans about 5–10x, depending on size; real edits
improve less because full integrity hashing remains. The ~10x observation is
specific to unchanged-source refresh near 95K, not an overall compiler claim.
Compilation of the 703K mixed corpus was effectively unchanged (1.978 vs 1.977 s).
Source-scoped fixture retention stayed 91.1% at all three context budgets,
matching BM25, with zero budget violations. There is no new quality win.

Full suite after core/CLI changes: **332 passed, 1 skipped**, 32.24 s.
All **6 mutation checks** still fail under their targeted broken implementation.
The added real-code oracle test also passes separately. Evidence:
`cycle5-scale.json`, `cycle5-public-deterministic.json.gz`, `cycle5-summary.json`,
`cycle5-tests.xml`, `cycle5-mutations.json`.

### New research foundation

`benchmarks/repository_tasks.py` contains 12 curated questions about actual
urllib3 2.7.0 behavior. Its answers are produced by executing the pinned library
with network connections blocked, not by an LLM grader or substring retention.
The cases cover disabled versus zero retry budgets, POST error categories,
empty allowlists, status eligibility versus exhaustion, backoff after redirects,
a zero Retry-After header, server-delay caps, immutable retry state, pool capacity,
and redirect header/method changes. Exact source file hashes and required spans
are recorded in `repository-oracles-v1.json`.

These are developer-known tasks, not sealed independent observations. Full
method/assignment spans are conservative coverage diagnostics, not proven minimum
sufficient context. Actual model answers remain to be measured. The NIM catalog
confirmed the existing 11B model is available; no key was printed.

**Keep:** skipped no-op work, explicit/persisted compiler policy, meaningful CLI
failures and executable real-code oracles. **Discard:** default unused graph
construction and treating status zero as compatible with failed CLI operations.
A more complicated incremental digest has not yet earned implementation.

Next highest-value hypothesis: the compiler cuts large Python classes at arbitrary
line windows. Natural method boundaries may retain the conditions needed to
answer these real questions at smaller budgets. Benchmark that challenger,
then use the authorized NIM endpoint for answer-quality validation, including a
no-context control to expose answers obtainable from model memory alone.

## Cycle 6 — method chunks and real answer validation

**EMPIRICAL. Verdict: PIVOT REQUIRED.** No promotion over ordinary BM25.
Comparator: `a06f397`; the default compiler still uses its previous chunking.
This cycle used LOCAL compilation/retrieval and explicitly authorized LIVE NIM
answer calls, with exact request caching labelled REPLAY. There were zero
generative optimization calls. The new answers supersede neither the independent
audits nor their standards; old headline reports remain invalid evidence.

### Hypothesis and implementation

Large Python classes were cut into arbitrary line windows. A tiny relevant method
could consequently require more context than its own source would need. The
experimental `compile --python-members` policy emits disjoint method spans and
retains class headers, constants, decorators, nested classes and dynamic class
bodies as original source. Updates preserve the policy. Oversized methods can
still be windowed; this is not a universal semantic-boundary guarantee.

A permanent counterexample has a small target method behind many irrelevant
methods: the old representation cannot fit it in 40 estimated tokens, while the
experimental representation can. Other regressions check exact source-line
coverage, nested classes/decorators, and incremental persistence. The added
class-member-erasure mutant is killed by an assertion, as are all six existing
critical mutants.

### Frozen real-code workload

The available source is the actual installed urllib3 2.7.0 package: 36 Python
files, approximately 104K neutral estimated tokens **per request**, not cumulative
totals. Rendered source with provenance headers is 104,605 estimated tokens. The
full NIM prompts reported about 81,810 actual input tokens at the median. These
are different accounting systems and are not interchangeable.

The 12 developer-known questions have network-free executable library oracles.
Full method/assignment spans are conservative structural diagnostics, not true
MSC. Selection uses the public runtime. All retrieval arms sweep 500, 1,000,
2,000 and 4,000 chars/4 token budgets including rendered source headers. Actual
answer validation uses the fixed 2,000 budget, identical question/system wrappers,
temperature zero, and 384 output tokens for every arm. No question or selection
algorithm was tuned from these answer outputs.

At 2,000 estimated tokens, all designated source spans were present in 2/12 old
BM25 selections, 6/12 method BM25 selections and 2/12 hybrid method selections.
At 4,000, the corresponding counts were 8/12, 8/12 and 3/12. Mean individual-span
coverage at 2,000 was 41.7%, 66.7% and 50.7%. Coverage did not predict a net answer
win. It must not be reported as answer accuracy or evidence sufficiency.

The optional hybrid used a real local `sentence-transformers/all-MiniLM-L6-v2`
encoder, not n-gram vectors. The local cache snapshot observed after the run was
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; package versions and source/code hashes
are in the archive. This is observed provenance, not yet an enforced runtime
weight-identity contract.

### Actual answers and counterexamples

Target: `meta/llama-3.2-11b-vision-instruct`, also confirmed in response metadata.
Success requires the exact requested JSON values and keys. The secondary check
only removes one enclosing Markdown fence; it does not select a favorable object
from prose or execute generated code.

| Arm | Completed / planned | Strict success | Fence-normalized success | API failures |
|---|---:|---:|---:|---:|
| No context | 12/12 | 0 | 1 | 0 |
| Full context | 10/12 | 0 | 0 | 2 |
| BM25, old chunks | 12/12 | 3 | 3 | 0 |
| BM25, method chunks | 12/12 | 3 | 3 | 0 |
| Hybrid, method chunks | 10/12 | 3 | 4 | 2 |

The method challenger gains `retry_after_eligibility` and loses
`redirect_header_scope`: **one win, one loss, ten ties**. The hybrid's extra
fence-normalized successes are not enough to promote it: two responses are
missing, the sample is small, and a formatting change affects its score.

All ten completed full-context answers violate the requested JSON contract;
eight hit the output cap. They often propose code changes instead of answering.
This weak full-context result is not proof that retrieval beats strong modern
answering systems. The no-context control also exposes one answer obtainable
without retrieval after removing its Markdown fence. No retention percentage is
computed against a zero baseline.

The disabled-versus-zero question demonstrates a different failure: the method
selection includes both designated methods, yet the model incorrectly returns
`MaxRetryError` for both cases. Its actual wrong answer is a permanent grading
regression. Presence of source spans is not proof of comprehension.

The first one-task canary made five requests; the subsequent full run made 54
new requests. There are **59 unique recorded 11B attempts**, including four API
failures. Five canary answers and one identical cross-arm prompt are reused as
REPLAY. API failures are missing quality observations, not wrong answers or free
successful reductions. Raw responses and usage are retained without credentials.
There are no automatic retries.

The source header format and strict scoring were fixed before the LIVE sweep.
Fence-normalized scoring was added as an explicitly secondary diagnostic after
the first responses exposed formatting failures. This is development evidence,
not a sealed independent benchmark. The 11B sweep partially overlapped a separate
90B availability/answer canary, so endpoint timing is not a controlled comparison.

The `meta/llama-3.2-90b-vision-instruct` one-task canary timed out on all five
predeclared arms, including no context. It provides no answer-quality evidence.
Those five attempts are archived separately in `cycle6-90b-canary.json.gz`.
There were **64 unique recorded LIVE attempts across both models** in this cycle;
the timed-out requests may have consumed provider work despite missing responses.

### Costs and decisions

On the initial 104K LOCAL sweep, old BM25 queried in about 2.53 ms median at 2K,
method BM25 in 2.65 ms and hybrid in 7.16 ms. Compilations took approximately
0.37 s, 0.42 s and 17.16 s respectively, including the semantic arm's cold local
encoder work. These single-run measurements do not establish a speed guarantee.
Actual median 11B prompt input was 1,632 old-BM25 tokens and 1,631.5 method-BM25
tokens; the new representation did not deliver a net answer or input-cost win.
No verified billing rate was used, so dollar cost and dollar savings remain N/A.

Additional scale checks use identical source-derived queries in each arm:

| Available estimated tokens, old → method | Compile ms, old → method | Artifact bytes, old → method |
|---:|---:|---:|
| 2,002 → 2,002 | 174.6 → 165.2 | 159,744 → 159,744 |
| 31,063 → 31,065 | 197.2 → 209.7 | 749,568 → 778,240 |
| 51,307 → 51,312 | 239.2 → 254.1 | 1,204,224 → 1,286,144 |
| 94,582 → 94,592 | 354.9 → 357.7 | 2,093,056 → 2,256,896 |
| 236,175 → 236,199 | 679.2 → 805.8 | 5,275,648 → 5,722,112 |

The slight available-token difference is from block separators, not extra source.
Warm literal-name lookups are about 0.6–0.8 ms here, a simpler query workload than
the behavior questions above. At the largest scale, a one-file edit takes
234.3 → 243.8 ms; full integrity hashing still limits incremental speed. The
profile now records the **actual changed-file fraction**: on small corpora,
rounding a requested 1% change to one file can be much more than 1%.

**Keep:** executable real-code oracles, explicit answer/transport/format records,
and an optional method-chunk experiment for future tests. **Do not promote:**
method chunks, hybrid fusion, graph expansion, or a claim of greater answer
accuracy. No current evidence supports a breakthrough or verified economics.

Next highest-value hypotheses: (1) establish a functioning stronger answering
baseline and new tasks before tuning retrieval from these failures; (2) repair
and attack encoder identity/cache isolation before relying on semantic artifacts.
Inspection found process-global encoder state and a delimiter-based embedding
cache key, while pack querying does not validate encoder identity against the
manifest. These are concrete follow-up risks, not repaired claims in this cycle.
Also remove remaining old headline prose in the legacy embedding module.

Evidence: `cycle6-repository-live.json.gz` includes original response records,
task/source/code provenance and the frozen run; `cycle6-repository-summary.json`
separates metrics; `cycle6-repository-local.json.gz` retains the preliminary LOCAL
sweep; `cycle6-scale.json`, `cycle6-tests.xml` and
`cycle6-mutations.json` record performance and checks. Reproduction commands are
in README. Generated copies of public source and scratch packs stay outside Git.

Final full suite: **343 passed, 1 skipped** in 31.10 s. Mutation testing:
**7/7 killed**, counting assertion failures rather than import errors or timeouts.

## Cycle 7 — encoder isolation and artifact identity

**EMPIRICAL. Verdict: PIVOT REQUIRED.** Correctness repairs, not a quality
promotion. Comparator: `5338df4`. This cycle made zero generative API calls.

### Reproduced failures

Six initial synthetic encoder tests failed on the committed implementation:

- `["alpha|NPKSEP|beta"]` and `["alpha", "beta"]` shared a cache key. The second
  call returned one vector when two were requested.
- Encoders with different truncation settings reused a cached vector.
- A missing second encoder borrowed the first encoder's loaded weights.
- A failed first load prevented another encoder from loading.
- Runtime loaders did not explicitly disable network fetching.
- The cache limited entry count, but ignored vector bytes. A 1,024-byte test
  budget retained 2,400 bytes of synthetic tensors.

Eight additional artifact tests failed: the compiler labelled a synthetic encoder
as MiniLM, querying accepted a different encoder with the same dimensions,
incremental updates mixed settings or silently omitted embeddings when weights
were missing, a previously unembedded pack indexed only its changed file without
fixing metadata, and incomplete/ragged/nonfinite vector batches were published.
The synthetic encoders are deterministic plumbing fixtures, not semantic models
or answer-quality measurements. Before-fix failure XML is preserved.

### Repairs and boundaries

Encoder instances now own their model, tokenizer, failed-load state and cache.
The default factory remains shared, with initialization protected by a lock.
Cache keys frame batch elements and settings using canonical JSON before hashing;
the cache evicts by both 64-entry and 16-MiB tensor-data limits. Inference and cache
access on one instance are serialized. This bounds cached tensors, not total
Python/model memory across arbitrary numbers of instances.

Runtime loading uses `local_files_only=True`, `trust_remote_code=False`, and
safetensors. The default model is pinned to MiniLM revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, verified against its
[upstream snapshot](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41).
An actual fresh cached-model load and query succeed with socket connections
blocked. Missing weights remain an explicit offline condition, and model
installation is separate. A failed instance must be replaced after installation.

Artifacts record the actual encoder ID, resolved revision, maximum sequence
length, pooling rule and document character limit. Query and update operations
check identity before mixing stored/query vectors. Batch row counts, dimensions
and finite values are validated before publication. Missing/incompatible encoders
roll back updates to an existing semantic index. If the original build had no
embeddings, the next source-changing update with available weights indexes every
block. Metadata and CLI compile/update statistics report unavailable/indexed/empty
states; deleting every source resets the index metadata.

Old semantic artifacts without an identity contract must be recompiled for hybrid
retrieval; default lexical retrieval still works. Old and new deterministic packs
remain format v4. The recorded encoder revision assumes trusted external model
files and Python libraries: it is not a byte-level authentication scheme for
those external dependencies. No custom model-loading code is authorized by an
artifact. Old unsupported headline prose was removed from the legacy encoder and
fusion modules rather than being retained for compatibility.

### Post-fix evidence

The paired public-runtime sweep used a per-request available context of 703,108
estimated tokens, 468 source files and 2,220 embedded blocks. It ran 45 previously
inspected templates, three methods and 800/1,500/3,000 token budgets. All **405
rows match before/after in every non-latency field**, including selected source
paths, spans, hashes, token counts, seed failures and retention diagnostics.
There are zero budget violations. These are correlated development fixtures,
not independent answer-quality evidence.

Default BM25 source-scoped fixture retention remains 91.1% at all budgets. Hybrid
retention is 88.9%, 91.1% and 93.3%, respectively, unchanged by the repairs.
The larger-budget hybrid difference does not establish a general advantage and
does not justify default promotion. The cycle-6 real-answer limitations remain.

Observed semantic compile time was 50.48 → 51.06 seconds. Hybrid median query
times were 17.53 → 18.83 ms at 800, 12.17 → 13.18 ms at 1,500, and 11.78 → 12.20 ms
at 3,000. Parts of this run overlapped unit/mutation checks, so these timings
are **not a controlled speed comparison**. No performance improvement is claimed.
The paired run preceded a final addition of status-reporting fields; subsequent
changes did not modify ranking or embedding calculations.

Final suite: **362 passed, 1 skipped**, 31.78 seconds. All **9 mutation checks**
are killed by assertions, including restored cache aliasing and an encoder
identity bypass. Additional regressions cover legacy artifacts, query vector
dimensions, explicit lexical degradation and removing all indexed sources.

**Keep:** isolated state, framed/bounded cache, offline model loading, explicit
encoder identity and atomic semantic updates. **Discard:** cross-model sharing,
delimiter-only keys, silent partial embedding indexes and old semantic headline
claims. No encoder, graph system or new chunking policy was promoted on quality.

Next highest-value hypothesis: a one-line edit still re-embeds every block in its
file. Reusing vectors for unchanged block text under the same checked encoder
contract could produce a substantial incremental-update gain. Benchmark this on
real source, including failures, duplicate text, changed spans, model mismatch,
and comparison with fresh compilation. Stronger live answering validation and
new independently held-out tasks remain necessary; the earlier 90B timeouts do
not establish a permanent goal blocker.

Evidence: `cycle7-encoder-before.xml.gz`, `cycle7-pack-encoder-before.xml.gz`,
`cycle7-semantic-paired.json.gz`, `cycle7-summary.json`, `cycle7-tests.xml`, and
`cycle7-mutations.json`. Raw timing and source provenance are retained rather
than replaced by headline summaries.

## Cycle 8 — reuse unchanged embeddings; remove update-history ranking bias

**EMPIRICAL. Verdict: PIVOT REQUIRED.** Comparator: `857bc1f`. Zero generative
API calls. These are infrastructure improvements; answer-quality superiority
over strong retrieval remains unestablished.

### Discovered and repaired

An edit to one method re-encoded all blocks in its file. Four initial regressions
failed. Semantic updates now temporarily retain vectors from replaced/deleted
files, then reuse them only when both the hash and exact text match. The existing
encoder identity check still runs, including when every vector is reused.
Malformed stored vectors and failed new batches roll back the transaction.
Duplicate text can retain multiple source occurrences; paths and line spans are
regenerated from current source. Renames can reuse old vectors. Deletion-only
updates do not copy vectors they cannot reuse. Unchanged files still skip parsing;
changed files are still parsed and reindexed in full. This is not global
deduplication or a cross-artifact cache.

The first real-source benchmark found a second, pre-existing failure: incremental
and fresh method-chunk artifacts disagreed on 8/36 queries after an edit, line
shift, or rename, even with byte-identical vectors in the old implementation.
Some cases selected different files, not merely a different presentation order.
Lexical, symbol and dense ranking broke equal scores using insertion history.
Four additional regressions reproduced the issue, including the scalar dense
fallback. Equal scores now use binary source path order and block ordinal.
The dense NumPy branch uses a stable sort; the scalar branch inherits the same
source ordering. No relevance score or retention threshold was tuned.

### Real-source incremental measurements

`benchmarks.embedding_update` copies the installed urllib3 2.7.0 source (36 Python
files), records source hashes, and invokes old and current code in separate
processes. Available context is about 104,287 estimated tokens with default
windows and 104,298 with experimental method chunks, per query. One edited file
is 2.8% of this corpus's files, not a 1% update.

Each operation has three independent baseline-restored samples. The local MiniLM
weights are warm; the embedding result cache is cleared before each update.
Actual submitted rows are counted by wrapping the encoder API independently of
the new compiler statistics. Times below are median total update latency,
including scanning and integrity sealing. Model-loading time is separately
recorded, not included in these warm-update numbers.

| Chunk policy / edit | Old encoder rows → new | Old → new update ms |
| --- | ---: | ---: |
| Default / one constant | 8 → 1 | 380.7 → 310.5 |
| Default / leading blank lines | 8 → 1 | 378.1 → 264.0 |
| Default / rename | 8 → 0 | 627.5 → 244.3 |
| Method chunks / one constant | 22 → 1 | 1,137.8 → 255.8 |
| Method chunks / leading blank lines | 22 → 1 | 1,207.7 → 266.6 |
| Method chunks / rename | 22 → 0 | 913.6 → 217.5 |

The method-edit case improved about **4.4× end to end**, not 22×. The default
constant-edit improvement was only 1.23×. The deletion-only control was variable:
217.0 → 182.3 ms with default chunks, but 145.2 → 186.9 ms with method chunks.
Machine noise and SQL overhead remain visible. The earlier pre-tie-fix paired
run is retained as discovery evidence, not substituted for the final run.

After stable ordering, all **288/288** incremental/fresh query comparisons agree
on selected evidence, estimated tokens and seed-failure status across both
chunk policies, four update operations, and 800/2,000/4,000 budgets. These reuse
12 developer-known questions; they are not 288 independent tasks. Source text
and provenance agree. Vector key coverage agrees; the largest observed float32
component difference was `8.20e-8`, below the declared `1e-5` tolerance. Different
encoder batches need not produce bit-identical floating-point results.

`embedded` still counts all vector rows written. New `encoder_rows_requested`
and `embedding_rows_reused` counters distinguish actual submitted work from
reuse. Weights must still be available even for a fully reusable changed file.
Source scanning and full integrity sealing remain proportional to corpus size.
No method-chunk or semantic-quality promotion follows from this update result.

### Public-runtime checks and tradeoffs

The 703,108-token deterministic paired sweep has unchanged source-scoped fixture
retention: default NeuralPack and BM25 both 91.1% at all three budgets; optional
lexical/symbol fusion 64.4%, 68.9%, 66.7%. No budget violations. Equal-score
ordering changes evidence in 210/405 rows and token counts in three, without
changing these retention diagnostics. These are previously inspected correlated
fixtures, not actual answer accuracy. Default NeuralPack remains ordinary BM25.

The stable joins have a cost in this workload: default median latency changed
from 4.39/4.92/4.60 ms to 9.11/8.01/6.69 ms at 800/1,500/3,000 budgets. Compilation
was 3.95 → 4.09 seconds. A separate actual-library scale run showed approximately
1–2 ms warm simple-name queries over 2K/31K/51K/95K/236K contexts; old/new timing
differences varied in direction. That simpler workload cannot dismiss the
larger query regression. No universal latency improvement is claimed.

A same-connection SQL experiment rotated four methods over the same 45 queries
for four passes (first excluded from warm summaries). Median execution was
1.15 ms for the old unstable query and 2.12 ms for the stable join. A `rank`
variant took 2.03 ms and a materialized-match CTE 1.85 ms; both matched the stable
reference in all 135 warm comparisons. The old query matched in only 54/135.
SQLite documents a possible `rank` sorting optimization in its
[FTS5 reference](https://www.sqlite.org/fts5.html#sorting_by_auxiliary_function_results).
Here neither challenger earned a production change: gains were about 4% and
13% of this step, with no answer-quality benefit. Keep the simpler stable join
and record the cost. `cycle8-sql-order.json.gz` contains the exact SQL, query
plans, corpus hashes, harness hash and all observations. This isolates SQL
execution, not end-to-end runtime latency.

Final full suite at the measured production code: **376 passed, 1 skipped**.
All **11/11 mutations** are killed by assertions, including bypassing vector
reuse and restoring insertion-order lexical ties. Tests also attack hash
collisions, stale spans, duplicate occurrences, malformed vectors, unavailable
or incompatible encoders, and transaction rollback.
After staging, all eight credential tests pass, including tracked working-tree
and Git object-store scans. The six compressed cycle reports were additionally
decompressed and checked against the same credential patterns; no matches were
found. All 39 measured production-file hashes still match the final code.

**Keep:** exact-text vector reuse and consistent tie ordering. **Discard:**
whole-file encoder work for unchanged blocks and insertion-history tie breaking.
Retain method chunks and hybrid selection as experiments. No new answer-model
validation or dollar savings claim was produced this cycle.

Evidence: `cycle8-before.xml.gz`, `cycle8-order-before.xml.gz`,
`cycle8-update-paired.json.gz` (discovery, before tie correction),
`cycle8-update-final.json.gz`, `cycle8-summary.json`,
`cycle8-deterministic-paired.json.gz`, `cycle8-scale.json`, `cycle8-tests.xml`,
and `cycle8-mutations.json`. Production source hashes are recorded in the paired
reports. Reproduce with the commands in README and the comparator above.

Next highest-value hypotheses: establish a functioning stronger answer-model
control and new held-out questions before further retrieval tuning; investigate
cheap explicit source-path constraints as an alternative to blind channel
fusion. A newly inspected compiler boundary also warrants attack: source
scanning currently catches read errors and skips files. Test whether a transient
read failure during update can be mistaken for a deliberate deletion. No fix or
proven failure for that boundary is claimed in this cycle.

## Cycle 9 — reject incomplete source scans; qualify a newer answer model

**EMPIRICAL.** Comparator: `be5bcc3`. This cycle separates compiler correctness,
local performance, and LIVE answer-quality observations. No generative model
was added to compilation or query-time selection.

### Source-scan counterexamples and repair

Eight initial regressions failed. A read/stat failure on a source file, or a
directory-listing failure, allowed both compile and update to publish an artifact
without its evidence. The scanner treated an inaccessible directory as an empty
one. Invalid UTF-8 could silently turn `adm\xffin` into `admin`, changing a string
literal. A source file growing above the size cap disappeared as if deleted.

Scanning now raises `PackError` for those conditions. Both operations preserve
the previous artifact; initial compilation publishes nothing. Directory errors
are propagated through `os.walk`'s error handler. Diagnostics name the path and
error class without echoing file content or opaque OS messages. UTF-8 decoding
is strict, and eligible text above 2 MiB is rejected explicitly. Actual deletions
still remove evidence; excluded directories remain unopened. Empty files and
recognized binary content follow the existing exclusion policy.

Accepted UTF-8 source has unchanged representation, so this does not bump the
artifact/compiler format. Existing unsupported sources must be converted or
excluded before compilation. This is not a filesystem snapshot or a complete
defense against simultaneous writers, symlink substitution or arbitrary secrets
in ordinary source. Those broader claims are not made.

The full suite after this repair and answer-configuration tests passed **389
tests, 1 skipped**. All **12 mutations** were killed by assertions, including
restoring silent directory-scan failure. Additional cross-encoder benchmark tests
were added afterward; the final suite is recorded below.

### Before/after public-runtime measurements

All **405** rows in the 703,108-token paired deterministic sweep are identical
in every non-latency field. Default BM25 fixture retention remains 91.1% at all
budgets; optional lexical/symbol fusion remains 64.4%, 68.9%, 66.7%. No budget
violations. This is source-scoped fixture retention, not answer accuracy.

Single-run scale observations (old → new):

| Available tokens | Compile ms | Warm query median ms | Single-file update ms |
| ---: | ---: | ---: | ---: |
| 2,002 | 203.5 → 187.0 | 2.05 → 1.47 | 35.9 → 23.6 |
| 31,063 | 336.0 → 276.4 | 1.97 → 1.30 | 88.3 → 63.9 |
| 51,307 | 404.6 → 322.3 | 2.13 → 1.56 | 130.4 → 94.6 |
| 94,582 | 697.9 → 486.8 | 2.33 → 1.27 | 218.8 → 147.4 |
| 236,175 | 1,607.3 → 1,160.5 | 2.05 → 1.26 | 400.8 → 375.3 |

The selector did not change in this cycle. Faster query observations therefore
cannot be credited to the scanner repair; machine/cache noise is substantial.
No speedup is claimed. The raw report also retains initial-query, verification,
memory, disk, no-op, 1% and 10% update measurements and actual changed fractions.
Performance runs did not overlap CPU-heavy tests or each other, but a separate
network answer-model canary was active. Timing remains observational.

### Answer-model qualification

NIM's actual model listing exposed `deepseek-ai/deepseek-v4-flash-0731`.
The evaluator now accepts an explicit output cap and reasoning setting, both
included in cache identity and recorded in the run. Previous default requests
keep their original 384-token cap. The new requests use the model's documented
[reasoning controls](https://docs.api.nvidia.com/nim/re/reference/deepseek-ai-deepseek-v4-flash-0731-infer).
These are answering calls after evidence selection, never optimizer calls.

Three developer-known questions were frozen for canaries: disabled-vs-zero
retries, server delay caps, and redirect method/header changes. Each used supplied
relevant source spans and full source as separate controls. The supplied spans
come from the evaluator, not NeuralPack, and are not proven sufficient or minimal.
Different-size controls qualify the answer model; they do not establish a
matched-budget retrieval advantage.

Non-thinking (`none`, 2,048 output cap) completed all six requests: **2/3** correct
with supplied spans and **2/3** with full source. No format failures. Median
answer latency was 8.06 s and 21.53 s, respectively. Full prompts used approximately
101,608–101,618 actual input tokens per request, not cumulative context totals.

High reasoning (4,096 cap) completed only three of six: two small-source answers
and one full-source answer, all correct. The other requests had two timeouts and
one HTTP 502. Completed answers used 424/574/889 output tokens, versus 22–38 in
the non-thinking controls. Missing answers do not count as correctness failures
or successes. This is insufficient to establish a superior reasoning setting;
the functioning non-thinking configuration was selected for the larger run.

The next experiment freezes the same 12 existing questions and the current
retrieval implementations. It compares no source, full source, BM25 with default
windows, BM25 with experimental method chunks, and local hybrid retrieval. The
three retrieval arms share a 2,000 estimated-token budget including source
headers. Earlier exact full-context canary requests are reused and labelled
REPLAY. These remain developer-known questions, not a new independent holdout.

### Completed live retrieval comparison

All 60 task/arm observations are recorded. The sweep made **56 new answering
attempts**; three full-context canary requests and one identical selected-context
request were exact replays. Including both canaries, this cycle made **68 new
answering attempts**, plus the separate read-only model-list request. No failed
request was automatically retried. Five sweep requests failed in transport
(four timeouts and one HTTP 529); they have no answer-quality score.

| Arm | Correct / completed answers | Transport failures | Median actual input tokens |
| --- | ---: | ---: | ---: |
| No context | 3 / 12 | 0 | 115.5 |
| Full source | 7 / 11 | 1 | 101,618 |
| BM25 default windows | 5 / 10 | 2 | 2,010.5 |
| BM25 method chunks | 5 / 10 | 2 | 1,986.5 |
| Hybrid method chunks | 6 / 12 | 0 | 1,989.5 |

There were no format failures or output-cap hits in completed answers. On
mutually completed pairs, method chunks had **0 wins / 1 loss / 7 ties** against
default BM25; hybrid had **1 win / 1 loss / 8 ties**. Full source had **2 wins /
1 loss / 6 ties**. Thus neither candidate earns promotion. An apparent 6-versus-5
success-count difference is not a quality win when completion sets differ.

All retrieval arms use a common chars/4 budget including source headers. Actual
target token usage is recorded separately and varies by selected text. These
are not identically tokenized target prompts. The LOCAL sweep covers
500/1,000/2,000/4,000 budgets; LIVE quality here covers only the 2,000 budget.
Multi-budget live quality curves remain unfinished.

Full source can fail where selected context succeeds (`empty_allowlist`), and
selected context can fail where full source succeeds (`disabled_vs_zero`).
`eligible_but_exhausted` was wrong in every completed arm. These counterexamples
separate evidence selection from answer-model reasoning; full source and manual
span selection are not guarantees of a correct answer.

Median answering latency was approximately 13.5 s for the two BM25 arms, 13.9 s
for hybrid, and 19.2 s for full source. These are sequential observations with
uncontrolled provider load; some LOCAL retrieval timing also overlapped tests.
Full-source usage reports include **101,376 cached input tokens** in one request.
The summarizer now records how many answers report cache usage and their reported
cached-token total. No verified endpoint price was available; **no dollar-savings
or break-even claim** follows from the approximately 50× input-token difference.

The working newer model strengthens the baseline compared with the earlier 11B
format-failure run. It still does not establish an independent validation result,
high-confidence omission detection, or a differentiated optimizer.

### Real local cross-encoder challenger

`benchmarks.repository_rerank` tested cached
`cross-encoder/ms-marco-MiniLM-L-6-v2`, revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`. It loads only local safetensors,
disables remote model code, and scores the same top 60 BM25 blocks with the
original query. Scoring truncates only the passage at a 512-token pair limit;
the selected source text remains intact. Scores are uncalibrated relevance
logits, not probabilities. A missing candidate set remains a selection failure.

Both default windows and method chunks were swept at
500/1,000/2,000/4,000 rendered context budgets. All 192 observations respect their
budget. This is a source-span coverage diagnostic, with zero generative calls.

| Policy / method | Mean required-span coverage at 500 / 1K / 2K / 4K |
| --- | --- |
| Windows / BM25 | 0.0 / 0.0 / 41.7 / 81.9% |
| Windows / cross-encoder | 0.0 / 0.0 / 55.6 / 69.4% |
| Members / BM25 | 33.3 / 48.6 / 66.7 / 79.2% |
| Members / cross-encoder | 28.5 / 30.6 / 56.9 / 77.8% |

Reranking added a median **5.35 s** with windows and **5.23 s** with method chunks,
versus about 6–8 ms to obtain BM25 candidates. Model/library loading took 14.29 s.
The CPU process used six Torch threads; post-query RSS was about 837 MiB and peak
working set about 866 MiB, including Python/libraries and prior operations.
The benchmark ran after the live sweep and tests completed, without another
CPU-heavy benchmark running. Timing is still one-machine observational evidence.

The cross-encoder does not earn a production dependency. It loses coverage at
every measured member-chunk budget, and its one window-chunk improvement is not
an answer-quality result. No live calls were spent promoting this challenger.
Its offline harness is retained as a reproducible legitimate-model baseline;
no cross-encoder flag or dependency was added to the default runtime.

### Decision and next cycle

**Verdict: PIVOT REQUIRED.** Keep strict scan failure handling and the improved
answer-model/evaluation controls. Discard silent source omissions, invalid-byte
deletion, and default promotion of this cross-encoder. Default BM25 remains the
safe operational baseline; method chunks, hybrid and graph expansion remain
experimental. "Safe" here means preserving declared contracts and reporting
failure, not proof that a nonempty selection contains every needed fact.

Final full suite: **392 passed, 1 skipped**; **12/12 mutations** killed.
No code ranking change was made. The next highest-value work is a prospective
new real-repository workload and multiple-budget LIVE comparisons, with a
reasoning-capable answer control given an explicit adequate deadline. The
60-second high-reasoning timeouts do not prove those answers impossible or that
the endpoint is permanently unusable. Freeze configurations before requesting
answers and retain every attempt. Exact provider-token budgeting and cheap
explicit source-path constraints are additional hypotheses; neither is repaired
or promoted by this cycle. Repeatedly tuning the existing 12 questions would not
establish generalization.

Evidence: `cycle9-scan-before.xml.gz`, `cycle9-deterministic-paired.json.gz`,
`cycle9-scale.json`, `cycle9-tests-final.xml`, `cycle9-mutations.json`,
`cycle9-canary-none.json.gz`, `cycle9-canary-high.json.gz`,
`cycle9-repository-live.json.gz`, `cycle9-repository-summary.json`,
`cycle9-rerank.json.gz`, `cycle9-rerank-summary.json`, and `cycle9-summary.json`.
Compressed LIVE archives retain exact contexts, original responses, task oracles,
generation settings and provenance; no request credentials are included.
After staging, all eight credential tests passed, including working-tree and Git
object-store scans. All six compressed cycle reports were additionally decoded
and scanned with the same credential patterns, with no matches. All 39 measured
production hashes still match the final source.

## Cycle 10 — prospective 300K-source trials, documentation repair and an integrity-cache hypothesis

### What was frozen and tested

The starting champion was `426ecc4`. All 39 production Python files remain
byte-identical to the measured baseline. This cycle changes evaluation tooling,
tests and documentation, and adds isolated compiler experiments; it does not
promote a new production selector or artifact format.

Twelve developer-authored Click 8.5.0 questions were executed locally and frozen
before retrieving evidence or requesting answers. The frozen task file SHA-256
is `b93d1989f986dcc94934e478a4c9fe73f877fcbddf9143a4f7906b7a6b9534d4`.
Questions exercise environment precedence, empty/invalid environment values,
boolean and payload flags, tuple batching, callback ordering/conversion,
normalized choices, invocation/forwarding, nested defaults, resilient parsing
and shared parameter destinations. All oracles run without network and isolate
their own environment variables. They are permanent regression data now, not
independent sealed validation or previously unseen data for future tuning.

The public Click 8.5.0 source distribution is pinned by URL and SHA-256
`ba0d2089de75ea0310e2dde03160e6ca10009947fb95a182f9b54021bb272e34`.
All 17 runtime Python files match the installed package used by the executable
oracle. The accepted collection includes 105 real code, documentation and test
files: **298,931 source-token estimates / 299,984 rendered available-token
estimates per question**. These are per-request sizes, not cumulative totals.
Successful full-source API responses report approximately 305,683 input tokens.

The frozen plan compares default BM25 chunks, optional Python method chunks and
hybrid retrieval with those method chunks. Each uses 512/2,048/8,192 estimated
context budgets. Original source, source headers, question and system prompt are
retained. The 132 observations deduplicate to 120 exact answer request payloads.
Budgets include rendered evidence headers in this harness; actual provider token
counts vary and are plotted separately. Span annotations are conservative
diagnostics, not proven necessary/sufficient evidence or exact MSC.

### LIVE results and interrupted control

Both answer configurations use `deepseek-ai/deepseek-v4-flash-0731`, temperature
zero, with **zero generative selection calls**. The first configuration used
high reasoning, a 4,096 output cap and 180-second socket-operation timeout.
After earlier successful answers, HTTP 529 and four consecutive timeouts exposed
a missing circuit breaker. The verified benchmark process was stopped. One
in-flight answer completed before termination; one remaining request has an
explicit unknown outcome and is never silently resubmitted.

That partial run contains **26 started unique requests: 20 completed answers,
one HTTP 529, four timeouts and one unknown outcome**. It leaves 94 unique
requests unattempted. The raw report has 26 LIVE, 3 exact-prompt REPLAY and 103
PENDING observations. Do not treat its mostly two-question comparison as a
complete quality benchmark. Both full-source controls completed correctly; for
the empty-environment question, 512/2,048 selections answered incorrectly while
the larger selections and full source answered correctly. The smaller evidence
included conversion-error distractors instead of the empty-environment rule.

A follow-up changes only target answer settings to reasoning `none`, output
cap 2,048 and socket timeout 90 seconds. Its input selections, tasks and order
are inherited unchanged from the frozen plan. Choosing this setting after the
parent's service failures is disclosed; it was not preregistered. Initial small
and full controls completed correctly, then the complete 120-request sweep ran.
There were **117 completed unique answers, two HTTP 529 responses and one
timeout**. The 132 observations include 12 exact-prompt replays.

| Method | 512 budget | 2,048 budget | 8,192 budget |
| --- | ---: | ---: | ---: |
| Default BM25 | 4/12 | 4/12 | 4/12 |
| BM25 method chunks | 4/12 | 2/12 | 2/12 |
| Hybrid method chunks | 3/12 | 3/12 | 4/11 completed; 1 error |

Full-source control: **4/11 completed; 1 error**. No-context control:
**1/11 completed; 1 error**. These are reference conditions, not matched-budget
retrieval competitors. Scores require the whole requested JSON object to match
the executable oracle. There were no JSON parse errors or output-cap hits, but
two questions had wrong top-level output keys in every arm. Those protocol
failures are disclosed and remain failures in the unchanged primary score.

On completed same-budget pairs, method chunks had **0 wins / 0 losses** at 512
and **0 wins / 2 losses** at both larger budgets. Hybrid had **0 wins / 1 loss**
at each smaller budget and **1 win / 1 loss** at the largest. No promotion follows.
Correctness also changed non-monotonically with budget: a source-precedence
answer was correct at 512 and wrong at larger BM25 budgets. Full source still
failed conversion and flag cases, so answer-model behavior remains a bottleneck.

The plotted frontier uses the **same 11 completed tasks across every retrieval
method and budget**. The excluded task and all planned/error counts remain in
the report. Its nondominated points are sample observations, not an optimum or
generalization claim. Small estimated-token differences can change that frontier
without creating a meaningful method advantage. This run has one target model
configuration and a small curated workload; stronger modern retrieval and
independent external tasks remain outstanding.

The follow-up reports 3,737,197 input and 4,758 output tokens across its 117
completed unique requests. Replays are not counted as new API usage. Failed or
unknown requests may have unreported usage. Recorded cache usage is zero in
completed follow-up responses. BM25 answering medians were roughly 9.4–11.0 s;
full-source median was 24.7 s. Provider load/caching and two concurrent requests
make these observational timings. No verified billing rate or dollar savings is
asserted. Across both configurations, **146 unique answer requests were started**.

### Evaluation safeguards repaired

The runner now freezes request/context hashes, validates every request before
dispatch, deduplicates identical prompts, preserves a request ledger and refuses
to silently reissue an unknown in-flight outcome. Read-only report generation
does not request answers. Four consecutive transport failures pause after the
current bounded batch completes; explicit resume is required and past errors
are not retried. Synthetic regression tests attack pause/resume, cache recovery,
tampered contexts, exact payload identity, duplicate billing and mixed budgets.

A second gap appeared when rebuilding the partial report: an execution-level
source stamp could be overwritten with the report generator's current revision.
New answers now carry their own execution-source hashes, with byte-exact source
snapshots archived separately; replay preserves those original stamps. All 120
follow-up attempts have them. The older high-reasoning requests have **no
per-request execution stamp**. Their frozen selection provenance and exact
payload/context hashes remain available, but later reporting snapshots are not
misrepresented as original execution snapshots. This limitation is preserved in
the partial archive.

Reports regrade raw answers against the frozen oracle, reject missing/duplicated
observations or edited favorable grades, keep undefined values as N/A, disclose
wrong output keys and use a common completed cohort for plotted comparisons.

### Compiler costs and challengers

LOCAL compilation/update profiles use the same real source in private copies.
For default BM25, median initial compilation across three trials was **1.89 s**,
artifact size **7,282,688 bytes**, and per-trial warm query medians ranged
**8.9–18.3 ms**. No-change update medians were about **36.9 ms**. Median updates
were **1.46 s** for one edited file, **1.50 s** for two files (rounded-up 1%), and
**2.02 s** for eleven files (rounded-up 10%). These append-comment edits are not
semantic refactors. Memory is cumulative process memory, not isolated per-arm
RAM. Background LIVE requests and uncontrolled filesystem caches limit timing
claims; source scanning and integrity remain repository-wide work.

The first semantic compilation took **71.75 s**. Subsequent 3.53 s and 2.67 s
builds reused the process's encoder cache; reporting their median as cold
compilation would be misleading. Semantic warm query medians ranged 41.8–75.4 ms.
The initial frozen-plan semantic compilation independently took 60.40 s. No
quality advantage justifies making this encoder mandatory.

A profiled one-file update spent about 2.6 of 3.8 instrumented seconds sealing
integrity. Profiling perturbs timings. Three v4-compatible digest batching
challengers reproduced all checked roots but yielded only roughly 23–32% lower
digest time on these artifacts. They were not promoted: this is a microbenchmark
and adds no incremental complexity improvement.

An isolated per-file digest prototype is more promising:

| Edit | Current v4 seal median | Known-dirty-file leaf seal median |
| --- | ---: | ---: |
| Small file | 598.2 ms | 21.3 ms |
| Large core file | 668.9 ms | 69.7 ms |
| Eleven files | 669.2 ms | 105.2 ms |

Every prototype result matched a fresh full recomputation of its experimental
digest. This is roughly **28× / 9.6× / 6.4× for the seal stage**, not whole-update
speed. The prototype uses a transient cache and known dirty paths; it is not
format-4 compatible and has no durable migration or general invalidation system.
A deliberate omitted-invalidation attack leaves a changed block invisible to
the stale cache while full recomputation detects it. Therefore a cached root
cannot replace a full verifier. No production format change was made.

The prototype's first benchmark also leaked SQLite handles during temporary
cleanup on Windows. Explicit closing repaired it; a permanent test checks closure
before cleanup. Automatic approval review rejected manual deletion of the failed
run's leftover temporary directory with only “blocked by policy.” It remains at
`C:\Users\vardh\AppData\Local\Temp\npk-leaf-hypothesis-usl3j82r`.

### False claims still present in active documentation

Six active architecture/math documents still asserted old perfect quality,
economic savings, a graph-default promotion and an exact Pareto knee despite
the README's retraction. They are replaced, not kept under a compatibility
banner. The authoritative independent audit files remain unchanged.

The purported repaired math also claimed expanded recall was bounded by direct
seed recall and assumed arbitrary content-only scores followed lexical overlap.
Both are false. A seed can reach a required non-seed vertex; an arbitrary scoring
function need not reward shared tokens. The replacements define their assumptions,
prove empty-seed reachability and finite-search facts, and distinguish graph
reachability from budgeted assembly and answer success. No invented complexity
classification, failure probability or optimality claim is retained.

### Decision and next highest-value work

**Verdict: PIVOT REQUIRED.** Keep the portable compiler/runtime, BM25 baseline,
new prospective fixtures, resilient evaluation runner and corrected documentation.
Discard default promotion of hybrid/method chunks, invalid historical claims,
unbounded dispatch after repeated errors and the idea that a cached digest is a full verifier.
The promising narrower research direction is incremental integrity sealing:
design complete invalidation and full independent verification, then compare
whole updates, failure recovery and memory before any format migration.

For quality, investigate retrieval polluted by output-format terms and explicit
source scope, using preserved failures as development data and new external
questions for validation. A separate observed limitation is that the shared
query tokenizer lowercases identifiers before its purported CamelCase split;
`RetryPolicy` currently yields only `retrypolicy`. No fix or quality claim for
that hypothesis is included in this cycle. Stronger answer controls and target
tokenizer budgeting remain necessary; the interrupted high-reasoning run does
not prove that configuration generally unusable.

Final full suite: **412 passed, 1 skipped**. All **12/12 contract mutations**
were killed. Production source hashes still match the frozen champion. Evidence
is in `cycle10-click-tasks.json`, the complete `cycle10-click-live.json.gz`,
partial `cycle10-high-partial.json.gz`, their summaries/curves, `cycle10-local.json`,
`cycle10-integrity-challengers.json`, `cycle10-integrity-leaves.json`, the update
profile, environment snapshot, test XML and mutation report. Compressed archives
preserve exact contexts, raw responses, ledgers and available source stamps.
After staging, all eight credential tests passed, including tracked-file and
Git-object scans. Both new compressed archives were decoded and scanned with
the same credential patterns, with no matches. No credential was printed or
replacement credential created.

## Cycle 11 — Durable integrity reuse and consistent query snapshots (2026-09-06)

### Discovered and attacked

The previous transient leaf-cache prototype did not justify a production format
change by itself. This cycle implements durable invalidation as a candidate:
version 5 stores file digests and a dirty-file journal, with eighteen persistent
SQL triggers over the six file-local tables. The root still covers global
manifest/dependency/FTS data and the actual cache. Full verification independently
recomputes every file digest; it never substitutes cached values for source reads.

New contracts cover changed-file-only hashing, full verification, moves between
owners, metadata, symbols, assignments, embeddings, deletion, rename, graph
policy changes, and indexing unchanged files when previously missing model
weights become available. Corrupted caches, missing tracking triggers and
unsealed external changes cannot enter an update as a silently accepted base.
Unknown tables/views/triggers are rejected. An exception injected after cache
refresh must roll back data, cache, journal and root together.

The before report's fifteen failures are missing-feature contract failures,
not fifteen independently reproduced old product bugs. Three semantic tests
initially failed because they deliberately edited artifacts without resealing.
The new preflight correctly rejected those fixtures earlier. They now arrange
self-consistent fixtures to reach the intended guards: malformed vector payloads
are explicitly resealed, and the hash-collision case injects a controlled hash
collision without bypassing artifact integrity. Exact-text vector reuse remains
necessary. All adapted checks pass.

A separate concurrency counterexample reproduced an actual product failure:
a query retrieved old candidate IDs, an update committed replacement blocks,
and the query returned failed seeds instead of the old available evidence.
Readonly contexts now begin a read transaction. Updates begin their write
transaction before validating the base. Both old behaviors failed the new
snapshot tests; both corrected behaviors pass. Long readers can still delay
writers, and a busy timeout remains possible. Applications must serialize
writes, including replacement compilation; no power-loss recovery claim follows.

### Measurements and decision

The complete paired real-source benchmark freezes both source
implementations, runs arms in separate processes in randomized order per trial,
compares identical edits, and checks selected text hashes/spans/token estimates
against both the other implementation and independently rebuilt artifacts.
It uses the existing 105-file Click collection and twelve questions at three
budgets. These are LOCAL equivalence and cost checks, not new LIVE accuracy.

The first candidate ran three deterministic trials per arm/configuration and
one local-embedding trial per arm. Initial and updated selections matched the
committed version-4 champion in **1,764 paired query/budget cases**. Each
updated artifact also matched independent fresh compilation. Default BM25
whole-operation median costs:

| Operation | v4 | First v5 candidate |
| --- | ---: | ---: |
| Small-file update | 381.5 ms | 68.4 ms |
| Large-file update | 582.1 ms | 188.3 ms |
| Two files, rounded-up 1% | 460.0 ms | 106.6 ms |
| Eleven files, rounded-up 10% | 592.0 ms | 249.0 ms |
| Delete | 683.6 ms | 106.5 ms |
| Rename | 394.3 ms | 70.7 ms |
| Full verification | 400.3 ms | 314.0 ms |
| No-change update | 24.5 ms | 17.8 ms |
| Median of per-trial warm-query medians | 7.0 ms | 8.3 ms |
| Artifact bytes | 7,282,688 | 7,516,160 |

The small-file paired speedups were 6.13×, 5.58× and 6.25×, while eleven-file
speedups were 2.02×, 2.38× and 2.48×. They are not the prototype's 28× seal-only
result. A one-file edit hashes one file and reuses 104 leaves; deleting a file
hashes no remaining file and reuses 104. Full verification rereads all survivors.
Source scanning and global FTS hashing remain corpus-wide costs.

The local-embedding rename had a retained adverse result: **394.9 → 926.2 ms**.
Of the candidate time, 863.7 ms was source scanning; encoder rows requested were
zero in both arms. A deliberately selected follow-up retained five timings per
arm. Median rename was 406.8 → 78.3 ms, with first-scan spikes of 422.6/434.6 ms
in both arms. This does not erase the original result or identify the external
cause. Filesystem/cache tails are real deployment constraints. The optional
semantic workers ended at roughly 771/749 MiB RSS, versus roughly 34–37 MiB for
deterministic workers; these are whole-worker measurements including fresh
builds, not isolated query RAM. First semantic compilation was 86.4/38.3 seconds
in separate processes, with uncontrolled OS caches and only one trial. Do not
attribute that difference to the digest change or call warm rebuilds cold starts.

### A second bottleneck and a retained challenger

The scale sweep exposed about 135–150 ms of extra initial-build cost at every
size. Trigger DDL ran before any write transaction, causing separate commits.
The original schema setup also committed each statement. Three randomized,
three-trial challengers compared separate DDL, a transaction for tracking only,
and a transaction enclosing schema/tracking/source writes:

| Available tokens | Separate DDL | Tracking transaction | Whole build transaction |
| --- | ---: | ---: | ---: |
| 2,186 | 316.0 ms | 176.4 ms | 35.4 ms |
| 52,395 | 461.8 ms | 318.2 ms | 174.3 ms |
| 298,845 | 1,069.3 ms | 959.1 ms | 797.0 ms |

All use actual Click files, ordered by file size for these source subsets.
All checked selections and verification results matched. The final build starts
its transaction inside `executescript`, before CREATE statements. A SQL trace
regression failed before this correction and passes afterward. Batching only
tracking DDL was discarded. The roughly 9× tiny-build gain is against the first
v5 candidate, not a universal improvement over the committed v4 product.

The final build's repeated default Click comparison retained exact selections
in another **252 paired cases**: small-file update 329.9 → 68.4 ms and eleven-file
update 520.2 → 246.6 ms. Initial compile was 1,262.3 → 1,204.0 ms and warm query
median 6.66 → 6.77 ms. This follow-up is one trial, reported separately from the
first candidate's three trials. Across both runs there were **2,016 paired
selection comparisons** and **3,456 incremental-versus-fresh comparisons**.
No generative answer requests were made; identical selections are not new LIVE
answer-quality measurements.

Final mixed-public-library scale results, one compile per arm/scale and repeated
source-name queries:

| Actual available tokens | Compile v4 → final v5 | One-file update v4 → final v5 | Warm query v4 → final v5 |
| --- | ---: | ---: | ---: |
| 2,002 | 158.5 → 25.9 ms | 15.2 → 17.8 ms | 0.68 → 0.90 ms |
| 31,063 | 195.0 → 89.8 ms | 37.8 → 20.6 ms | 0.67 → 0.68 ms |
| 51,307 | 230.4 → 118.1 ms | 64.1 → 25.7 ms | 0.70 → 1.10 ms |
| 94,582 | 322.0 → 217.4 ms | 98.1 → 34.2 ms | 0.64 → 0.81 ms |
| 236,175 | 704.2 → 685.4 ms | 224.0 → 60.0 ms | 0.70 → 0.99 ms |

Tiny updates can be slower; warm query costs depend on workload. The source-name
queries in this sweep are much easier than the long Click behavior questions;
their sub-millisecond medians cannot be generalized to arbitrary 100K queries.
The requested 25K/100K/250K scale labels are not the actual available-token counts.
The separate Click collection supplies about 300K available tokens per question.
No dollar or query break-even claim follows. Cache-state variation is visible
in raw trials and compilation amortization is only local wall time.

**Decision: promote durable integrity reuse and whole-build transaction batching
as infrastructure; retain BM25 as the default selector. Verdict: PIVOT REQUIRED.**
Discard cache-only verification, separate DDL commits, the partial batching
challenger, and any interpretation of these results as better answers. Version 5
requires recompiling older artifacts, including v4. It does not silently migrate
or relabel their digests. The authoritative audit files remain unchanged.

Initial full suite: **432 passed, 1 skipped**. Final full suite: **433 passed,
1 skipped**. All **16/16 contract mutations** were killed by assertions, including
the previous three critical mutants and the new dirty-journal, cached-verifier,
reader-snapshot and build-transaction mutants. Raw failures, adapted fixture
checks and final passes are retained. ADR 0005 states assumptions and limitations.
After staging, all eight credential checks passed, including tracked text and
all Git blob objects. Both new gzip archives and their 81 embedded byte-exact
source blobs were decoded and scanned with the credential patterns: zero
matches. No key was printed, replaced or used for a live call in this cycle.
`cycle11-summary.json` binds final source hashes, results and archives. Its source
snapshot archive distinguishes the first candidate, final candidate, v4
champion and transaction challengers. The final compiler differs from the first
candidate only in its initial build function; its AST matches the measured
whole-transaction challenger. Final measured source also matches the mutation
run and scale profile. The unrelated trace log is left outside this commit.

### Further hypotheses found during this cycle

These observations are not completed repairs or measured improvements:

- Installing dirty-file triggers only after an unpublished initial bulk build
  may remove remaining per-row tracking work. Whole-build transaction batching
  has been measured and adopted; delayed trigger installation has not.
- Source scanning protects known credential filenames but does not reject
  credential-shaped strings in ordinary source. The broad secret-free artifact
  claim is already withdrawn. Test fail-closed source screening with synthetic
  fixtures, without silently redacting or dropping evidence.
- The scanner does not produce an atomic snapshot of files being edited during
  its walk. URI-special characters in artifact paths also deserve a targeted
  portability test; neither issue has been repaired in this candidate.
- Query tokenization still lowercases before CamelCase splitting. Stronger seed
  retrieval and target-tokenizer budget enforcement remain higher-value quality
  hypotheses than further graph elaboration.

## Cycle 12 — literal evidence, source boundaries and seed challengers

### Discoveries and repairs

Starting champion: `9f9c6bf`. Compiler rules are now 5.2; artifact format remains
5. Source screening rejects recognized credential shapes in eligible text and
paths, without echoing values, redacting source, or publishing partial builds.
All secret fixtures are constructed synthetic strings. NUL at either the start
or beyond the old 8K scan boundary now fails explicitly. Resolved source files
must remain inside the requested root, and before/after metadata checks reject
ordinary concurrent edits, including same-size changes. This is not an atomic
repository snapshot or proof that arbitrary source contains no secrets.

Literal `#` and percent characters in pack names could previously select a
plausible sibling database. Encoded SQLite URIs fix this across compilation,
query, update and verification. Missing-pack updates now fail without creating
an empty database. The initial boundary attack reproduced 16 failures, with two
passing cases and one host-dependent symlink skip.

Independent source reconstruction exposed two further problems. `splitlines()`
rewrote Unicode separators within source strings, and recapping could omit a
terminal blank line while claiming it in the span. Eight targeted tests failed
before repair. Physical CR/LF lines are now distinct from Unicode data, and
reported spans follow actual slices. On the pinned Click default build, invalid
literal spans fell from **3 to 0**; neither build omitted nonblank source lines.
Recapping changes some chunk boundaries (1,330 → 1,327 blocks), so identical
cross-version selections are not claimed. The first old/new query sweep differs
on three of its 36 task/budget observations. A self-consistent hash also used to
certify impossible source spans; full verification now checks internal line
geometry separately. External source correspondence still requires the source.

The initial identifier harness also used the wrong required-source namespace
for older controls. Its corrected scores fixed that namespace but did not fix
the source-span defect. **Both initial reports are withdrawn for promotion**,
with raw contexts and exact execution sources retained. The replacement LOCAL
run reconstructs every block before retrieval and all **1,344 selected contexts**
independently afterward. Its source mappings and reconstruction checks pass.
See `cycle12-initial-evidence-withdrawal.json` and ADR 0006.

### LOCAL retrieval comparison

The same pinned public Click 8.5.0 collection supplies 105 files and 298,931
estimated corpus tokens. Eight new executable behavior families were frozen as
identifier/prose pairs before retrieval; 12 previously inspected questions are
controls. These are developer-authored tasks, not independently sealed tests.
Two chunk policies, eight seed methods, and budgets 512/2,048/8,192 produce the
1,344 observations. Target questions survive unchanged; generative calls: zero.

Full required-span retention on the 16 new window-policy questions:

| Seed method | 512 | 2,048 | 8,192 |
| --- | ---: | ---: | ---: |
| BM25 | 3/16 | 8/16 | 14/16 |
| BM25 with explicit `src/click/` scope | 3/16 | 11/16 | 16/16 |
| CamelCase expansion | 3/16 | 9/16 | 14/16 |
| Empty-seed expansion | 3/16 | 8/16 | 14/16 |
| Lexical fusion | 3/16 | 8/16 | 14/16 |
| Symbol-priority seeds | 1/16 | 8/16 | 14/16 |
| Local hybrid | 2/16 | 7/16 | 9/16 |
| Local cross-encoder | 1/16 | 4/16 | 10/16 |

These are **EMPIRICAL coverage diagnostics**, not accuracy or MSC. Identifier
and prose pairs are correlated. Required whole spans are conservative and can
penalize method chunks; complete source is not proof of sufficient reasoning.
The source-scope method receives explicit metadata also available to a competent
baseline. This is not a novel NeuralPack algorithm.

Real encoders were used locally: `sentence-transformers/all-MiniLM-L6-v2`, pinned
revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, and
`cross-encoder/ms-marco-MiniLM-L-6-v2`, pinned revision
`233902d25c440f23af6f7d6e94d2946bac0bee0a`. Windows/members semantic builds took
22.8/35.1 seconds and stored 1,327/1,696 vectors. Their artifacts used
10,059,776/11,177,984 bytes. BM25 selection medians were about 7 ms, scoped BM25
11–12 ms, hybrid 29–46 ms, and cross-encoding about 2,565 ms plus assembly.
Reranking was computed once per query and reused across swept budgets; its cost
is added back for each stand-alone query estimate in the LIVE comparison.

### Frozen LIVE answer validation

After source reconstruction and executable-oracle preflight passed, freeze the
prose member of each new family, four methods and three budgets, plus full and
no-context controls. Plan hash:
`cc7a0331673d4088366d03d57531911938634d10c4d3a5de2652d733b5274bf6`.
The 112 observations require **106 distinct requests**; six exact-prompt replays
are not independent answer trials. DeepSeek V4 Flash 0731 uses reasoning `none`,
temperature zero and a 2,048-token output cap. No live calls debugged plumbing.
All selections were frozen before dispatch and were unchanged during execution.

Every task has 298,931 corpus tokens and **298,846 available compiled tokens**.
Actual provider input usage is recorded separately from chars/4 budget estimates.
All 106 attempts completed in the ledger: **94 answers, 12 HTTP 529 errors**.
No failed request was retried. Every attempt has exact executor source hashes.
Reported unique usage totals 2,136,895 input and 4,058 output tokens across the
94 responses. Unknown endpoint prices remain N/A; no dollar-saving claim follows.

| Method | 512 correct/completed | 2,048 correct/completed | 8,192 correct/completed |
| --- | ---: | ---: | ---: |
| BM25 windows | 3/7 | 3/8 | 3/8 |
| Explicit source-scope BM25 | 3/6 | 3/8 | 3/8 |
| Hybrid windows | 4/8 | 4/8 | 2/6 |
| Cross-encoder windows | 2/7 | 4/7 | 2/6 |

Full source scored 2/6 completed answers; no context scored 1/6. They are
reference conditions, not matched-budget retrieval arms. At 2,048 tokens, both
hybrid and the cross-encoder have one paired win and no paired loss against
BM25. Source scoping has no paired answer wins at any budget despite higher
coverage. The hybrid/reranker win concerns literal formatting of an explicit
parameter hint. At the larger budget that advantage disappears. More retrieved
text is not monotonically better answer quality.

The common completed cohort contains only **four tasks**. Curves and their
observed frontier use that same cohort, with all planned counts and missing
answers disclosed in `cycle12-answers.md`. Those curves are **EMPIRICAL**, not
evidence of optimality or generalization. This trial reveals wrong behavior
answers, including ignored open integer bounds and incorrect option-suggestion
formatting, even when substantial source is supplied. No retrieval method solves
all eight cases. Coverage cannot substitute for actual answer testing. Remote
LLM preprocessing was not tested, so no comparative economics claim is made
against that architecture. The default runtime remains zero-generative-LLM.

### Cost attacks and retained improvement

Three paired default Click trials before source-screen optimization show the
cost of the new boundary checks: compile 1,207.8 → 1,253.2 ms, small-file update
74.5 → 120.4 ms, two-file update 111.0 → 159.8 ms, eleven-file update
222.2 → 276.1 ms, unchanged scan 20.3 → 71.5 ms, and warm query 8.17 → 7.79 ms.
These are medians, not speed guarantees; source scanning remains proportional
to the available collection.

Profiling identified the OpenAI pattern's word-boundary regex as a major cost.
Three challengers were compared on the pinned corpus, with 340 generated
differential examples. Screening medians: unfiltered regexes **24.61 ms**,
only the mandatory OpenAI-literal precheck **4.35 ms**, and all-pattern literal
prechecks **6.63 ms**. Keep only the simpler OpenAI precheck. Production boundary
tests compare 540 generated examples to the unfiltered current regex policy.
Forty alternating full scans returned identical source data and metadata;
median scan time fell **126.74 → 93.50 ms**. This is a narrow screening/scan
improvement, not a 5.7× compiler or retrieval claim.

The final paired Click repeat ran under substantial external machine load;
a contemporaneous sample had under 1 GiB free memory. Report it separately:
champion/final median compile 2,589.4/2,476.8 ms, small-file update 124.2/177.3 ms,
two-file update 165.3/228.8 ms, eleven-file update 417.4/406.7 ms, and warm query
13.89/13.64 ms. It does not establish an end-to-end speedup. LIVE answer IO also
ran concurrently, making answer latency observational. Both paired runs retain
all cross-version differences; together they require and pass **2,592
incremental-versus-fresh selection comparisons**.

The earlier scale sweep used the repaired implementation before the literal
precheck, with one compile per arm/scale. Actual available tokens were
2,002/31,063/51,307/94,582/236,175. Candidate compile times were
26.9/91.9/139.7/239.2/619.2 ms; one-file updates were
16.7/26.8/35.1/47.4/99.6 ms. These easy source-name queries had sub-millisecond
warm medians; they do not represent long behavior-question latency. Requested
scale labels are not actual context counts. All raw memory, disk, update and
timing results are retained. The final implementation differs from the measured
precheck-free one only in `check_source`; exact source snapshots distinguish them.

### Decision, checks and next hypotheses

**Verdict: PIVOT REQUIRED.** Promote the source-boundary, filename and literal
provenance repairs, stronger internal verification, and measured narrow screen
optimization. Retain BM25 as default. Keep hybrid optional and graph expansion
experimental. Do not promote source scoping, CamelCase expansion, fusion,
symbol-priority retrieval, or cross-encoding as a general quality improvement.
Discard the all-pattern prefilter and the interpretation of coverage as accuracy.
The weak hybrid signal is a follow-up hypothesis, not a win on modern retrieval
established by an independent evaluation.

Final optimized build: **478 tests passed, two skipped**. All **22/22 mutants**
are killed by assertions, including the three original critical mutants.
The genuine host-symlink test is skipped where Windows disallows creating one;
the independent mocked outside-root rejection test passes. Raw pre-repair
failures and the corrected test assumption about noninteger spans are retained.
Twelve gzip archives and 350 embedded source blobs were decoded and scanned with
the current credential patterns: zero matches. Source snapshots bind the original
champion, repaired precheck-free code, final code, harnesses and tests. All LIVE
contexts, responses, execution sources and ledger outcomes are archived. The
authoritative audits remain unchanged; unrelated trace logs remain uncommitted.

Highest-value follow-ups:

- Compare narrow, source-derived diagnostic controls with full context to
  separate missing retrieval evidence from a target model ignoring or misusing
  supplied evidence. Do not place executable answers in retrieval inputs.
- Test the small hybrid gain on another frozen package/workload and another
  answer model before promotion; repeated budgets on one case are not new wins.
- Investigate explicit source-role/version metadata as a user-controlled scope,
  benchmarked against equally scoped BM25. Avoid silently excluding relevant docs.
- Attack verifier type assumptions and writable-connection setup failure paths;
  these are open hypotheses, not completed fixes.
- Improve tokenizer-aware budget accounting, scanner read-error reporting and
  richer behavior tasks before adding more graph machinery. Current source
  screening and internal checks do not prove arbitrary input is safe or sufficient.

## Cycle 13 — storage contracts, source labels and external evidence (2026-09-06)

### Discoveries and retained repairs

**EMPIRICAL:** resealed binary block text crashed verification; binary manifest
values could be certified and accepted by queries or updates. Two writable
connection initialization faults leaked the connection. Full artifact acceptance
now validates stored types against the trusted compiler schema. Query/update
share a manifest reader that rejects non-text metadata. Setup failures close
their connection, including cancellation, and expected storage errors become
`PackError`. Format 5/compiler 5.2 source layout and normal selections are unchanged.
The new checks do not establish publisher authenticity or every semantic
constraint on arbitrary artifacts; cached updates still assume an accepted base.

The answer grader had another real defect: duplicate JSON keys silently kept the
last value, allowing contradictory answers to pass. It now rejects duplicates
at every nesting level, escaped duplicate keys, and NaN/Infinity constants.
Six pre-fix failures and a killed grader mutant are retained. Regrading **339
completed archived observations** from cycles 6, 9, 10 and 12 changed no scores.
These include correlated replays, not 339 independent trials.

### Frozen diagnostic and result

Use the same pinned Click 8.5.0 collection and eight known prose questions:
105 files, **298,931 corpus tokens and 298,846 available compiled tokens per
question**. This is a diagnostic follow-up, not held-out validation. Budgets are
2,048 and 8,192 estimated context tokens. The independent preflight reconstructs
all source spans and rendered prompts. Its initial rounding assumption was
wrong (ceiling instead of the declared floor(chars/4)); it was corrected before
any live calls. Neither estimate is a target-model tokenizer count.

Three retrieval arms retain ordinary BM25, labeled excerpts with headers charged
to budget, and the exact same selected blocks with labels omitted. Four uncapped
reference arms use required definitions, called definitions, full source and no
source. The called-definition control traces trusted executable tests but stores
only library function identities and literal source, with class context. It has
privileged access and is neither deployable retrieval nor proven sufficient MSC.

Plans were frozen before answers:

- DeepSeek: `0860003ec841b3ea9445f8d3926bb04382348adf996feffcbfcec4f3b7361e1a`.
  Model `deepseek-ai/deepseek-v4-flash-0731`, reasoning `none`, temperature zero.
- Nemotron: `7117b65ef3df537ceb2a48d41346a46f6b76ebc0d88e7ca2c6b2bd32a8faf5ed`.
  Model `nvidia/nemotron-3-super-120b-a12b`, temperature 1, top-p .95,
  `enable_thinking: false`, following its documented configuration.

Both use a 2,048-token output cap and 90-second socket-operation timeout. There
are **160 unique attempts, 138 completed answers and 22 HTTP 529 errors**.
All errors belong to DeepSeek; no failures were retried. One progress message
miscounted 136/24 before the final ledger read and was immediately corrected.
Original and final replay reports, immutable requests, contexts, responses,
ledgers and exact executor sources are archived. Stricter replay grading changed
none of these 138 completed outcomes. Generative optimization calls: **zero**.

| Model / method | 2,048 correct/completed | 8,192 correct/completed |
| --- | ---: | ---: |
| DeepSeek / BM25 | 2/6 | 2/6 |
| DeepSeek / labeled BM25 | 3/7 | 2/6 |
| DeepSeek / same blocks, bare | 3/6 | 3/7 |
| Nemotron / BM25 | 5/8 | 5/8 |
| Nemotron / labeled BM25 | 5/8 | 5/8 |
| Nemotron / same blocks, bare | 3/8 | 3/8 |

DeepSeek has **zero paired label wins or losses** against either comparator,
with five completed pairs at each budget. Nemotron has two label wins against
the bare same-block arm at each budget (open integer clamping and parameter
hint formatting), but **zero wins against ordinary BM25**. Repeated budgets on
the same two cases are not four independent improvements. Headers displace
source; comparing only the weakened same-block arm would give a misleading
promotion result. Neither rendering change nor graph expansion is promoted.

DeepSeek required/called/full/none controls scored 3/4, 3/5, 2/4 and 1/7.
Nemotron scored 3/8, 3/8, 4/8 and 0/8. Some Nemotron failures had malformed JSON
or wrong output keys; no response hit the output cap. The common completed
retrieval cohort has only two DeepSeek tasks and all eight Nemotron tasks.
Curves use those common cohorts and disclose all planned outcomes separately.
No general quality guarantee or model ranking follows from this small study.

Reported unique input/output usage was **1,432,269 / 2,512** tokens for DeepSeek
and **2,683,155 / 3,397** for Nemotron. Within Nemotron, ordinary BM25 used about
2,180 actual input tokens at the 2K budget; full source used about 300,350.
That is an observed token difference, not established dollar savings or a novel
NeuralPack retrieval advantage. Prices are unverified (N/A). Remote generative
preprocessing was not tested. Model runs overlapped with two workers per model;
endpoint load, caching and host activity make answer latency observational.

### A limit of the available collection

**EMPIRICAL:** `NoSuchOption` calls the external `difflib.get_close_matches`,
whose implementation is absent from the Click-only corpus. For the frozen
examples, Python 3.12.10's default cutoff .6 excludes all candidates. Both answer
models nevertheless suggested options in completed source-control answers.
This exposes missing external behavior, not a proof that package source was
sufficient and only the answer model failed.

A permanent fixture retains identical Click source while replacing the external
matcher in a test; the correct answer changes. The new
`research/math/AVAILABLE_CONTEXT_LIMIT.md` gives the **PROVED UNDER ASSUMPTIONS**
indistinguishability result for a deterministic selector/answerer receiving
identical inputs in two environments with different correct answers. It is a
negative result with explicit information assumptions, not a complexity theorem
or a probability claim. The authoritative audits remain unchanged.

### LOCAL cost and acceptance

Three paired trials against champion `3ff2cce` on the same Click collection:

| Operation | Champion median ms | Repaired median ms |
| --- | ---: | ---: |
| Compile | 1,167.47 | 1,164.71 |
| Full verify | 277.31 | 288.05 |
| Unchanged update | 46.35 | 47.28 |
| Small-file update | 93.26 | 100.60 |
| Large-file update | 205.03 | 195.42 |
| Two-file update (~1%) | 134.65 | 140.17 |
| Eleven-file update (~10%) | 257.81 | 243.98 |
| Warm query | 7.24 | 7.37 |

All **1,296 incremental-versus-fresh selections** match exactly; no cross-version
evidence differences occurred. There is no end-to-end speedup claim. Full type
checking adds acceptance work without adding a corpus scan to ordinary queries.
The profile overlapped live answer IO but no other CPU test suite.

The separate one-trial scale sweep has actual available contexts of
2,002/31,063/51,307/94,582/236,175 tokens. Candidate compile times were
28.66/100.05/134.26/270.41/664.88 ms; one-file updates were
17.96/26.80/32.46/45.30/98.73 ms. Full verify took
6.82/29.43/41.84/84.65/250.82 ms. Warm source-name queries were 0.77–0.96 ms;
they are easier than the roughly 7 ms behavior-question queries above. Artifact
sizes grew from 172,032 to 5,337,088 bytes; process peak memory grew from roughly
28 to 40 MB and includes prior scales. Raw data preserves every case and caveat.

All **26 product contract mutants** are assertion-killed, including the three
original critical mutants and four new storage/cleanup mutants. The separate
grader mutant is also assertion-killed. Full tests, decoded archive scans and
tracked/history secret checks are recorded in `cycle13-summary.json`.

### Keep/discard and next cycle

**Verdict: PIVOT REQUIRED.** Keep the artifact and grader repairs. Retain BM25 as
the default. Do not promote source labels based on an ablation that does not
beat the normal baseline, and do not equate full package source with complete
environmental evidence. No new feature changes the runtime's zero-generative
architecture. The two model configurations also caution against drawing broad
retrieval conclusions from one answer model.

Highest-value next hypotheses:

- **CONJECTURE:** explicit external dependency evidence acquisition can repair
  some source-universe failures. Compare every method on the same expanded source
  and estimated/exact budgets; privileged test traces remain diagnostics.
- **CONJECTURE:** source-role/symbol fields and a stronger modern local encoder
  can improve seeds before structural expansion. SQLite already supports weighted
  FTS5 columns; that is a competent baseline, not a novel algorithm.
- Prepare Qwen3-Embedding-0.6B as a challenger to MiniLM, using the documented
  query instruction and pooling. Revision
  `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` was downloaded and its weight hash
  verified for cycle 14. It has not been loaded, benchmarked or integrated.
- Attack manifest semantic constraints and exact schema acceptance, which are
  separate from stored-value types. Improve target-tokenizer budgets and scanner
  read-error accounting. These remain open work, not completed safety claims.

References: [SQLite FTS5](https://www.sqlite.org/fts5.html#the_bm25_function),
[Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), and
[Nemotron configuration](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b).

## Cycle 14 — modern seeds, external source, and semantic metadata checks

**Verdict: PIVOT REQUIRED.** Continue the portable compiler/runtime; no new
retrieval challenger earned promotion. The compiler and default query path still
make zero generative calls and need no API key. Champion before this cycle:
`be28ae5`. The authoritative independent audits are unchanged.

### What was discovered and repaired

Fifteen failing-before regression checks showed that resealing a malformed
artifact could make verification accept false available/file/block counts,
invalid numeric values, unknown mode or flags, a made-up embedding status,
malformed encoder JSON, and false block-token estimates. Unknown mode also entered
query, stats and update without rejection. Full validation now checks known
metadata contracts against actual stored content; common readers reject invalid
policy and numeric values without scanning the corpus on every query.

The first full run found two old integrity-journal tests expecting directly
mutated, semantically invalid data to pass full verification merely because it
was resealed. Their journal and digest assertions remain; acceptance now rejects
the incompatible embeddings and stale file counts. This is a correction to the
old test expectation, not a product rollback.

The first mutation run exposed three stale tripwires: cached verification,
manifest type checking and update manifest checking. Additional validators now
caught the old fixtures even with those protections disabled. The repaired
fixtures change a source value without changing its length and exercise a BLOB
in source-root metadata as well as mode. A new tripwire's `pytest.raises` failure
was classified as a harness error under the assertion-only rule; it now uses an
explicit rejection assertion. Final result: **28 product mutants plus one grader
mutant killed**. Initial failures, survivors and harness error remain archived.

Full acceptance: **546 passed, 2 skipped**. Twelve frozen executable standard-
library counterexamples are now permanent tests. Accepted behavior includes
deterministic, empty and unavailable-encoder states; lexical legacy access stays
separate from full semantic-index acceptance. The repair does not claim complete
schema validation, arbitrary semantic validity, external-source authenticity or
per-query rehashing of accepted artifacts.

### Competing seeds on genuine public source

Added thirty CPython source/doc files at commit
`0cc81280367df838c4b199f8f0378837165071c2` (v3.12.10) to the 105-file Click 8.5.0
collection. All 23 selected library files match the executable local Python
version after newline normalization; seven documentation files and the license
are pinned separately. This is selected external source, not the complete runtime
environment. Each expanded request has **559,647 corpus tokens / 559,738 available
compiled tokens**. Click-only requests have **298,931 / 298,846** respectively.
These are per-request floor(chars/4) estimates; source and compiled joins differ.

Twelve new questions were frozen before retrieval: extended interpolation scope,
fallback/conversion, duplicate options, percent escapes, valueless options,
section defaults, interpolation cycles, dictionary casting, path matching,
relative paths, URL resolution and shell lexing. Eight share `configparser` and
are correlated. Eight previous Click prose questions are controls. None is an
independently sealed holdout.

The LOCAL grid has **1,080 selections**: two corpora × twenty questions × nine
methods × three budgets (512, 2,048, 8,192). Methods: BM25, three ordinary weighted
FTS5 field settings, Qwen plain/prefixed embeddings, two Qwen hybrids, and a real
MiniLM RRF baseline. All rankings use the actual public selector's assembly and
fallback, literal windows, the same candidate policy and estimated caps. Native
BM25 is also checked directly against the injected-ranking harness. Every context
was independently reconstructed from source spans before any LIVE request.

Qwen model: `Qwen/Qwen3-Embedding-0.6B`, revision
`97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, builtin offline Transformers,
safetensors, query instruction, last-nonpadding-token L2 pooling. It runs with
512-token truncation, batch 8, GPU float16 inference, float32 document vectors.
Plain and path/symbol-prefixed encodings are separate challengers. MiniLM remains
revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU, 256 tokens, documented
mean pooling. Hardware, truncation and model size differ: timings are not an
algorithm-only comparison. No model is a generative optimizer.

On 2,183 expanded blocks, Qwen loaded in 5.49 s and indexed plain/prefixed text in
100.08 / 101.56 s. It truncated 334 / 342 blocks and used a peak 2.66 GB of allocated
GPU memory. Each document matrix is 8,941,568 bytes. Median query encoding was
45.03 ms. MiniLM indexed in 45.01 s, with a 3,353,088-byte document matrix and
12.52 ms median query encoding. These sidecars are research outputs, not integrated
artifact features. Qwen weight download and source-index build cost are additional.

Expanded deterministic compilation took 1.87 s and produced 13,197,312 bytes.
The fielded side index added 68.71 ms and 3,829,760 bytes. New-question 2K selection
medians were BM25 9.33 ms, weighted BM25 5.14 ms, Qwen 49.58 ms and weighted hybrid
52.83 ms. Fielded search uses a canonical fresh row order, whereas the production
lexical index joins source metadata to preserve ties across updates. No claim
that weighted search's timing gain is due to scoring weights alone is justified.

Whole required-span coverage remains a diagnostic. For example, new-question
8K full-span counts were BM25 1/12, weighted BM25 3/12, Qwen plain 3/12, Qwen
prefixed 1/12, and weighted hybrid 3/12. Those numbers do not measure answer success.
All **324 out-of-corpus** standard-library selections on Click-only returned text
(177 uncalibrated high-risk, 147 uncalibrated moderate-risk). They are excluded
from promotion cohorts. Nonempty retrieval does not establish that needed source
exists, and these risk labels are not calibrated probabilities.

### LIVE answer validation and attacks on the proposed improvements

Four methods and two budgets were fixed before aggregating LOCAL quality results:
BM25, name-weight-4 FTS5, Qwen prefixed, and their hybrid. Nemotron 3 Super 120B
A12B answered frozen prompts with temperature 1, top-p .95, explicit no-thinking
template flag, a 2,048-output-token cap and a 90 s socket timeout. No queries were
rewritten and no answer hints were added to retrieval. Two workers, one attempt
per unique request, no retries. Identical prompts share one answer across arms.

There were **252 planned observations, 219 unique attempts, 218 completed answers
and one HTTP 503**. All completed answers ended with `stop`. Exact JSON grading
was independently replayed against the frozen executable results. Missing
transport stays unknown. The curves use common completed cohorts of 12 new cases,
8 expanded Click controls and 7 Click-only controls.

| Expanded new questions | 2,048 budget | 8,192 budget |
| --- | ---: | ---: |
| BM25 | 3/12 | 1/12 |
| Weighted BM25 | 2/12 | 1/12 |
| Qwen prefixed | 1/12 | 2/12 |
| Weighted/Qwen hybrid | 1/12 | 0/12 |

No-context scored 1/12. At 8K, Qwen gained the interpolation-scope and valueless-
option cases but lost fallback/conversion against BM25. At 2K it lost two cases
without a paired win. These are single stochastic observations, not a robust
effect estimate. Bigger budgets reduced several methods' success despite larger
required-span coverage. The archived raw answers show real behavior errors, not
just incomplete retrieval or malformed output keys.

Weighted BM25 helped the old Click-only 2K controls (5/8 versus BM25 3/8), but that
advantage disappeared in the expanded corpus (both 2/8). Expanded Click controls
at 8K scored BM25 4/8, weighted 3/8, Qwen and hybrid 5/8. One paired win on eight
previously inspected cases does not justify the new model's cost or a promotion.
Adding external source did not automatically repair the missing-evidence problem.

Actual unique reported usage: **1,050,862 input / 9,475 output tokens**. Dollar
cost is N/A; endpoint prices are unverified. Full-context and remote-LLM-prepass
answer arms were not run this cycle. Full-prompt token estimates are retained per
request as estimates only. There is no end-to-end savings or economic break-even
claim. See `cycle14-answers.json/.md/.png` for all arms, pairs and frontiers.

### Cost of the repaired product

Three paired trials against `be28ae5`, same 105-file source and edits:

| Operation | Before median ms | After median ms |
| --- | ---: | ---: |
| Initial compile | 1,121.89 | 1,127.31 |
| Full verify | 285.55 | 290.28 |
| Unchanged update | 44.32 | 49.89 |
| Small-file update | 89.48 | 87.32 |
| Large-file update | 188.59 | 192.36 |
| Two-file update (~1%) | 126.18 | 126.13 |
| Eleven-file update (~10%) | 233.35 | 229.62 |
| Warm behavior query | 6.96 | 7.01 |

All 1,296 incremental/fresh selections match, with zero cross-version differences.
Full metadata checking adds acceptance work; no general speedup is claimed.
The separate one-trial scale sweep used 2,002/31,063/51,307/94,582/236,175 tokens.
Candidate compile times were 26.20/87.01/120.98/222.70/573.65 ms; full verification
4.22/23.96/39.54/67.06/176.46 ms; single-file updates
16.94/25.81/31.11/39.02/83.92 ms. Warm easy source-name queries took 0.70–0.83 ms;
these are distinct from the 7–10 ms behavior questions. No CPU test suite overlapped
these profiles. Single-machine timing variation and OS caches remain uncontrolled.

### Keep, discard and next hypothesis

Keep metadata validation, stronger tripwires, the pinned external corpus, real
model adapters for research, and reproducible raw evidence. Preserve BM25 as the
default; discard promotion of Qwen, fielded search or hybrid from this evidence.
No graph expansion feature earned promotion either.

**CONJECTURE:** hierarchical retrieval over modules/documents and then passages
can recover useful seeds at lower compute cost than global dense search. The
next comparison should include multiple required modules, misleading namespaces
and source absent from the artifact. Measure module routing and source relevance
separately; do not hide omissions by forcing one module or inflating risk scores.
Repeat promising effects with another answer model and new task families before
promoting. Target-specific token budgets, exact schema contracts and scanner
read-error accounting remain open, rather than implied completed features.

`cycle14-evidence.json.gz` preserves exact source, contexts, plans, responses,
ranking data and preparation/final code snapshots in a content-addressed archive.
`cycle14-vectors.zip` retains numeric embedding/query arrays without pickle.
Archive scans, all failed-before results, final acceptance and source hashes are
bound by `cycle14-summary.json`. No secrets are embedded; the pattern-scan scope
and limits are explicit. The current product remains **PIVOT REQUIRED**.

## Cycle 15 — document routing fails to generalize; reporting contracts repaired

Date: 2026-09-07. Verdict: **PIVOT REQUIRED**. Starting champion `463b38f`.
The `.npk` compiler, default BM25 selector and zero-generative-call runtime are
unchanged. All findings below are **EMPIRICAL** unless explicitly marked otherwise.
The archive separates preparation/execution code from later audit repairs.

### Observe, hypothesize and attack

Cycle 14's newer dense encoder did not earn its cost. We tested whether selecting
files before passages would repair seeds more cheaply. The lexical sidecar uses
weighted document and passage FTS indexes, with document gates of 1/4/16 files,
soft rank fusion, round-robin file balancing, a flat-search escape and passage-parent
routing. No gold facts participate in ranking. The architectural inspiration is
[Dense Hierarchical Retrieval](https://aclanthology.org/2021.findings-emnlp.19/);
our deterministic implementation does not reproduce its learned retriever.

Eight new tasks were frozen before routing: configuration plus shell lexing,
configuration plus URL joining, pathname matching versus filename matching,
configuration plus lexical paths, URL/shell quoting, configuration plus fuzzy
suggestions, configured file filtering, and conversion errors plus shell tokens.
Executable Python 3.12.10 oracles are permanent tests. They combine already-known
libraries; they are correlated developer-authored cases, not independent holdout.
Twelve previous standard-library cases and eight Click cases are explicit controls.

The complete LOCAL grid contains **1,512 selections**: 28 questions, two corpora,
nine methods and three budgets (512/2,048/8,192 estimated passage tokens). The
expanded corpus has **559,738 available tokens per task**; Click-only has 298,846.
These are per-request values, not cumulative totals. Sources are the previously
pinned Click 8.5.0 and CPython 3.12.10 collection. Click-only lacks the new standard
library source and is an out-of-corpus diagnostic; it receives no live calls.
Every selection retains original source spans, question and explicit budget.
All 1,512 contexts were reconstructed independently before live execution.

The four LIVE methods were fixed before aggregating LOCAL outcomes: BM25,
flat weighted passage search, four-document gating and the flat escape method.
Whole required-span coverage stayed zero across all methods on the eight new
cases at both live budgets. Partial source-span recall improved in some arms,
but this did not translate into correct answers. Required spans are conservative
source anchors, not a proof that equivalent evidence elsewhere is insufficient.

### Actual answer tests at matched estimated budgets

Two models each received 234 distinct prompts, representing 252 observations
including shared prompts. Nemotron used temperature 1, top-p .95 and thinking
disabled; DeepSeek used temperature 0 and reasoning effort none. Both used a
2,048-token output cap, 90-second socket timeout and two workers per model.
The model configurations differ; only within-model pairs support comparisons.

| New composed questions | Budget | BM25 correct/completed | Flat fields | Four-document gate | Flat escape |
| --- | ---: | ---: | ---: | ---: | ---: |
| Nemotron | 2,048 | 0/8 | 0/6 | 0/7 | 0/8 |
| Nemotron | 8,192 | 0/8 | 0/8 | 0/8 | 0/8 |
| DeepSeek | 2,048 | 0/6 | 0/7 | 0/8 | 0/8 |
| DeepSeek | 8,192 | 1/8 | 0/6 | 0/8 | 0/7 |

Each cell planned eight questions; missing answers are transport failures, not
incorrect answers. No-source controls scored zero on these new cases. Exact JSON
success requires every requested value. Inspected failures include real semantic
errors around interpolation scope, raw values, comment/quote handling and wildcard
behavior. Better retrieval alone may not explain all failures.

On old standard-library controls at 8,192 tokens, DeepSeek's four-document gate
scored 7/11 completed versus BM25 4/11, with three paired wins, no losses and two
missing pairs. With Nemotron the gate scored 1/12 versus BM25 0/12. On old Click
controls, DeepSeek BM25 scored 4/8 versus gate 3/8; Nemotron BM25 4/8 versus gate
3/8. Positive behavior on familiar cases does not establish general improvement.
The reports retain every arm, task, paired result and common-completed-cohort
frontier; the small common cohorts are visibly labelled.

Nemotron completed **227/234** requests with seven HTTP 503 errors. DeepSeek
completed **217/234** with eleven HTTP 529 errors and six timeouts. No failed request
was retried. Combined reported usage is **2,125,100 input and 21,178 output tokens**.
No generative optimization calls occurred. Target answering made one attempt per
unique prompt. Dollars are N/A. Full-context and remote-preprocessor answer arms
were not run, so these trials do not establish net cost savings or break-even.

### Cost, ties and discarded complexity

Sidecar construction took 276.74 ms / 7,032,832 bytes for the expanded corpus and
184.36 ms / 3,891,200 bytes for Click-only. Three shuffled warm ranking repeats
checked 756 candidate lists against the earlier run. Ranking-only median wall time:
BM25 22.47 ms; flat fields 16.56; gate 4 19.32; balanced 4 66.62; escape 4 64.57.
CPU measurements are retained separately, but the timer's 15.625 ms granularity
makes many short operations round to zero. Live answer I/O overlapped these local
profiles; no CPU test suite did. Cross-cycle even-BM25 timing changed substantially,
so the apparent slowdown versus cycle 14 is not attributed to an algorithm change.

A separate SQLite prototype defers metadata lookup using FTS5 rank streaming and
reads the entire boundary-score tie group to keep source ordering. This follows
[SQLite's documented rank mechanism](https://www.sqlite.org/fts5.html), not a new
binary/index format. Five shuffled paired repeats checked 300 identical candidate
lists. Real-question top-60 ranking improved **16.94 to 11.74 ms** (1.44x), but
2,000 equal-score files regressed **4.34 to 16.46 ms** (3.79x slower). Top-240 real
queries improved only 17.90 to 15.80 ms. The synthetic tie flood is a stress test,
not a large public-corpus claim. This challenger is not promoted. A permanent test
covers ties, incremental edits, orphan FTS rows and alternate rank configuration.

### Unexpected evidence failures and repairs

The public `audit-run` command still invented 100% quality retention on zero
baseline success, treated missing expected facts as successful substring matches,
joined answer/usage rows by position, accepted incomplete usage, hid increased
cost as zero savings, and priced unknown models via a placeholder. We reproduced
**21 failing cases out of 22** before repair. Additional malformed-mode cases were
then added. Schema 2 requires matching unique IDs, nonempty expected fixtures and
valid integer usage. It rejects duplicate JSON fields and non-finite constants,
retains signed token differences, returns null/N/A for zero-denominator retention,
and reports only declared substring-fixture outcomes. All dollar fields are N/A;
execution and billing provenance are not authenticated by this log schema.

Seven shuffled audit profiles measured 20 / 1,000 / 10,000 synthetic tasks:
**0.98 to 0.93 / 11.36 to 19.44 / 111.22 to 186.72 ms** before/after. Validation adds
work at scale; there is no claimed performance gain. The first profiling attempt
failed only while serializing the result because a path string was passed instead
of a Path. It was corrected and the complete paired run repeated; only the second
run is recorded as timing evidence. The `.npk` query/compiler code is unchanged.

The modern research reporter accepted six planted corruptions: missing or duplicated
observations, changed method/budget, altered usage and replaced answers. All six
failed-before counterexamples now pass rejection tests. Every report row is rebuilt
from the frozen plan, raw ledger and independent grade, including explicit replay
semantics. Both completed live runs passed the repaired report without another API
call; the conclusions above are based on those checks.

Three scanner tests also failed before repair: missing, unreadable and invalid-UTF-8
tracked text was silently skipped. Those now fail the scan as incomplete without
printing exception values. Decoded archive contents are screened separately. This
is limited credential-pattern detection, not universal secret detection.

### Keep/discard and next cycle

Keep the audit/report/scanner repairs, permanent counterexamples, executable
composed task oracles and reproducible evidence. **591 tests pass, two skip; all
34 mutants are killed** (31 product, two grading/reporting, one scanner), including
the original dependency, query-preservation and fallback mutants. Full tests and
mutation runs were separate from CPU timing. Archived failed-before tests retain
invalid old behavior only as reproduction evidence.

Discard promotion of hierarchical routing and deferred metadata lookup. Graph,
local neural and reranker options remain experimental. This is not a clean whole
product audit: separate legacy pricing entries still treat descriptive placeholder
sources as verified, and old benchmark writers still label substring/mock results
accuracy and fabricate completion-token counts. These are the next required repair;
they are not evidence for current published economics. The audit command itself
no longer emits their invented dollar figures.

**CONJECTURE:** retrieval polluted by answer-format instructions and combined
questions can improve through deterministic query decomposition with original-query
fusion and explicit negative-constraint preservation. Test it only after closing the
remaining reporting/pricing defects. Separate seed omission from target-model errors,
freeze new question families before inspecting results, and retain BM25 comparisons.
No theorem of evidence sufficiency, universal speedup or probability of safety is
claimed. The portable compiler remains useful; differentiated retrieval remains
**PIVOT REQUIRED**.

Exact sources, plans, contexts, responses, preparation/execution/final code and
profiles are in `cycle15-evidence.json.gz`. The content-addressed archive, decoded
pattern scan, tests, mutations and code hashes are bound by `cycle15-summary.json`.

## Cycle 16 — pricing provenance, execution truth and the optional-client boundary

Date: 2026-09-07. Starting champion `5429fa7`. Verdict: **PIVOT REQUIRED**.
This cycle repairs remaining claim-producing paths and identifies a concrete
resource hypothesis. It makes **zero new answer-model calls**. Existing cycle-15
answers are regraded as REPLAY evidence. The `.npk` compiler/selector are unchanged.

### What failed and what was kept

Seventeen new pricing/client/trace contract checks failed against the previous
build. Unknown model names received arbitrary prices; mock/default aliases borrowed
OpenAI rates; a nonempty placeholder source/date counted as verification; invalid
counts were accepted; tiny quotes were rounded per request; negative savings were
clipped. The planner invented 100 output tokens, fixed token-to-latency formulas
and cache hits. Traces aggregated these claims, silently skipped corrupt JSON,
and mixed provider counts with planner estimates. The old economics script inserted
77.8/83.3/100% historical accuracy numbers into a different workload.

The supported rate table now contains exact OpenAI `gpt-4o` and `gpt-4o-mini` IDs,
with an explicitly matched provider, source URL, review date and standard text-fee
scope. The official [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o)
and [GPT-4o Mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) pages
were opened and checked on 2026-09-07. Rates are hypothetical text quotes, not
verified invoices. Unknown providers/models yield None/N/A, never fallback prices.
NVIDIA, gateway, mock and default identities cannot borrow these quotes. Calendar
metadata validation does not claim source authentication or bind runtime import to
an always-correct local clock. No remote price lookup occurs during runtime.

Negative, fractional and boolean usage counts and cache counts larger than input
are rejected. Decimal arithmetic avoids rounding tiny requests before aggregation.
Quote differences retain negative values and undefined zero-baseline ratios are
None. The planner quotes only hypothetical uncached input when a provider/model
is documented. Otherwise it ranks estimated input tokens. Unsupported output,
latency and cache-hit forecasts and the unused latency-filter argument are removed.

Another defect inverted the optional client's configured maximum risk score:
0.05 was passed as a minimum confidence score instead of the intended 0.95. The
client now converts the threshold correctly. It remains an uncalibrated retrieval
score, not a probability. A separate failing-before test also caught full-context
passthrough labelled calibrated; all plan risks now remain uncalibrated, with
explicit zero dropped-context evidence for raw passthrough.

Trace schema 2 separates planner estimates from provider-adapter usage. Shadow
mode logs the unchanged prompt and zero executed reduction, retaining its hypothetical
plan separately. Optimized estimates use one counting basis on both sides. Corrupt
JSON, duplicate identities and inconsistent differences fail analysis; incompatible
counting bases are grouped and legacy costs are not totalled. Actual billed cost,
net savings and break-even remain N/A without the missing measurements.

Six obsolete runners were deleted: evaluation_suite, msc_ablation, sealed_suite_200,
context_optimization_benchmark, component_ablation and live_validation. These could
produce false accuracy/completion figures or imply validation of mismatched inspected
fixtures. Needed static inputs survive in legacy_fixtures; the profiler and parameter
sweep imports use the proper modules. Historical source/results remain archived as
historical evidence, not current behavior. Provider-name accuracy inference and
summary overrides were removed from metrics helpers. The incremental benchmark's
structural check is now called retrieval_fixture_pass_fraction.

### Economics from actual records

The replacement economics command reads one frozen plan, its context hashes,
request identities, raw response files, ledger, usage and complete observations.
It regrades exact JSON answers and refuses missing attempt counts. A REPLAY/LOCAL
report makes zero API calls. Hypothetical text quotes require an explicit provider
assumption and exact returned model ID; they cannot be interpreted as billing.
Missing full-context or remote-preprocessor arms and local CPU prices are not invented.
Six tampering/unknown-count cases have permanent tests, along with a network-denial
fixture showing that the reporter itself has no model dependency.

Both cycle-15 runs pass this reconstruction: Nemotron has 234 attempts/227 responses;
DeepSeek has 234/217. Those are historical ledger counts, **not new calls this cycle**.
The replays preserve 2,125,100 reported input and 21,178 output tokens across completed
unique answers. NVIDIA pricing is unsupported, so all dollar/net-savings claims
remain N/A. No answer superiority or economic break-even is inferred.

### Policy and overhead at increasing context size

EMPIRICAL: three shuffled before/after process pairs use literal whole public
Click/CPython files wrapped as legacy-client input. Context estimates including
file wrappers are **2,202 / 26,004 / 51,938 / 102,491 chars-divided-by-four tokens**.
The planner uses a different estimator; both numbers are retained per request.
The target is MOCK and the network is prohibited. Each process makes a first and
repeat call per size/mode. These are legacy-client diagnostics, not `.npk` query
benchmarks or answer-quality comparisons.

| Context estimate | Optimized before/after warm ms | Shadow before/after warm ms |
| ---: | ---: | ---: |
| 2,202 | 4.54 / 5.35 | 4.99 / 4.81 |
| 26,004 | 46.83 / 47.04 | 46.22 / 48.71 |
| 51,938 | 92.15 / 93.51 | 92.12 / 96.28 |
| 102,491 | 174.00 / 192.35 | 184.08 / 187.64 |

All **96 calls** retain the exact query/system messages, nonempty source and one
mock provider invocation. On the largest context the old optimized client dispatched
2,444 planner-estimated tokens; the corrected client dispatched 107,918. The old
shadow trace claimed 105,474 avoided tokens despite sending all 107,918; the new
trace correctly reports zero. At the smallest size the corrected optimized client
still avoids seven estimated tokens. This is policy/measurement correction, not
proof that either selected evidence set produces the better answer.

An earlier three-pair profile before the passthrough-label repair is also retained,
with its exact candidate snapshot. It had ~174 ms after versus ~175 ms before at
the largest optimized case. Final measurements vary; no performance improvement is
claimed. CPU tests and mutation testing were separate from these profiles. Timings
include mock response and trace I/O. RSS samples are not peak-memory measurements.

### A useful new bottleneck hypothesis

EMPIRICAL: a separate three-trial fresh-process probe isolates the APIs. Median
resident memory after one query is **25.65 MB** for compiled `.npk` selection,
**684.28 MB** for the optional legacy planner, and **23.72 MB** for that planner
with the existing `NPK_ENABLE_EMBEDDINGS=0` setting. Corresponding import-plus-query
medians are **50.84 / 4,212.08 / 44.97 ms**. Torch and Transformers load only in the
middle case. All network access is forbidden. The probe's reproduction script is
retained; this exploratory measurement is not preregistered independent validation.

This does not show that `.npk` consumes 684 MB, or establish evidence equality
when disabling embeddings. The comparison uses different APIs/inputs and one
small legacy query. It does reveal a large optional-client initialization cost.
**CONJECTURE:** explicit opt-in encoders can remove that cost without losing useful
evidence on the workloads that matter. The next cycle should measure evidence
changes across harder queries before making the default-policy decision, then
resume deterministic query decomposition with original-query/constraint preservation.

### Acceptance and next cycle

**613 tests pass, two skip. All 40 mutation tripwires are killed** (37 product,
two grading/reporting, one scanner), including the original three critical mutants
and new provider, price, usage, provenance, trace and threshold-inversion attacks.
The first full run correctly failed its strict scanner because intentional file
removals had not yet been staged; staging the deletions resolved the missing-file
condition without weakening the scanner. The original failure XML is retained.

Keep the pricing/client/trace repairs, raw-evidence economics, conservative policy,
reusable fixtures and mutation tripwires. Discard fake forecasts, old metrics,
unsupported pricing and duplicated obsolete runners. No retrieval challenger is
promoted. Exact models, target-specific token budgets, calibrated omission risk,
independent unseen evaluation and complete matched-budget answer economics remain
research/integration work. The compiled artifact remains useful infrastructure;
the differentiated retrieval claim is still **PIVOT REQUIRED**.

## Cycle 17 — Make optional encoders explicit; attack legacy safety boundaries

**Verdict: PIVOT REQUIRED.** The default compiled BM25 runtime and `.npk` format
remain unchanged. The older optional client becomes cheaper and its boundary
checks become stricter. No new generative answer-model calls were made.

### Discoveries and failed assumptions

The default older selector probed local MiniLM on ordinary requests. Disabling
embeddings had been available as an environment setting, but the planner/client
did not expose an explicit opt-in and defaulted to neural initialization. Seven
encoder-contract checks failed before repair (including two missing-API failures).
An initial fresh-process test accidentally allowed a caught import error to hide
the attempted import; the final test records attempted imports independently.
Both pre-repair XML versions remain available.

Ten budget-contract checks failed before repair. The selector admitted an
oversized first seed, summed rounded per-block estimates, and omitted separators.
The retriever also treated oversized single blocks as ordinary success and did
not re-check the actual joined dependency output. A concrete eight-block fixture
requested eight estimated tokens and emitted 18. The real-source grid did not
trigger a cap violation; these are distinct regression counterexamples.

Six new message-boundary counterexamples exposed guard failures: a long current
question could conceal source deletion; earlier query paragraphs disappeared
before checking preservation; a query copied into an older assistant message
could satisfy the guard; whitespace was stripped; and explicit combined prompts
and ambiguous long messages had unsafe boundaries. Four estimator-contract tests
also failed: the client labeled chars/3.8 estimates as chars/4.

Repairs make local embeddings explicit, enforce joined seed budgets, and label
raw fallback with zero savings. The source-presence guard excludes the same
original query from both sides and requires the complete current query in its
latest user slot. Ambiguous input is preserved in full. Estimator metadata now
uses `planner_chars_div3_8_estimate`; old mislabeled v2 traces are rejected.
These guards do not prove semantic sufficiency or calibrated omission risk.

### Paired LOCAL seed evidence

The frozen run used the existing pinned CPython/Click source, 2,183 compiled
blocks, 28 known correlated tasks, no graph edges, and 512/2,048/8,192 caps under
the same legacy estimator. Per request: **589,197 available joined estimated
tokens**, versus 587,038 when separately estimated blocks are summed. Neither
number is a cumulative total. Required source spans are diagnostics, not accuracy.

Real CPU MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` was loaded
offline. Load cost 9,769 ms in this experiment; the first document/query scoring
call cost 45,787 ms. Subsequent queries reused document vectors and had median
scoring cost 25.27 ms. Exact scores were replayed into old/new selector snapshots.
The 504 selections averaged 2,157 ms excluding encoder work, exposing the older
text-scanning path's cost. These are not compiled FTS5 query timings.

At every budget, lexical selection's mean required-span fraction was 0.0476 and
embedding fusion's was 0.0298. Neither method retained all required spans on any
of the 28 tasks. Holding mode constant, all 84 lexical and all 84 embedding
selections matched before/after. The default changes to the cheaper lexical
channel; no quality-superiority claim follows. The public-grid cap checks pass,
and all 504 observations reconstruct from frozen blocks, indices and requirements.

The seed run froze before the later message-guard and estimator-label repairs.
The exact intermediate candidate and final code are both archived. Measured
selector, scorer, retriever, estimator and encoder files match final source;
only safety/planner/runtime/telemetry differ between those snapshots.

### Controlled optional-client profile

Three shuffled fresh-process trials compared old default, old explicitly
disabled, repaired default, and repaired explicit opt-in. Both snapshots were
given the same installed cache, and enabled arms had to actually load the pinned
model. This corrects the uncontrolled package-relative cache difference in prior
informal probes. All network calls were denied; the target was MOCK.

| Available context, chars/4 estimate | Old/new first call ms | Old/new warm call ms | Old/new RSS MB |
|---|---:|---:|---:|
| 2,202 | 4,077.04 / 7.33 | 5.32 / 4.65 | 684.81 / 29.13 |
| 26,004 | 1,063.25 / 56.89 | 50.13 / 49.58 | 724.16 / 30.42 |
| 51,938 | 1,401.21 / 93.47 | 94.91 / 95.04 | 731.22 / 31.58 |
| 102,491 | 1,754.08 / 180.72 | 192.13 / 175.76 | 734.96 / 33.64 |

First-call times exclude module imports and process startup. Only the smallest
case pays initial model loading; later sizes reuse model state. Imports separately
cost roughly 72 ms before and 78 ms after. RSS is after-call, not peak. The old
disabled mode performs similarly to the new default. No CPU tests or mutations
overlapped profiles; OS caches and unrelated host activity were uncontrolled.

All 96 calls preserved query/system/nonempty source and made one MOCK target
invocation. Their dispatched message digests match across every arm at each size.
A separate LOCAL replay reconstructed the exact message bytes and matched all 96
captured digests and token counts; those reconstructed files are labeled REPLAY,
not presented as raw answer-model responses. Larger inputs were passed through.
This removes avoidable cost; it does not establish target accuracy or API savings.

### Acceptance, kept/discarded, and next hypothesis

**652 tests pass, two skip. All 47 mutation checks are killed**, including the
original dependency/query/fallback mutants and seven new encoder, budget,
source-boundary, query and report attacks. The first final-check attempt found
one old shadow-mode fixture that only reduced through optional dense tie ranks.
It now uses deliberately long duplicate blocks so deterministic deduplication
supplies a real hypothetical reduction; the zero-executed-savings assertion remains.

Keep explicit local opt-in, a deterministic client default, precise fallback
classification, full query preservation, honest estimator labels and reconstructable
evidence. Discard implicit encoder initialization and the assumption that extra
embedding compute improves this legacy seed selector. Preserve the main compiled
runtime as the baseline. The source-presence tests are narrower than complete
semantic safety; the encoder remains uncalibrated and experimental.

Next: test original-query plus verbatim-clause retrieval against competent compiled
BM25/weighted BM25, then use new answer tests only if LOCAL evidence improves.
Research notes and attacks are in `research/CYCLE17_SEED_HYPOTHESES.md`; valid
negative counterexamples and qualified budget reasoning are in
`research/math/CYCLE17_COUNTEREXAMPLES.md`. The remaining ignored selector
parameters and shared CamelCase helper are recorded review questions, not claims
that changing them will improve the main retrieval default.

## Cycle 18 checkpoint — message preservation and clause retrieval

**PIVOT REQUIRED.** Message repairs are accepted; the second frozen answer-model
run is still pending. This is a checkpoint, not a completed two-model evaluation.

Five new attacks showed that the older chat planner changed meaningful string
spacing, repeated event records, requested license text, literal blank lines and
message/tool metadata while labeling the transform lossless. All five changes
passed its existing guards. The generic deduplicator and prefix rearranger,
their flags, and an obsolete hardcoded-savings profiler have been deleted.
Non-user messages and message envelopes are preserved; unmeasured transforms
carry unknown ordinal risk. All five attacked inputs now remain byte-identical.

Three shuffled fresh-process trials with real source and a MOCK target measured
warm client latency at 2,202/26,004/51,938/102,491 available chars/4 tokens.
Before: 5.72/66.05/112.51/206.69 ms. After: 4.70/50.56/93.82/190.48 ms.
All 36 repaired dispatches preserved their complete input; nine smallest-context
dispatches had changed before. The smallest first call regressed slightly,
7.90 to 8.82 ms. CPU tests/mutations did not overlap profiles; LIVE IO and host
activity did. These modest timings justify no 10× or economic claim.

**681 tests pass, two skip; all 51 mutation checks are killed**, including the
original three and four new preservation/risk mutants. The first full run failed
because deleted files were still in Git's index. Their deletion was staged; the
scanner was retained and the final full run passed. The shadow-accounting test
now uses distinct relevant/irrelevant files for actual lexical reduction instead
of relying on unsafe repeated-text removal.

The LOCAL seed experiment froze eight new stdlib behaviors plus 28 known controls.
It used the same 559,738 available estimated tokens and 2,183 source blocks for
all methods, swept 512/2,048/8,192 budgets, and reconstructed all 540 selections.
At 2K on new tasks, whole-required-span counts were BM25 3/8, balanced clauses
2/8, ordinary clause fusion 0/8, focused fusion 0/8. Weighted fields matched BM25.
Repeated ranking medians: BM25 8.54 ms, weighted fields 6.82 ms, clause methods
18.51–19.85 ms. Required spans are diagnostics, not answer accuracy.

Nemotron completed its frozen 245 attempts: 173 answers, 66 HTTP 503 and six HTTP
429 failures. A server-error pause was respected before resuming only unattempted
requests at one worker. Failed/uncertain requests were not retried. On the eight
new cases, balanced clauses had 0 wins/2 losses/4 missing pairs against BM25 at
2K and 1 win/1 loss/2 missing pairs at 8K. The no-context control remains explicit.
No challenger earns promotion. DeepSeek's ledger remains active and its eventual
results will be audited separately; no complete second-model claim is made here.

Keep message repairs, regression tests and reconstructable evidence. Discard
generic destructive transforms; leave clause retrieval outside the product.
Next, finish the existing answer run, then test whether missing exact-version
API documentation explains semantic failures. Any corpus addition will be a new
declared challenger with matched within-corpus budgets. See the
[decision](docs/decisions/0012-message-preservation-and-clause-checkpoint.md),
[Nemotron report](experiments/results/cycle18-nemotron-answers.md), and
[qualified counterexamples](research/math/CYCLE18_COUNTEREXAMPLES.md).

## Cycle 19 — manual corpus and explicit answer replays

**PIVOT REQUIRED.** The three exact-version manuals hypothesis failed to improve
the eight difficult behavior tasks in completed Nemotron comparisons. BM25 at
2K had 0 wins/2 losses/2 ties/4 missing; at 8K 0/0/3/5. Weighted fields had
0/0/6/2 and 0/1/3/4. Older controls include gains, so this does not prove that
manuals cannot help. The original 36 questions remain known, not sealed.

All 432 LOCAL selections were reconstructed; 216 original outputs reproduced the
prior cycle. Context available per task grew from 559,738 to 589,949 estimated
tokens. Existing incremental compilation parsed only three new files, skipping
135; median time was 531.62 ms versus 3,687.38 ms for a full build. Six compiled
representations and 108 paired queries agreed. Timing excludes the initial pack
copy and later integrity checks; the source scan remains linear.

There were 73 new LIVE attempts (55 answers, 18 HTTP 503 errors) and 173 explicitly
replayed records (117 prior answers, 56 prior errors), with no unattempted requests
remaining. Shared prompts are not independent repetitions. Replays now require
archived original response/plan bytes and matching payloads; summary content and
token usage must equal raw provider records. Replayed attempts count as zero new
API calls. Dollar savings remain unknown; no missing baseline arm is invented.

**706 tests pass, two skip; all 54 planted mutations are killed.** Keep replay
provenance and matched-corpus comparisons. Do not promote manuals, weighted fields
or clause retrieval over default BM25. Next test the answering model with known
supporting source and explicit reasoning settings, because retrieval and answer
generation failures cannot be inferred from the same aggregate error count.
Cycle 18's DeepSeek run is still separately active.

See the [decision](docs/decisions/0013-manual-corpus-and-replay-provenance.md) and
[answer report](experiments/results/cycle19-nemotron-answers.md).

## Cycle 20 — answering-model and privileged-source controls

**PIVOT REQUIRED.** Eight known questions were held fixed across original BM25,
no-source and manually chosen source conditions. The direct configuration used
thinking off and a 2,048 output cap; reasoning used thinking on, a 16,384 output
cap and a longer socket timeout. This is a combined configuration diagnostic.

Direct correct/completed counts: none 1/5, BM25 1/6, privileged source 1/7.
Reasoning: 2/5, 3/7, 2/5 respectively, each out of eight planned tasks. On paired
BM25 inputs, reasoning had 2 wins/1 loss/2 ties/3 missing; on privileged inputs,
2/1/1/4. Privileged source itself had no direct-mode wins or losses against BM25
and one win/one loss in reasoning mode. Every completed answer was valid JSON;
many still contained wrong values.

There were 32 new LIVE attempts, 24 answers and eight HTTP 503 failures, plus
16 explicit parent replays including five earlier failures. Direct completed
arms averaged 45–51 output tokens; reasoning 1,955–2,401. Target latency increased
substantially. Different completed sets preclude treating these ranges as a
matched speed ratio; the cycle record retains matched means. There is no new
price or savings claim and no generative optimizer call.

**712 tests pass, two skip; 56/56 mutants killed.** Keep evidence-matching and
missing-outcome checks, the raw controls, and the qualified non-identifiability
proof. Do not promote privileged selection or claim reasoning is a free gain.
Next measure source-scan versus index/integrity costs before deciding whether
an explicit changed-file update API earns its complexity. See the
[decision](docs/decisions/0014-target-competence-controls.md).

### Closing evidence audit and cycle 18 completion

DeepSeek's frozen cycle 18 plan completed 245 LIVE attempts: 208 answers, 28 HTTP
529 errors and nine timeouts. All raw observations and grades were audited.
Balanced clauses versus BM25 on the eight new behaviors had 0 wins/0 losses/7
ties/1 missing at 2K, and 0/1/6/1 at 8K. Weighted fields had one 2K win and one
8K loss. This does not establish a consistent advantage over BM25. The two
models' raw records remain distinct; no cross-model outcomes are substituted.

The archive review found a missing `pyproject.toml` in both cycle 18 and 19
archives because their file-extension filters did not cover the source manifest.
The actual corpus and selections used that file. Collection now follows the
manifest and verifies its paths and hashes. The cycle 20 archive supplements the
omission without rewriting either sealed predecessor. After six regression
cases, **718 tests pass and two skip; all 57 mutations are caught**, including
the additional archive-omission attack.

## Cycle 21 gate — profile before adding an update API

**EMPIRICAL; no compiler change.** Three shuffled LOCAL repetitions used the
same 138 exact public-source files, approximately 590K available estimated
tokens. No-change updates took a median 76.44 ms, one-file changes 227.64 ms,
two-file changes 233.90 ms and 14-file changes 624.81 ms. Twelve updated artifacts
matched independent full rebuilds, and 60 paired query outputs agreed. Copies,
full validation and reference builds were outside update timing. No CPU tests,
mutations or archive compression overlapped; LIVE IO and host activity did.

Scanning used about 95% of no-change time, but only 28%, 30% and 13% of the three
changed-file cases. Under fixed remaining cost, eliminating all scan work gives
optimistic median bounds of 19.59×, 1.39×, 1.43× and 1.14×. These are not measured
challenger speedups. No-change event knowledge is also weaker than a verified
whole-tree scan. Discard the proposed changed-file API for this measured workload
instead of adding new partial-synchronization semantics for a small gain.

Keep the profile and its exact sources in the cycle 20 evidence archive. The next
highest-value hypothesis is whether changed-block indexing dominates updates of
large individual files; measure that before attempting a format or update change.

## Cycle 22 — measure exact block reuse before promoting it

**EMPIRICAL; research challenger only.** Three pinned public CPython files were
compiled as separate artifacts with approximately 30K, 88K and 117K available
estimated tokens. Five shuffled update repetitions found exact block reuse
improved append updates by 1.35× (Python), 2.13× (C) and 1.78× (RST). A leading
blank line preserved 179/180 Python blocks, but zero C or RST blocks; the latter
updates improved only 1.02× and regressed slightly (0.997×). Python parsing
remained a substantial floor. No 10× result or broad repository claim emerged.

All 60 updated artifacts matched fresh builds; 300 paired queries agreed at
the same 2,048-token cap. The initial stage profile passed another 18 artifact
and 90 query comparisons. Eight regression cases attack duplicate occurrences,
span updates, repeated edits, tied retrieval, scope rejection and rollback.
These are LOCAL compilation checks, not answer accuracy. See the
[measurements and limitations](research/CYCLE22_BLOCK_REUSE.md).

Final acceptance: **726 tests passed, two skipped; all 58 mutation tripwires
were killed**, including the three original critical mutations.

Keep the archive and qualified multiset reuse proof. Do not ship the temporary
single-threaded adapter or extend it to embeddings/graphs without evidence.
The next highest-value hypothesis is content-anchored or structural boundaries:
test whether they improve reuse after insertions without harming retrieval or
making compilation expensive. The main product verdict remains **PIVOT REQUIRED**
for claims of differentiated answer quality beyond competent retrieval.

## Cycle 23 — content boundaries versus a stronger granularity control

**EMPIRICAL; LOCAL, no runtime change.** Line-content anchors retained about
93–99.9% of block payload after a leading blank line in five public CPython
files, where the old splitter retained none. However, C splitting became slower.
An adversarial 1,000-line source defeated the hints and retained zero blocks;
that counterexample is now a permanent regression.

Ten developer-authored manual questions were tested on the same 177,554-token
source corpus. Six splitters used identical BM25 selection and four budgets,
with 720 selections across three shuffled trials. Ordinary 2,048-character
windows retained all required passages on 5/10 tasks at 512 tokens and 7/10 at
1,024, versus 4/10 and 5/10 for similarly capped anchors. Anchors reached 8/10
at 2,048 versus 7/10 for that control. These are source-passage diagnostics,
not actual answer quality; equivalent unannotated passages are not credited.

Seventy-two updates and 720 paired query comparisons matched fresh builds.
Leading-line updates improved 2.16–2.49× through anchors plus row reuse, but
ordinary character windows gained 2.08–2.32× as well. At the larger ceiling,
scattered edits left 389 reusable anchor blocks versus eight fixed-window blocks,
yet reused update times were about 819 versus 824 ms. Reusable payload is not
a substitute for measuring total work. No 10× total-update result emerged.

Keep the exact evidence, the fixed-size controls and twelve regression cases.
Discard automatic promotion of content hashing: it has not earned its added
complexity on these measurements. The default remains the existing independent
compiler/runtime. Next test small indexing units with source-aware passage
assembly against the competent fixed-size control, including missing qualifiers
and version boundaries on unseen material. **PIVOT REQUIRED** still describes
the differentiated answer-quality claim. See the
[full cycle](research/CYCLE23_BOUNDARIES.md).

Final acceptance: **738 tests passed, two skipped; all 59 mutations were caught**.
The closing audit reconstructs 720 recorded contexts and their passage metrics
from source spans. Raw executed sources remain separate from later reporting
code; the plot retains every budget point, including zero-hit outcomes.

## Cycle 24 — repair omitted source, then test small units and nearby passages

**EMPIRICAL.** A new corpus of 153 SQLAlchemy 2.0.43 documentation files exposes a
real compiler defect: the generic `build` exclusion silently erased all source
under `doc/build`. Compiler 5.3 removes that exclusion and requires recompilation
before old artifacts can receive incremental updates. An exact manifest gate
now rejects valid-but-empty or partial benchmark artifacts. All expected paths
and raw hashes match after repair. Failed preparations remain separate evidence;
no paths were flattened and no LIVE calls were spent debugging the omission or
the subsequent benchmark return-type error.

Ten newly authored SQLite behavior scenarios were executed twice in an isolated,
pinned SQLAlchemy environment. Their labels never enter the compiled corpus.
The full corpus supplies approximately 528K estimated tokens per question.
Eight retrieval/assembly methods at four matched budgets produced 960 LOCAL
observations with reconstructed literal spans and repeatable context hashes.
At 4,096 tokens, paragraph expansion retained all specified manual passages on
5/10 tasks, versus 3/10 for shared BM25 and 4/10 for shared hybrid. At 1,024 it
retained none, versus 1/10 and 0/10. These are passage diagnostics, not accuracy.

One initial compile measured 3.54 seconds for fixed 2,048-character units,
4.78 seconds for 512-character units and 113.95 seconds for real MiniLM embeddings.
Shared BM25 selection medians ranged 36–54 ms across caps; paragraph expansion
57–76 ms; shared hybrid 195–248 ms. All hybrid cells used the neural channel.
These measurements provide no 10× result or reason to make embeddings mandatory.

The frozen answer comparison completed 78 unique LIVE attempts: 61 responses,
17 HTTP 503 failures, zero generative optimizer calls. BM25 passed 2/8 completed
tasks at 1K and 3/8 at 4K; paragraph expansion 4/9 and 2/9; hybrid 1/7 and 2/7.
Each arm planned ten tasks. Full-source prompts averaged 512,590 actual input
tokens and passed 0/7 completed tasks under the strict JSON contract; no-source
passed 2/8. These are one-model executable-scenario observations, not general
model rankings. Full-source cache hits were reported on six responses; billing,
net savings and break-even remain N/A without pricing and local cost evidence.

Attacking the apparent 1K paragraph gain found that one of its two paired wins
was correct BM25 values in invalid JSON. Its sole 4K loss was also formatting.
A supplementary bounded-literal diagnostic preserves original grades and leaves
one value-level win at 1K and none at 4K. Only three tasks completed every selected
arm/cap, so the complete-case frontier is descriptive and too small for promotion.

Keep the compiler source repair, corpus identity gate and adversarial regressions.
Discard promotion from passage checks or formatting-dependent answer differences.
**765 tests pass, two skip; all 63 mutations are killed**, including the three
original critical failures. **PIVOT REQUIRED** still describes claims of reliable
answer-quality superiority over competent retrieval. Next measure operation-aware
query views against existing clause controls, including how repeated schema and
the encoder's 256-token limit affect retained query information; this remains
an untested hypothesis. See the [cycle report](research/CYCLE24_UNIT_PASSAGES.md).

## Cycle 25 — a narrow identifier spelling repair earns its place

**EMPIRICAL; LOCAL, zero generative model calls.** Query preprocessing lowercased identifiers
before attempting camel-case splitting, erasing the boundaries it needed.
A frozen 2,304-selection comparison used 32 sampled documentation identifiers,
three query forms, two budgets, three trials and four methods. Literal source
hits for underscore names queried as bare camel-case aliases rose from 0/16 to
14/16 at 1K and 15/16 at 4K with vocabulary-checked splitting. The actual MiniLM
hybrid reached 3/16 and 6/16. These are spelling lookup probes, not answer quality;
the sampled names include examples, anchors and inflected SQL words.

Unconditional splitting reached 16/16 on the latter slice but made known-compound
queries much slower: 1.13 to 17.46 ms median at 4K. Checking the current lexical
vocabulary first preserved the original selections and took 1.12 ms there.
This avoids added work in a challenger; it does not accelerate the old product
15×. Previously failed bare-alias retrieval takes more time when it now works.

The smaller vocabulary check is promoted to the compiled runtime. Whole query
bytes and original terms survive; no new model, flag or artifact schema is added.
It reproduced all 192 prototype selections and left all 40 earlier behavior-query
selections unchanged. A newly found case-folded deduplication defect was repaired
before promotion. The `someotherobject` / `some_other_object` collision is retained
as a permanent counterexample: lexical presence does not prove intended identity.

Six default-split artifacts contained 2,035 through 527,662 available estimated
tokens. Across 432 timed requests, repaired short-alias medians ranged 0.69–2.35 ms;
long behavior questions 3.19–13.68 ms. The largest native-query slice stayed about
2.2 ms. Profiles have uncontrolled host load and one initial compile each; they
are not cross-splitter speedup claims. No concurrent agent benchmarks, tests,
archive compression or LIVE IO overlapped the measurement.

Keep the guarded spelling repair and all controls; discard unconditional splitting
as the default. **775 tests pass, two skip; all 65 mutations are killed.**
**PIVOT REQUIRED** still describes broad answer-quality superiority. Next test
source-aware identifier normalization and collision reporting against this repaired
lexical baseline before adding any index or schema complexity. See the
[complete experiment](research/CYCLE25_IDENTIFIER_SPELLING.md).

## Cycle 26 — spelling indexes improve lookup, not behavior sufficiency

**EMPIRICAL, LOCAL.** The normalized-spelling idea was tested against the current
lexical champion, normalized-source FTS, marked/unmarked spelling dictionaries,
query variants without an extra index, and real local MiniLM hybrid retrieval.
Two complete runs each contain 7,272 observations: 202 tasks, six methods, two
matched caps and three shuffled repetitions on 527,807 available tokens per
request. The second run repairs a baseline-adapter overhead error, not the
selected source: all 2,424 unique contexts and outcomes are unchanged. The audit
reconstructed all 14,544 selections from literal source spans and checked budgets.

Normalized FTS raises new-probe literal identifier presence from 69/96 to 86/96
at 1K, with 19 wins and two losses. At 4K it reaches 96/96 versus 89/96, but the
no-index variant also reaches 96/96. On the ten existing behavior scenarios,
current lexical retains all annotated passages on 1/10 at 1K and 3/10 at 4K;
normalized FTS gets 0/10 and 3/10, dictionary methods 0/10 and 0/10, query variants
0/10 and 1/10, and hybrid 0/10 and 4/10. These are source diagnostics, not answer
accuracy or sealed independent validation. No challenger earns default promotion.
Marked and broad dictionary contexts are identical in all 404 task/cap pairs.

New-spelling query medians are 18.23/38.27 ms for current lexical, 7.20/7.73 ms
for normalized FTS, and 68.13/107.79 ms for actual local hybrid at 1K/4K. The
combined research side index costs one measured 2.92-second compilation and
16,121,856 bytes. Its two indexes share that container, so those costs cannot be
assigned wholly to either one. Initial query run latency for normalized FTS is
superseded because its adapter executed and discarded an unused lexical search.
The original raw data, executed code and explicit followup remain preserved.

The first incremental writer passed sequential checks but failed a controlled
concurrent-update counterexample: ownership was cached before the write lock.
Acquiring `BEGIN IMMEDIATE` before that read fixes the mixed-index result. The
actual product compiler already used this order. The final experimental index
update medians are 26.43/26.99/100.78/401.50 ms for 0/1/2/16 changed files, versus
fresh-index medians 3,446.38/3,578.55/3,173.41/3,219.05 ms. Core source updates
are reported separately. Across the before/after runs, 120 logical-table and 240
rank comparisons match fresh indexes. Host variance prevents attributing the
before/after timing difference to the lock alone. This is optional maintenance
work avoided, not a 10× product economics claim.

Keep the narrow controls, collision counterexample, transaction repair and
regressions. Discard general spelling-index promotion, the marked-only extra
option on this corpus, and the wasteful benchmark adapter. **785 tests pass,
two skip; all 69 mutants are killed.** The first mutation attempt recorded 68
kills and one harness classification error: pytest's missing-exception failure
did not meet the harness's explicit-assertion rule. The test now asserts observed
rejection directly; the strict harness was not weakened. Its first result and
original test are retained.

No generative/API calls were made in this cycle; local encoder inference was
measured explicitly. Billing cost, savings and billing break-even remain N/A.
The product remains an LLM-independent local context compiler/runtime, and the
overall research verdict remains **PIVOT REQUIRED**. Next test operation-aware
static query views against existing clause and lexical baselines on behavior
scenarios; this is a conjecture, and prior clause failures must remain controls.
See the [complete experiment](research/CYCLE26_SPELLING_INDEX.md).

## Cycle 27 — operation views do not earn answer-quality promotion

**EMPIRICAL.** Eight query policies sweep 1K/2K/4K caps on 20 executable SQLAlchemy
scenarios and their padded-query variants, using the same 153 manuals, 1,141
blocks and source assembler. Each request has 527,598 corpus / 527,807 available
estimated tokens. All 2,880 source selections are reconstructed; the 960 unique
cells have identical context bytes across three repetitions. Combined operation
views raise known all-annotated-passage retention from BM25's 3/10 to 8/10 at 4K;
new-scenario retention rises from 2/10 to 4/10. New-scenario 4K selection medians
are 64.18 ms BM25, 92.41 ms combined and 215.79 ms ordinary hybrid. These are
LOCAL source diagnostics with uncontrolled host load, not target accuracy.

The pinned encoder truncates 17/20 original queries. All 20 padded variants
produce identical complete encoder input features and omit the actual scenario.
The formal result concerns the bounded dense representation, not the full-query
lexical channel or answering model. Focused views cannot promise to retain every
constraint merely because they fit inside the encoder window.

Five methods at matched 1K/4K caps, plus full/no-source controls, yield 240 planned
answer observations and 217 terminal unique payloads. There are 168 new LIVE
attempts, 125 answers and 43 service failures; 49 explicit REPLAY records include
37 prior answers and 12 old failures. No failed or uncertain payload was retried.
The target is Nemotron-3-Super-120B-A12B, with frozen non-thinking settings. Known
combined-view 4K pairs have zero wins, one loss and five ties versus BM25, with
four missing. New ordinary-hybrid 1K pairs have three wins, no losses and five
ties, with two missing; the literal-value diagnostic has two wins, no losses,
five ties and three unresolved. The operation candidate does not beat this
strong control. Formatting diagnostics preserve primary grades. Small,
selectively incomplete common-case frontiers do not justify promotion.

Successful new calls report 4,416,318 input / 3,206 output tokens; REPLAY reports
3,648,148 / 1,043 from old calls. Costs, savings and break-even remain N/A.
The optimizer made zero generative calls, and the product runtime is unchanged.

Before/after regressions capture two focused-search fallback failures, three
Unicode physical-line failures, and two rate-limit scheduler failures using
synthetic LOCAL responses. Empty focused retrieval now tries the original query;
AST spans convert UTF-8 byte columns using physical CR/LF lines; a single HTTP
429 pauses after the already-dispatched batch. Executed source versions and all
failed-test outputs remain archived. The final parser matches all 40 frozen query
views exactly. **803 tests pass, two skip, and all 73 critical mutants are killed.**

Keep the controls, counterexamples and repairs; discard general promotion of
operation views and answer claims inferred from passage retention. Verdict:
**PIVOT REQUIRED**. Next conjecture: expand the declared corpus to include pinned
API source/docstrings referenced by manual directives, then test against BM25 and
ordinary hybrid at matched budgets. Missing rendered API bodies reflect the
manual-only corpus definition, not an omitted declared source file. See the
[complete experiment](research/CYCLE27_OPERATION_QUERIES.md).

## Cycle 28 — Open checkpoint: the rival exposes a retrieval gap

The API-source experiment added all 256 pinned SQLAlchemy library Python files
to the 153-file manual corpus and reconstructed 1,080 LOCAL observations. It
remains open for target-answer validation. An equivalent symbol SQL rewrite
reduced isolated expanded-corpus channel latency from 276.15 to 145.35 ms; it
has not been promoted and is not a whole-query improvement claim.

The user then identified CRISP as a rival. A read-only snapshot and fresh builds
enabled a seven-arm, five-budget comparison on its current 246 tasks / 207
distinct questions. All 8,610 contexts were audited, including 86,871 source
items. At 2,048 actual context tokens, NeuralPack's method-level chunks plus
exact costing reached 62.2% needle retention; CRISP reached 95.1%, and its
simpler BM25-plus-structure baseline reached 93.9%. The advantage persists
under question-group resampling. These are inspected source-retrieval tasks,
not answer-accuracy validation or the rival's older 300-task headline.

The default estimated cap exceeded actual BPE budgets on 36/1,230 observations;
average conservative estimates do not establish a per-request bound. A separate
data-only acquisition of NVIDIA's pinned tokenizer/template matched all 74
successful past input-usage records. This check made no new API calls. Both
prepared SQLAlchemy target runs still have zero new calls; the shuffled v2
supersedes v1 before LIVE execution.

Keep CRISP's structural baseline, exact-cost controls and source audits.
Discard the current-selector-as-champion assumption and any claim that costing
or method splitting alone closes the gap. Two interrupted comparison runs are
retained as incomplete; checkpointed batches finished with bounded memory.
The infrastructure checkpoint has **826 passing tests, 2 skips and 76 killed
mutants**. A verified standard TAR/XZ archive preserves the rival inputs,
artifacts, outputs and replay provenance with zero recognized credential-pattern
matches. It explicitly marks the cycle and goal incomplete.

The next highest-value work is a product repair for exact local budgets and
stronger code-aware seeds, followed by executable answer tests against the
audited structural baseline. Provisional verdict for the existing retrieval
approach: **PIVOT REQUIRED**. See the
[comparison](research/CYCLE28_CRISP_REPRODUCTION.md) and
[open working record](research/CYCLE28_WORKING_RECORD.md).

### Cycle 28 continuation: exact local budgets and bounded counting reuse

A fresh method-chunked compilation of the same frozen rival corpus contains
558,878 source tokens under the pinned NVIDIA tokenizer. The four-arm comparison
audited 2,484 selections, 44,158 literal source items and 864 timing observations.
Character estimates exceeded real caps on 61/621 distinct question/budget cells;
both exact arms stayed within every cap and produced identical contexts.

New-query exact counting is costly: median 364 ms at 2,048 tokens and 1,092 ms at
8,192. A bounded exact-text count cache reduced immediate repeats to about 9–10 ms,
while barely changing cold cost. An additive approximation was faster cold but
changed evidence and lost one tight-budget needle result; it remains experimental.
The runtime now accepts local tokenizer data, rejects random dropout, disables
truncation/padding, reconciles final counts, and keeps exact/estimated units apart.
No generative optimizer call, API key or provider state is required.

The current suite passes 831 tests and skips 22 on CPython 3.12.14. Twenty skips
are oracles pinned to CPython 3.12.10, whose canonical full-suite command never
started because automatic approval review twice timed out; two are symlink
permissions. All 84 mutation checks are killed, including the original three
critical mutants. Canonical-version verification is still pending. No new LIVE
call was made. The product gate matched 1,441 saved counts, 621 default selections
and 216 exact selections. Its 2K median was 141.54 ms cold and 4.33 ms immediately
repeated, in a separate run with uncontrolled host load. No cross-run cold-speed
gain is attributed to the code change. A synthetic real-BPE boundary regression
and its killed mutant preserve the failure of additive cost assumptions.

Keep exact counting and bounded transparent reuse; discard silent additive-cost
equivalence and any claim that caching closes the retrieval gap. Next: explicit
identifier intent, indexed path/name information and executable-answer comparison
against the stronger structural baseline. Verdict remains **PIVOT REQUIRED**.
See [the repair, experiment and limitations](research/CYCLE28_LOCAL_BUDGETS.md).

### Cycle 28 continuation: explicit references and a benchmark blind spot

The public selector lost explicit short/code words such as `get`, `id` and
`return` before retrieval. Eight new failing counterexamples now pass after
restoring atomic inline references. The fixed candidate and product agree in
920 seed rankings and 21 affected selections. All original rival questions
retain their previous rankings: this is a correctness repair that the old
benchmark does not exercise, not a claim of overtaking CRISP. Seed-stage time
is essentially unchanged (2.599 to 2.606 ms median in paired local passes).

The full suite passes 862 tests with 22 environment-related skips; all 85
mutation checks catch their defects. Canonical Python-version checks remain
pending. The nine-arm matched-block seed experiment is checkpointed at
2,500/5,589 selections, awaiting completion and independent audit. Fifteen new
source-informed behavior tasks have identical oracle answers and traces in two
fresh runs. The failed first oracle metadata attempt is retained. No new API
call was made. Keep the narrow repair; do not promote metadata/structural
features until the larger comparison and actual answers justify them.
Verdict remains **PIVOT REQUIRED**. See [the open seed study](research/CYCLE28_SEED_ABLATION.md).

### Cycle 28 continuation: metadata improves retrieval, answers still decide

The frozen nine-arm experiment completed 5,589 selections. Its independent audit
reconstructed 114,890 source items and checked all exact token caps. A separate
gate reproduced 1,863 distinct seed calls and the reported ranking scores.
At 2,048 NIM tokens, body-only retrieval retained the annotated needle on
148/246 tasks, uniform path/name metadata on 205/246, and CRISP scoring plus
selective literal raise lookup on 225/246, using identical NPK blocks. These are
source-retention measurements on inspected questions, not answer accuracy.

Increasing candidate count alone produced no selected-hit gain. Broad code-word
retention gained only one task at 2K. Keep the explicit-reference correctness
repair; do not promote either broader policy from these results. Uniform metadata
is a promising challenger, but it and CRISP's scorer both lose the traceback
construction question that ordinary BM25 answers with the expected evidence.
Short context-manager signatures crowd out the longer `Traceback.from_exception`
block even though it remains in the candidate pool. This is a ranking failure,
not missing compiled source, and it disproves a claim of uniform improvement.

Fifteen executable behavior questions now have frozen native CRISP contexts at
512/2,048/8,192 NIM tokens. The 90 native/control selections have no recorded cap
overrun or empty output, pending independent source-view audit. Real MiniLM CPU
and Qwen local GPU document encoders have completed; cross-encoder and hybrid
context selection is running. No new target call has been made at this checkpoint.
The rank-gate import guard failed once before scoring; its module/function-name
collision now has a passing permanent test. Eleven new preflight attacks reject
altered contexts, queries, counts, attribution and false fallback status.

Next: independently check all behavior selections, freeze no-context/full-context
controls and exact framed prompt counts, then collect actual target answers.
Separately test the tokenizer's documented no-offset API as a simpler way to
reduce exact-counting overhead before considering custom tokenization algorithms.
No new runtime dependency or generative optimizer call is introduced.
All numerical claims in this entry are **EMPIRICAL**; verdict **PIVOT REQUIRED**.

### Cycle 28 continuation: real answers, local model costs and an audit race

All 405 frozen behavior selections passed independent source, query and exact
budget checks at 512/2,048/8,192 tokens. The source contains 558,878 NIM tokens
per request. The LIVE plan attempted 76 distinct requests: 59 actual answers,
16 service-overload errors and one rate-limit error. Local framed counts match
all 59 successful usage records. Every arm is incomplete, so accuracy is N/A;
source-retention gains still do not establish an answer-quality winner. The
run is paused and completed/failed requests will not be silently retried.

Actual local MiniLM and Qwen document encoding cost 112.99 and 127.51 seconds;
query encoding medians were 11.19 and 43.05 ms on their declared CPU/GPU setups.
The cross-encoder costs 12.9 seconds per query for 160 candidates. It has not
earned product integration. A simpler tokenizer API reduced paired exact
selection medians about 15–17%, preserving 6,897 differential token sequences
and 270 selected outputs. This modest challenger remains experimental.

A reproduced report race could bind older outcome counts to a newer ledger
hash. Reports now reject concurrent ledger changes and preserve the exact
snapshot. Explicit request spacing and parsed Retry-After recording improve
the development executor; they do not add remote work to the runtime. Mutation
source binding now covers benchmark code and tests as well as product code.
The final full suite passes 901 tests with 22 environment-related skips, and
all 88 mutants are killed. Canonical-version oracle checks remain outstanding.

Keep the exact-budget and query-preservation repairs. Discard any ranking of
partial answer fractions, automatic graph promotion or unverified savings.
Next: attack repeated exact-tokenization work and the metadata ranking loss,
then resume never-attempted answer requests when the service recovers. The
SQLAlchemy source/answer evaluation remains open. See
[the answer checkpoint](research/CYCLE28_BEHAVIOR_ANSWERS.md). All measurements
here are **EMPIRICAL**; verdict remains **PIVOT REQUIRED**.

### Cycle 28 continuation: spend CPU deliberately, reject duplicate piece caches

A guarded BPE piece-cache prototype matched 6,903 differential inputs and all
540 public selections, but its 2K median was 185.91 ms versus 158.31 ms for
ordinary counting and 131.62 ms for the simpler no-offset API. Reject it as a
product candidate. A permanent added-token counterexample explains why naive
piece summing is also incorrect.

Speculative exact batches preserved another 1,350 public selections across
one- and four-thread runs. On four threads, batch-8 cut 2K wall time from the
no-offset control's 128.62 ms to 76.25 ms, while CPU time rose from 125.00 ms to
218.75 ms. On one thread it lost: 142.55 ms versus 129.52 ms. Keep batching
experimental as a latency/CPU tradeoff; it is not the default efficiency path
and does not improve answer quality. No new runtime complexity is promoted.

The canonical CPython 3.12.10 interpreter is now accessible through the approved
execution route. **931 tests pass, two symlink tests skip, and all 91 mutants
are killed**. The 20 previously skipped version-pinned oracle checks pass,
without changing their definitions. See
[the counting experiments](research/CYCLE28_COUNTING_COST.md). Next: prefer
the simple counter, address seed ranking, and finish the frozen target-answer
comparison. All reported numbers are **EMPIRICAL**; verdict **PIVOT REQUIRED**.

A subsequent paced batch added 17 answers and seven HTTP 503 failures from
24 new attempts. The independent 100-attempt audit now verifies 76 responses
and matching actual input counts; 24 transport failures remain missing. Every
arm is incomplete. No answer-quality winner is declared. The ledger and report
are quiescent at this checkpoint; no completed or uncertain request was retried.

### Cycle 28: source identity can cost useful code

The original plan reaches 108 attempts and 81 answers; transport failures remain
missing and every arm is incomplete. All successful actual input counts match.
A corrected post-hoc diagnosis finds wrong answers with listed function bodies
present; the diagnostic does not establish sufficient context or causal blame.

All 270 rendering selections pass independent source/packing audit. At 2K,
median header costs are 151 tokens for BM25, 145 for indexed fields and 166 for
the CRISP-derived scorer. All-listed-function exposure changes 9→7, 10→9 and
10→10 out of 15 respectively. Discard automatic source-label promotion; answer
benefit remains a CONJECTURE. Default zero-generative runtime is unchanged.

Keep the source/budget audit and repair UTF-8 plan decoding on Windows. The
45-request unchanged-context target diagnostic is prepared but unattempted after
two approval timeouts. Local setup failures were fixed before any dispatch.
The bundled suite passes 924 tests with 22 explicit skips; all 96 mutants are
killed. Final canonical full verification remains pending after launch timeouts.

Next: isolate target-configuration and source-rendering effects, then revisit
source-state completeness and boilerplate ranking. All numbers are EMPIRICAL.
Verdict: PIVOT REQUIRED. See [the cycle record](research/CYCLE28_SOURCE_IDENTITY.md).

### Cycle 28: attack crowding without a remote optimizer

A frozen 8,658-selection matrix now compares rank controls, acceptance-aware
name/file grouping and two body-BM25 fusion weights on 222 inspected questions.
The first 500 cells pass independent ordering, source and exact-budget checks,
covering 11,461 selected items. The remaining fixed matrix is running; partial
cohorts are not a completed comparison. No candidate is promoted.

Permanent counterexamples falsify universal dominance claims for both grouping
and rank fusion: forced variety can displace a second required fact, and a poor
second ranking can overrule a correct top candidate. A separate finite-queue
argument proves only candidate enumeration under its stated assumptions.
The current bundled suite passes 935 tests with 22 skips and kills all 99 mutants.

Keep the controlled experiment and independent audit; discard automatic promotion
from one repaired traceback example. Next: complete the full matrix and answer
validation. All measurements are EMPIRICAL. See
[the current study](research/CYCLE28_PACKING_CHALLENGERS.md). Verdict: PIVOT REQUIRED.

### Cycle 28: isolate incorrect structural intent

Reproduced an erroneous raise bonus from `BaseException` and `exc_type` in the
frozen rival. Added research-only action and conservative guards, explicit
all-relations-off and original controls, 22 positive/negative regressions, and
two mutation tripwires. Mixed-clause false negatives are preserved explicitly.
The 2,664-cell study is frozen and running. Its rank gate finds changes on one
of 222 questions for either guard, versus 46 when all relations are removed.
These are EMPIRICAL ranking changes, not answer-quality improvements.

The canonical suite passed 977 tests with two skips and killed 101 mutants.
An audit-only cache/order change is receiving a fresh verification run. The
8,658-cell packing matrix completed; its full independent audit is open.
The resumed target diagnostic has 18 LIVE answers and six server errors at the
24-attempt checkpoint; every successful prompt count matches the local count.
Keep useful structural hints under test; discard noun/subword inference as a
justification for a raise bonus. No product promotion. Next: completed audits,
paired losses/gains and actual answer outcomes. Verdict: PIVOT REQUIRED.

The intent study subsequently completed all 2,664 observations (789 distinct
selector computations), with independent audit still running. The targeted raw
traceback result remains a miss at 512/2,048 under both original and conservative
intent; removing the false bonus alone does not solve its budgeted selection.
Canonical v2 verification again passes 977/two skips and kills all 101 mutants.
The target diagnostic paused at 39 attempts after repeated 503s: 25 answers,
14 service errors and six unattempted. All 25 successful prompt counts match.
Paired target-setting gains are limited and missing-heavy; the four jointly
answered BM25/CRISP pairs all tie. Next: complete audits, then test seed length
normalization against the original strong baseline, recording short-method
regressions. This hypothesis is unimplemented. No promotion or answer winner.

### Cycle 28: length-normalization sweep and completed intent audit

The independent intent audit passes all 2,664 records, 789 unique admission
orders and 56,381 source-item checks. Both guards preserve the original
182/225/242 annotation hits, while disabling structural lookup gives
168/206/232. The guard fixes the false hint but not the small-budget constructor
miss. Keep this distinction; no graph-expansion or answer-quality claim follows.

Implemented a frozen five-setting BM25 length-penalty study, with exact original
and guarded-default controls, matched budgets and isolated per-request parameter
scope. The 3,996 observations are running. A simple derivative establishes only
the direction of individual pre-bonus scores under stated assumptions; a finite
example reverses two documents' order. Neither proves improved relevance.
Current canonical verification: 990 passed, two skips, all 103 mutants killed.

All 45 target-profile requests are now attempted: 28 answers and 17 server errors.
Every successful hosted prompt count matches. BM25/CRISP have only seven joint
answer pairs: one CRISP win and six ties; eight remain missing. This cannot
establish broad answer superiority. Next: audit the length sweep and packing
matrix, retain paired regressions, and promote only supported improvements.
Verdict: PIVOT REQUIRED. See CYCLE28_LENGTH_NORMALIZATION.md.

### Cycle 28: reject grouping/fusion; attack local model identity

The full packing audit passes all 8,658 source/count/admission checks and
172,235 selected source-item occurrences. An independent aggregation matches
all 39 raw-record groups. Every grouping/fusion challenger loses more annotated
evidence than it gains at every tested cap. Reject these default candidates;
keep their negative fixtures and reproducible research code. Audited curves
and paired task losses are saved, with no answer-quality or dollar-cost claim.

The length study finishes 3,996 observations (3,333 actual local selections).
Its complete independent audit remains active. A focused source/count check
finds that b=0, .25 and .5 recover the missed traceback factory at 2K, while
guarded .75 and 1 do not. This is one inspected case, insufficient for promotion.

Captured the rival's changed current source separately from the frozen baseline.
MOCK loader interception shows its advertised revision is not passed to either
model loader, and ambient online flags remain online. No real model load or
network request is claimed. NeuralPack already pins the requested revision and
forces local loading; new permanent tests attack the coincidentally-correct-cache
case, wrong loaded revision and ambient online settings. Canonical verification
passes **993 tests, two symlink skips, all 105 mutants killed**, with 328 current
Python source hashes checked. Current rival retrieval claims remain untested.

An analysis SQL query itself exhausted memory. Preserve the failure; typed
struct-list expansion with bounded resources repairs the utility. This does
not count as a product performance gain. Next: finish the length audit, examine
paired losses, and continue the existing answer trial without retrying DONE
requests. Verdict remains PIVOT REQUIRED; the goal remains active.

### Cycle 28: reusable tokenizer interiors earn further testing

The previous whole-text piece cache lost. A new in-memory prototype prepares
stable-interior candidates once per source block and re-encodes joins during
selection. Its claimed boundary stability is a CONJECTURE limited to one
inspected tokenizer pipeline, not a theorem. Unsupported or missing prepared
inputs use upstream counting; the product default is unchanged.

All 3,860 declared ID/count attacks pass. The same public selector produces
identical outputs across 405 profiled cells, and a subsequent check verifies
all 2,700 actual admission counts with upstream whole-text encoding. Against
the stronger no-offset counter, median query time falls 177.28 to 26.26 ms at
2K and 553.96 to 67.47 ms at 8K. The result is under concurrent audit load and
does not establish better retrieval or answers. Preparing 3,451 unique blocks
costs 2.335 seconds and accounts for 23.44 MB of Python objects.

Exact counting-only checks at 100,303/250,478 tokens fall from 157.08/321.43 ms
to 8.39/16.79 ms. These are not whole-query latencies. Conditional preparation
crossover against the stronger counter is 16 queries at 2K, excluding startup,
persistence, updates and API economics. Current checks: 1,001 passed, two skips,
all 107 mutants killed; 331 source hashes match.

Keep this performance challenger; discard premature universal-exactness or
product speed claims. Next: broader corpus/Unicode attacks and compact,
integrity-checked persistence with incremental invalidation. Retrieval's frozen
length study is still under independent audit. Overall verdict PIVOT REQUIRED.
See CYCLE28_BOUNDARY_COMPILATION.md for scope, costs and failure paths.

The concurrent length audit subsequently completes all 3,996 records, 3,333
admission replays and 73,914 source-item checks. Weaker penalties repair the
traceback example but lose evidence elsewhere: at 2K, b=0 gains four/loses 14,
.25 gains four/loses seven and .5 gains three/loses three. b=1 gains three/loses
none at 2K but loses net two annotations at 512. Keep it only as a prospective
2K challenger; reject general parameter promotion. The broad hoped-for gain
from weakening normalization is unsupported. The reusable counting prototype
is this cycle's stronger measured result, with its persistence/proof limits open.

### Cycle 28: a stronger check loses; restricted barriers retain the gain

The whole-piece equality checker passes 3,860 replayed attacks and all 2,700
admission counts, but makes 2K queries slower: 176.09 to 228.96 ms. Discard it as
a runtime candidate. Two new preparation/counting defects were reproduced and
fixed before profiling, with permanent regression tests. Numeric-only barriers
provide a narrower conditional argument but cover only 974/3,451 unique blocks;
2K time improves modestly, 176.32 to 134.66 ms.

Complete ASCII-word barriers retain nearly all original speed: 182.49 to
26.62 ms at 2K and 550.75 to 70.20 ms at 8K against within-run no-offset
controls. The original prototype is still slightly faster at 2K/8K. The new
candidate supplies a narrower PROVED UNDER ASSUMPTIONS argument, not a generic
tokenizer theorem. Non-ASCII blocks use the numeric subcase. All 405 selections
agree, all 2,700 actual admission counts agree upstream, the original 3,860
attacks pass, and 44,816 finite small-alphabet cases pass. No retrieval or
target-answer improvement follows. Preparation takes 2.052 seconds with
22.20 MB of accounted objects; the 14-query preparation crossover at 2K
excludes startup, persistence, updates and API economics.

All 50 count-only scale observations pass. At 100,303 tokens the candidate
costs 8.95 ms versus 144.15 ms; at 250,478 it costs 50.23 versus 299.55 ms.
The slower 250K case exposes Unicode-wide fallback: 41 non-ASCII blocks account
for 38,306/47,452 standalone residual boundary tokens, especially emoji/spinner
tables. These are component sums, not whole-context sizes or causal timings.
Next hypothesis: safely delimited word barriers within mixed-Unicode blocks,
then compact persistence and incremental invalidation. This relaxation remains
CONJECTURE; no default changes or persisted format are claimed.

Canonical checks: 1,011 tests pass, two symlink tests skip, all 112 mutants are
killed and 336 Python source hashes match. Three more never-attempted NIM
payloads returned 503 after cooldown; the trial pauses at 141 attempts, with
94 answers, 46 HTTP 503s and one 429. All successful prompt counts reverify;
seven first-stage payloads remain never attempted. Answer accuracy remains N/A.
Overall PIVOT REQUIRED, goal active. See CYCLE28_COUNTER_BARRIERS.md.

### Cycle 28: compact counts persist and update without full recompilation

Delimited ASCII-word barriers within mixed-Unicode blocks pass 3,860 old cases,
90,480 declared finite stress cases, 405 public selections and 2,700 independently
counted admission trials. At 250,478 actual tokens, count-only time improves from
39.66 to 25.84 ms versus the whole-block ASCII restriction; at 100,303 it regresses
8.54 to 9.00 ms. Keep the narrower conditional argument, not a universal theorem.

Replace retained interior ID lists with counts: accounted objects fall from
23,274,103 to 4,255,187 bytes. An experimental 1,216,512-byte SQLite sidecar binds
records to source hashes, parent `.npk`, tokenizer and engine version. Trusted
receipts permit reuse; unknown caches recompile before admitting any records.
A real writer race was reproduced and repaired by retaining the exclusive lock
through receipt capture. Preserve its first faulty test harness separately.

The first storage profile declared the wrong cache setting and is excluded.
Corrected v2 produces 540 matching selections, independently reproduces all
2,700 admission counts, and improves warm 2K median time from 176.22 to 23.82 ms.
Trusted loading takes 73.38 ms; preparation takes 2,145.44 ms. Fresh-counter first
request is still slower, 1,022.77 vs 843.41 ms after initialization is included.
Nine real source-update trials match full cache rebuilds. One-file cache update
takes 21.20 ms versus 2,251.21 ms to rebuild; the source-plus-cache update still
costs 820.19 ms. Do not call this a 106x product improvement.

Current canonical checks: 1,031 pass, two symlink skips, 118/118 mutants killed,
341 source hashes verified. No new LIVE calls, retrieval gains or target-answer
advantage. Keep this optional research cache; core format/defaults are unchanged.
Next hypothesis: remove redundant tokenizer JSON serialization/decode at startup,
then challenge the counter on the larger SQLAlchemy corpus. The startup profile
finds 952.77 vs 672.80 ms median constructor cost, with extra JSON work accounting
for much of the gap. Overall PIVOT REQUIRED. See CYCLE28_PERSISTED_COUNT_CACHE.md.

### Cycle 28: direct metadata removes startup copying; SQLAlchemy limits the gain

Implement a separate compact-counter constructor using the loaded backend's small
metadata accessors. The single-byte-snapshot loader, dropout/padding/truncation
checks, normalizer/added-token gates, source counts and persistent format stay
the same. Fourteen new real-BPE regression cases pass. Discard the extra full
vocabulary serialization/JSON decode; retain the old constructor as a control.

New matched profiles cover 135 fresh and 1,215 warm observations on 153 library
files and 409 SQLAlchemy source/documentation files. Every selected result agrees,
and the upstream oracle checks all 8,100 actual admission trials. Available exact
compiled-block tokens per request are 559,083 and 2,342,422. This is broader
counting validation, not new answer or retrieval evidence.

Fresh 2K request medians improve from 1,019.57 to 750.44 ms and from 1,116.52 to
851.59 ms against the old cache constructor. The simpler no-offset controls take
834.02 and 889.83 ms. Three of 30 SQLAlchemy fresh pairs are slower than that
control. Warm 2K medians are 181.40 to 24.65 ms and 241.18 to 72.79 ms; changing
the constructor does not materially improve warm time over the old compact cache.
SQLAlchemy cache build costs 9,197.63 ms plus a 1,061.67 ms writer constructor.
Its 2K preparation crossover estimate is 61 warm queries, not an API-dollar or
whole-product break-even claim. Keep the first-request gain modest in reporting.

Canonical checks complete: 1,045 pass, two symlink skips, 120/120 mutants killed,
343 source hashes unchanged. All processes terminal. No new LIVE calls or default
format changes. Next hypothesis: hydrate only retrieved candidates' existing
count records while retaining trust/source checks and full-encoder fallback.
Retrieval remains the unresolved product bottleneck. Overall PIVOT REQUIRED;
see CYCLE28_LEAN_STARTUP.md. Goal remains active, this cycle is PROGRESS.

### Cycle 28: lazy count hydration trades warm overhead for startup and memory

The new reader verifies a private SQLite snapshot and hydrates source count
records by exact text hash only as candidates arrive. It checks parent identity
inside the selector's existing transaction and falls back to whole encoding for
missing records. Unknown caches do not get the trusted shortcut. Twelve real
BPE/SQLite regression cases pass; six new mutants catch hidden scans/compilation,
source aliasing, parent mismatch, unsupported-engine reuse and partial hydration.

Across both frozen corpora, 135 fresh and 1,620 warm selections match the previous
outputs, and all 8,100 actual admission counts match upstream. Fresh 2K medians
are 761.59 to 702.23 ms on the libraries and 858.67 to 743.40 ms on SQLAlchemy,
against eager count loading. One library fresh pair loses; all 30 SQLAlchemy
pairs improve. Warm 2K regresses 24.20 to 25.60 ms and 72.90 to 74.84 ms. Keep both
strategies rather than declaring a uniform latency win. SQLAlchemy retains
1,192,198 count-record bytes versus 12,794,267 eagerly, with separate SQLite and
backend memory costs. No retrieval or answer advantage follows.

After 6,022 seconds of verified cooldown, seven original never-attempted target
payloads yield five answers and two HTTP 503s. The independent 148-attempt report
verifies 99 prompt counts. All first-stage requests have been attempted, but
49 lack answers. Keep accuracy N/A. No original DONE payload was retried.
Next quality work is explicit transport-recovery lineage, preserving successful
responses as REPLAY; no overwrite of the original trial. Optional compiler/
runtime integration is the next system step, ahead of further counting polish.

Canonical suite: 1,057 pass, two symlink skips, 126/126 mutants killed, 345 source
hashes unchanged. All cycle processes terminal. Overall PIVOT REQUIRED; goal active,
turn PROGRESS. See CYCLE28_LAZY_COUNTS.md for costs, assumptions and limitations.

### Cycle 28: explicit transport recovery and answer-completeness audit

OBSERVE: all 148 first-stage requests were attempted but 49 had no answer.
IMPLEMENT: a separate hash-bound recovery stage archives original attempts,
reuses 99 answers with explicit LIVE-origin REPLAY records, and permits one new
attempt only for each known HTTP 429/503 failure. Frozen questions, oracle answers,
selection and generation settings cannot change. Unknown attempts cannot resume.
The answer reporter separates attempt completeness from answer completeness.

TEST/ATTACK: 1,087 tests pass, two symlink skips; all 132 mutants fail by test
assertion, including six new recovery/completeness mutants. All 347 bound Python
sources remain unchanged. A synthetic template-flag fixture error was corrected
before LIVE calls. MEASURE: 18 new attempts recover 12 answers and return six
503s. The second batch pauses after three consecutive errors. Cumulative calls
148 -> 166, returned unique answers 99 -> 111, missing 49 -> 37; 31 eligible
requests have not yet received their one recovery attempt. All 111 prompt counts
match. The original ledger remains unchanged.

BM25 has five correct of twelve answered; native CRISP seven of thirteen.
Paired BM25 versus CRISP: one win, two losses, seven ties, five missing pairs.
Accuracy stays N/A and no retrieval champion is promoted. A verified post-hoc
counterexample shows two wrong answers despite complete function and literal-table
exposure. KEEP lineage and completeness checks; DISCARD sufficiency claims from
mere exposure. NEXT: freeze a compact reference-evidence diagnostic to separate
omission from presentation/target-reasoning limits; resume never-retried eligible
requests only after inspecting the service pause and cooldown. No repeated
sampling of existing answers or failed retries. PIVOT REQUIRED; goal active.
Details: research/CYCLE28_TRANSPORT_RECOVERY.md.

### Cycle 28: compact source references fail to establish an advantage

OBSERVE: wrong target answers persisted despite complete function/table exposure.
HYPOTHESIS: manually seeded small functions, with or without direct module
declarations, might reduce distraction. IMPLEMENT: two frozen reference arms,
exact source spans and local prompt counts; ambiguous overload definitions require
an explicit source line. The24 unique requests represent30 observations because
six pairs share context. No generative optimizer calls or repository-code execution.

TEST/ATTACK: independent payload audit hashes155 files and recounts558,878 source
tokens per request. Reference contexts are96-1,383 tokens. Canonical suite1106 pass,
2 skips; all138 mutants killed,349 source hashes unchanged. Synthetic counterexamples
demonstrate omitted defaults, conditional bindings and transitive initializers.
Those limitations block automatic-runtime promotion. No full-dependency guarantee.

MEASURE: reference24 attempts ->19 answers +5 HTTP503s, all prompt deltas0.
Primary-only4 correct/13 answered; module bindings5/11. Neither beats native CRISP.
Primary-only can reach at most6/15 even if its two missing answers pass; CRISP
already has7 correct. Binding-vs-primary has2 wins/0 losses/8 ties/5 missing, with
five ties from identical payloads. This is weak post-hoc evidence, not graph proof.

After observed service recovery and a2,431-second cooldown,31 never-retried eligible
baseline payloads receive their single allowed recovery attempt:23 answers +8 HTTP503.
All49 eligible original failures have now been retried once. Aggregate recovery35
answers/14 failures; original-or-recovered134 returned answers from197 API attempts.
Original ledger and earlier reports remain intact. All134 prompt deltas0.
BM25 now has5/15 strict task successes. Native CRISP has7/14 answered, with one
missing; it wins this frozen comparison even if that answer fails. Field-weighted
lexical has7/12 answered, but no advantage over CRISP is established. Full accuracy
is N/A for incomplete arms. Later268 original budget-stage payloads remain unattempted.

Across reference and recovery this turn:55 new API attempts,42 returned responses;
returned responses are not automatically correct answers. A separate diagnostic
finds one class-prefix-plus-extra-message failure per reference arm and leaves all
strict grades unchanged. Not every strict failure implies wrong reasoning.

KEEP audited counterexamples and evidence infrastructure. DISCARD the assumption
that primary-only context is a superior automatic optimizer. No champion, core
schema or runtime change is promoted. NEXT: distinguish dependency incompleteness
from target reasoning/formatting on fully specified executable cases, using a
separately frozen target configuration if needed; do not attribute target changes
to NeuralPack gains. PIVOT REQUIRED; goal active, turn PROGRESS. See
research/CYCLE28_REFERENCE_EVIDENCE.md.

## Cycle 28 continuation: complete-source controls and typed audit identity

EMPIRICAL: a new16-call target diagnostic returns all16 answers. With identical
complete programs, questions and8,192 output ceilings, direct Nemotron passes6/8
and its low-effort thinking setting passes8/8. Both average235.25 input tokens;
output15.375 vs136.5 tokens, target latency2.944 vs7.640 seconds. All16 prompt
deltas are0. Direct mistakes generator reversal and a supplied subtraction;
both failures are valid JSON and cannot be caused by retrieval omissions.
The contexts are only46–313 tokens each; this is not a retrieval or scale claim.

Re-audited the existing45-call target profile without repeating it. Compared
with recovered direct answers on identical source, BM25 has2 wins/0 losses/6
ties/7 missing and CRISP4/0/5/6 for the profile. Those historical settings change
multiple controls together and have missing responses. No NeuralPack gain follows.

Two attacks found that native Python equality accepted Boolean-to-number answer
changes and integer-to-float count changes in the new trial validator. Both
regressions failed before repair; strict JSON identity now rejects them. The
saved trial re-audits with unchanged grades and no extra target calls.

KEEP executable complete-source controls and typed evidence checks. DISCARD
complete-source-as-correct-answer guarantees. No product champion promoted.
NEXT: use complete-source controls on new repository tasks under identical
target settings, then compare retrieval at matched budgets. CRISP still wins
the original frozen comparison. PIVOT REQUIRED; goal active, turn PROGRESS.
Details: research/CYCLE28_COMPLETE_PROGRAM_CONTROLS.md.

Final checks for that continuation:1,129 pass,2 skip,141/141 mutants killed,
351 source hashes unchanged. The first mutation invocation hit a60-second
harness timeout; narrowing two mutation selectors to their specific assertion
cases and running in a fresh process completes all141 without changing the
kill criterion. The full23-case fixture suite remains intact. All16 LIVE
requests are terminal with answers. No product schema or default changed.

## Cycle 28 continuation: shared response/replay identity

EMPIRICAL:11 new regressions reproduce type substitutions accepted by shared
response, replay, parent-ledger and recovery-plan validators. Strict JSON
identity and integer policy-version validation repair these checks. The focused
suite passes60; full1,140 pass/2 skip;144/144 mutants are assertion-killed.
Full and mutation stages run separately on identical351 source hashes.

New local audit revalidates381 record files,233 unique payloads,282 historical
API attempts and197 successful LIVE responses across the explicitly listed
runs. All recorded grades are unchanged. No new target call. Paired audit
timings over197 valid records rise from0.144 to1.156 ms per batch; keep the
additional1.012 ms for correctness. This is not runtime or model latency.

KEEP typed identity and11 counterexamples. DISCARD native equality as record
identity. CRISP remains ahead in the frozen repository comparison. No retrieval
champion is promoted. NEXT: return to stronger seed evaluation on new repository
tasks with the same target settings and paired complete-source controls.
PIVOT REQUIRED; goal active, turn PROGRESS. See
research/CYCLE28_SHARED_RECORD_IDENTITY.md.

## Cycle 29: explicit compact source views

EMPIRICAL: field seeds find required source in241/246 candidate pools, while
only205 survive the2,048-token selection. Tested exact source views that mark
docstring omissions, with full, compact-first and compact-on-rejection policies.
All5,994 selections at512/2,048/8,192 caps complete. Raw controls reproduce;
the independent audit checks every final payload and8,508 sampled proposal counts.

At2,048, field source checks205→211 and frozen CRISP225→233 with compaction.
But field primary non-doc implementation exposure on15 behavior questions falls
10→9; documentation exposure also falls sharply. CRISP compaction loses a source
check at8,192. This is not answer accuracy or a win over the rival.

FALSIFIED by permanent fixtures: docstrings are always safe to drop; smaller
ranked blocks cannot displace required implementation evidence. Ten regressions
cover exact spans, Unicode, inline statements, explicit omissions, markers in
the token cap, empty seeds, unchanged queries and request isolation.

The initial full-retokenization trial stops at292/5,994; every saved output
matches the completed prepared-counter trial. A separate72-pair profile measures
existing counter reuse at2,048:374.75→10.80 ms median packing cost, excluding
retrieval/compilation/target inference, plus2,412 ms one-time count preparation.
The speed gain is not novel retrieval or product end-to-end performance.

KEEP explicit source-view diagnostics and counter reuse. DISCARD automatic
docstring compaction as a product default. Full1,150 pass/2 skip; final mutation
stage recorded below on completion. No live calls, default changes or promotion.
NEXT: new repository behavior questions with definition-complete evidence,
captured-default/configuration counterexamples, matched caps and fixed target
settings. PIVOT REQUIRED; broader goal active. See research/CYCLE29_SOURCE_VIEWS.md.

Final verification:1,150 tests pass,2 explicit symlink skips,147/147 mutants
assertion-killed. Both stages bind identical355 Python sources. The original
critical mutants remain killed; no harness timeout or import error counts as a
kill. Current prefix:cycle29-final-canonical. All cycle29 processes are terminal.

## Cycle 30: batched index deletion and bounded-parameter updates

EMPIRICAL: `_drop_file` previously gathered block IDs in Python and generated an
unbounded SQL IN clause. Under `SQLITE_LIMIT_VARIABLE_NUMBER = 32`, updating or
deleting any file with >= 33 blocks crashed with `sqlite3.OperationalError: too
many SQL variables`. Furthermore, because FTS5's `block_id` column is UNINDEXED,
executing per-file deletes in a loop forced SQLite to scan the entire FTS5 index
N times, creating O(N * |lexical|) quadratic work on multi-file updates.
An initial audit check in `update_batch_eval` also used an unindexed LEFT JOIN
against `lexical`, consuming 110,000+ progress ticks per 1,000 rows (~160 ms).
Replacing it with a NOT IN subquery dropped the check to 250 ticks (~0.5 ms),
a 300x audit speedup.

IMPLEMENT: `_drop_lexical` creates a temporary table `npk_obsolete_files`
and removes all obsolete postings in a single joined scan, keeping parameter
counts constant. `_drop_file` now uses a subquery with exactly 1 parameter and
skips redundant lexical scans when called within update loops. The experimental
`block_reuse.py` adapter was adjusted to retain un-reused block cleanup semantics.

TEST/ATTACK: Three new permanent regression tests verify bounded parameter usage
under artificial SQL variable limits, verify lexical index consistency when FTS
rowids differ from block IDs, and enforce a linear opcode budget on index audits.
The independent auditor verified all 10,702,770 FTS5 postings, token positions,
and document lengths across 30 conditions (champion, candidate, and fresh rebuild),
plus 300 3-way query response comparisons across 5 query families and 2 budgets.
All returned selections, spans, token counts, and fallback flags matched identically.

MEASURE: In-memory isolated bytecode operations on a 1,000-file synthetic corpus
showed SQLite progress ticks dropping from 1,037,807 to 62,637 (a 16.57x reduction)
and wall time from 1,284 ms to 217 ms (5.91x faster). On 100-file deletion, ticks
dropped from 191,518 to 8,366 (a 22.89x reduction) and wall time from 236 ms to
24.5 ms (9.64x faster). End-to-end full update on 1,000 files dropped from 11,080 ms
to 8,303 ms (1.33x speedup), with single-file edits remaining dominated by directory
walking and hashing in `scan_source` (~2,000 ms).

KEEP batched index deletion and bounded-parameter SQL in core `npk/pack/compile.py`.
DISCARD unbounded positional IN clauses and repeated per-file FTS scans.
Full suite: 1,151 passed, 22 symlink skips. All 150/150 mutants assertion-killed.
Scope: 365 Python files. Prefix: cycle30-final-canonical. 0 generative model calls.
NEXT: Profile and accelerate source tree scanning and change detection without
compromising content-hash invalidation or secret screening. PIVOT REQUIRED;
active goal in progress. See research/CYCLE30_UPDATE_BATCHING.md.

## Cycle 31: connection hardening, zero-legacy query boundaries, and query throughput

EMPIRICAL: `npk/pack/select.py` previously imported `content_terms` from `..context.info_gain`,
dragging legacy Product B modules (`info_gain`, `bm25`, `analyzer`) into memory on the first query.
`npk/pack/format.py::connect()` lacked `trusted_schema=OFF`, `enable_load_extension(False)`,
and `query_only=ON` on read-only connections. `_available_tokens` fetched all block strings into
Python to compute character lengths, and `PackSelector.select()` opened and closed a fresh SQLite
connection on every query call. In `scan_source`, `os.walk` sorted filenames but left dirnames unsorted.

IMPLEMENT: Self-contained `STOPWORDS`, `_query_terms`, and `_content_terms` in `npk/pack/select.py`.
Added connection security hardening in `format.py::connect()`. Replaced the Python string loop in
`_available_tokens` with SQL aggregate `SELECT count(*), coalesce(sum(length(text)), 0) FROM blocks`.
Added context management (`__enter__`, `__exit__`, `close()`) to `PackSelector` with snapshot
transaction isolation (`BEGIN` ... `ROLLBACK`). Sorted `dirnames` in `scan_source`.

TEST/ATTACK: Four new regression tests verify SQL vs Python token count identity across Unicode,
PRAGMA enforcement and write blocking on read connections, process-level module isolation
(0 `npk.context` modules imported), and connection reuse with clean lock release on context exit.
Four new mutation tripwires verify detection of unclosed connections, disabled security PRAGMAs,
and zeroed token counts.

MEASURE: Process isolation confirmed 0 `npk.context` modules imported during query. Multi-query
throughput on Click 8.5.0 improved 1.99x (4.02 ms -> 2.02 ms median), with tight loops reaching
0.15-0.32 ms/query (4.6-18x faster). `_available_tokens` improved from 4.58 ms to 3.30 ms (1.39x faster)
with zero string allocations. All 20 2-way query response checks matched identically.

KEEP self-contained query terms, SQLite defense-in-depth, SQL token aggregation, and
context-managed `PackSelector`. DISCARD cross-module legacy context imports and unbounded string loops.
Full suite: 1,155 passed, 22 symlink skips. All 154/154 mutants assertion-killed.
Scope: 367 Python files. Prefix: cycle31-final-canonical. 0 generative model calls.
NEXT: Investigate symbol index reference noise and artifact storage footprint.
PIVOT REQUIRED; active goal in progress. See research/CYCLE31_RUNTIME_HARDENING.md.

## Cycle 32: language-aware symbol indexing and noise elimination

EMPIRICAL: `symbols` previously consumed 47.2% of the entire artifact (6.5 MB out of
13.86 MB on Click 8.5.0), with 96.1% of rows (107,883 / 112,259) being non-definition
references. `IDENT_RE` matched every 3+ letter word indiscriminately across code and
prose. Python keywords (`def`, `return`, `for`, `class`, `None`, `True`, `False`) and
English stopwords (`the`, `and`, `with`, `that`) were the most frequent "symbols" in the
artifact. In hybrid retrieval, changelog entries in `CHANGES.md` out-ranked source code
definitions purely from English word repetition.

IMPLEMENT: Added language awareness to `_extract_symbols(block, language)`. Excluded
Python keywords (`keyword.iskeyword`) and stopwords from code reference extraction.
Prose files (`markdown`, `rst`, `text`, `toml`) extract definitions (e.g. section headings)
but skip emitting bare prose words as symbol references, relying on FTS5 `lexical` for prose.
All definitions (`is_def = 1`) remain 100% preserved.

TEST/ATTACK: Four new regression tests verify keyword exclusion, prose reference omission,
100% definition preservation, and incremental update symbol parity. Two new mutation
tripwires catch keyword and prose guard bypasses. All 40 query comparisons verified;
hybrid queries on code definitions (`parameter`, `ExitStack`) now prioritize real source
implementations over changelogs.

MEASURE: Artifact size on Click 8.5.0 dropped from 13.86 MB to 10.94 MB (-21.1% on disk).
Total symbol rows dropped from 112,259 to 60,643 (-46.0%), eliminating 51,616 noise rows
and saving nearly 3 MB of B-tree page storage. 100% of definitions preserved (4,376/4,376).
Compile time improved from 1,650 ms to 1,455 ms.

KEEP language-aware symbol extraction and keyword/prose reference filtering.
DISCARD indexing language keywords and prose bare-words in `symbols`.
Full suite: 1,159 passed, 22 symlink skips. All 156/156 mutants assertion-killed.
Scope: 369 Python files. Prefix: cycle32-final-canonical. 0 generative model calls.
NEXT: Investigate DML call amplification in `_write_file_blocks` and FTS tie-breaking limits.
PIVOT REQUIRED; active goal in progress. See research/CYCLE32_SYMBOL_INDEX_CLEANLINESS.md.

## Cycle 33: per-file batched DML insertion and tie-breaking boundary limits

EMPIRICAL: In `_write_file_blocks`, `lexical`, `symbols`, and `assignments` rows were
inserted individually per block, generating over 4,420 separate database calls across
Click's 2,213 blocks. Profiling showed 1,819 ms spent in block insertion. An attempt to
push `LIMIT` into an inner FTS5 subquery in `_lexical_channel` produced a 3.55x query
speedup on typical queries, but FALSIFIED tie-breaking correctness on boundary score
ties: `test_equal_scores_use_source_order_after_an_update` caught that FTS5's internal
heap cut off candidates based on insertion history before the `f.path` tie-breaker could run.
The subquery pushdown was discarded.

IMPLEMENT: Batched secondary table insertions in `_write_file_blocks`. `blocks` continues
sequential rowid generation, while `lexical`, `symbols`, and `assignments` rows are
accumulated across all blocks in each file and inserted using single `executemany()` calls.

TEST/ATTACK: Two new regression tests verify batched `executemany` invocation and exact
row alignment across `blocks`, `lexical`, `symbols`, and `assignments`. A new mutation
tripwire catches lexical batch omissions. The Cycle 8 tie-breaking regression suite
passes 100% without divergence.

MEASURE: Block insertion time dropped from 1,819.17 ms to 1,468.80 ms (1.24x speedup,
saving 350 ms per compile). Database calls for secondary indexing dropped 13x.
All table row counts and contents match 100% identically across all tables.

KEEP per-file batched DML insertion for `lexical`, `symbols`, and `assignments`.
DISCARD per-block `executemany` calls and naive subquery `LIMIT` pushdown in FTS5.
Full suite: 1,161 passed, 22 symlink skips. All 157/157 mutants assertion-killed.
Scope: 375 Python files. Prefix: cycle33-final-canonical. 0 generative model calls.
NEXT: Investigate stat-fingerprinted scanning in `update_pack` and `npk update --quick`.
PIVOT REQUIRED; active goal in progress. See research/CYCLE33_BATCHED_FILE_INSERTS.md.

## Cycle 34: stat-fingerprinted fast scanning for developer iteration

EMPIRICAL: `scan_source` previously re-read, bounds-checked, UTF-8 decoded, and
SHA-256 hashed every file from disk on every update call, consuming 1,235 ms on 1,000 files
even when 99.9% of files were unchanged. The v5 SQLite `files` schema already stores
`mtime_ns` and `size`. However, unconditionally skipping reads broke concurrent read-race
detection in `tests/test_source_boundary.py` (`test_file_change_during_read_cannot_publish_inconsistent_metadata`).

IMPLEMENT: Added optional stat-fingerprinting via `update_pack(pack, source, quick=True)`
and CLI flag `npk update --quick`. `update_pack` reads verified file records under `BEGIN IMMEDIATE`
and passes `known_files` to `scan_source`. When `quick=True`, files matching `(size, mtime_ns)`
skip reading and hashing. When `quick=False` (default), strict cryptographic content-hash
scanning runs in full.

TEST/ATTACK: Five new tests verify zero disk reads on untouched files under `quick=True`,
proper re-indexing of modified files, byte-identical Merkle roots between quick and strict
updates, CLI `--quick` flag execution, and boolean type validation. A new mutation tripwire
catches bypass of the stat fingerprint cache.

MEASURE: Source scanning on Click 8.5.0 dropped from 80.07 ms to 37.77 ms (2.12x faster).
On 1,000 files, scanning dropped from 1,235.25 ms to 702.34 ms (1.76x faster, saving 532 ms
per update). Twin artifacts updated with `quick=True` and `quick=False` produced byte-identical
`actual_root_sha256` digests and identical query evidence.

KEEP optional stat-fingerprinted fast updates (`quick=True`, `npk update --quick`).
DISCARD replacing cryptographic content-hash scanning as the default.
Full suite: 1,166 passed, 22 symlink skips. All 158/158 mutants assertion-killed.
Scope: 377 Python files. Prefix: cycle34-final-canonical. 0 generative model calls.
NEXT: Investigate query result caching and canonical prompt ordering.
PIVOT REQUIRED; active goal in progress. See research/CYCLE34_STAT_FINGERPRINT_UPDATES.md.

## Cycle 35: in-memory query result caching and canonical prompt ordering

EMPIRICAL: Repeated queries during multi-turn agent sessions or test loops spent 4-6 ms
re-executing FTS search, block hydration, and risk calculation. Furthermore, default
context emission joined evidence in greedy relevance order, scattering blocks from the
same file and fragmenting prompt prefixes across related queries, preventing LLM provider
prefix-cache hits.

IMPLEMENT: Added an in-memory LRU query result cache to `PackSelector`, keyed by
`(root_sha256, query, budget, ...)` to ensure automatic invalidation on artifact update.
Added `context_text(order="canonical")` to `Selection`, sorting evidence by `(path, span)`
before joining to keep code from the same file contiguous for prefix-stable caching.

TEST/ATTACK: Five new regression tests verify sub-millisecond cache hits, cache invalidation
after file updates, LRU size bounding, and canonical vs relevance context ordering.
Two new mutation tripwires catch stale cache keying and unsorted canonical ordering.

MEASURE: Repeated query latency on Click 8.5.0 dropped from 5.98 ms to 0.87 ms (unmanaged)
and 0.004 ms (managed, ~500-800x faster). All 10 ordering checks verified that canonical
order groups source files contiguously while default relevance order remains 100% unchanged.

KEEP in-memory query caching and canonical context ordering in `npk/pack/select.py`.
DISCARD persistent cross-process query caches.
Full suite: 1,171 passed, 22 symlink skips. All 160/160 mutants assertion-killed.
Scope: 379 Python files. Prefix: cycle35-final-canonical. 0 generative model calls.
NEXT: Investigate FTS5 external content and root digest pruning as a v6 format candidate.
PIVOT REQUIRED; active goal in progress. See research/CYCLE35_QUERY_CACHE_AND_CANONICAL_ORDERING.md.

## Cycle 37: v8 external-content FTS5, definition-only symbols, and adversarial closure

EMPIRICAL: The v7 contentless-delete FTS5 implementation had a correctness hole
that ordinary SQLite and FTS5 integrity checks did not expose. After a changed
block was deleted and reinserted, BM25 document-frequency normalization differed
from a clean rebuild. A direct SQLite 3.53.1 probe reproduced the drift: an
otherwise identical query moved from a score near `-0.000001` on the fresh build
to about `-0.397` after the incremental update. The final v7 audit therefore did
not qualify as a stable incremental artifact.

IMPLEMENT: Bumped the public format to v8 and the compiler to 8.0. The lexical
table is now external-content FTS5 over `blocks`, with the block body remaining
authoritative and normalized body/name/path values maintained in postings. The
schema stores normalized path metadata in `blocks.path`, and updates issue
source-aware FTS5 delete rows before removing old blocks. This avoids a duplicate
stored body and keeps the block ID as the verified FTS row ID. Old packs require
explicit recompilation.

IMPLEMENT: Full verification now runs the FTS5 internal integrity command and,
when ordinary checks are clean, builds a rollback-only temporary contentless FTS5
index from `blocks` and `files`. It compares actual and expected instance
postings by term, document, column, and offset. This catches an internally valid
but source-inconsistent posting tree even when its self-declared root has been
rewritten. The verifier test was strengthened to require full file-leaf
recomputation, so cached sealing cannot masquerade as full verification.

KEEP: The A1/A2 fielded BM25 and structural naming work moved into the product
path in the v7 predecessor and remains the retrieval baseline. A4 definition-only
symbols also stays promoted: the frozen corpus went from 84,312 persisted symbols
to 5,871, symbol storage from 5,120,000 bytes to 446,464 bytes, and pack size from
9,662,464 bytes to 4,988,928 bytes while all 207 field-only selection cases stayed
exact. The v8 pack on the same initial corpus is 5,066,752 bytes, a 1.56% increase
accepted for stable incremental FTS semantics.

TEST/ATTACK: Added exact BM25 score parity against a fresh rebuild after a
one-file update, resealed bogus-posting and document-length rejection, direct
block-name mutation classification, and a full-leaf spy for the verifier. The final audit compiled
153 files and 3,513 initial blocks, ran 15 deterministic query probes, performed
strict no-op and one-file updates, built a fresh changed-source pack, and found
equal logical tables and query payloads. Updated and fresh SQLite byte streams
remain allowed to differ because incremental row history and IDs differ. The
default runtime made zero generative calls.

MEASURE: The strict no-op update scanned 153 files, skipped all 153, preserved
bytes, and took 93.3 ms. The one-file update indexed one file, skipped 152,
hashed one integrity leaf, and took 203.1 ms. Full verification of the
3,513-block frozen pack measured about 0.018 seconds before the source-parity
check and about 0.68 seconds with postings, document lengths, and configuration
parity in the refreshed local median run. This cost is paid
at artifact acceptance and is absent from query-time selection.

REJECT: B1 knapsack scoring fell from fielded retention 162/205/229 to 28/108/203
at 512/2,048/8,192 tokens; the fields-plus-relations arm fell from 175/223/239 to
42/131/219. B2 coverage weighting lost measured candidate coverage and did not
recover target `B-b8c5ec3852`. A9 canonical rank added 0.0879 ms median without
an established semantic benefit. The 8 KiB page-size trial saved 0.66% bytes but
slowed queries. The SQLite cache-pragmas trial had 1,440 paired exact queries,
median delta -0.00745 ms and tied p95, so only cheap settings remain and no large
speedup claim is made.

ATTACK RESULT: The first complete mutation rerun exposed a surviving
`cached_verification` mutant because the old test checked only the final boolean.
The test was changed to spy on `full_file_digests`; a focused rerun killed that
mutant, and the complete rerun killed all 159/159 mutants with no harness errors.
The final full suite passed 1,227 tests with 22 explicit symlink skips in 176.17
seconds. An earlier mutation output produced while its test source was changing
was discarded as invalid evidence and was not used for this result.

PROMOTE: v8 external-content FTS5, source-aware update deletion, source-derived
posting, document-length, and configuration verification, definition-only symbols,
and the existing deterministic
fielded retrieval baseline.

DISCARD: Contentless-delete v7 as an update contract, B1 knapsack allocation,
B2 coverage weighting, A9 precomputed canonical rank, page-size promotion, and
the claim that connection pragmas produced a material speedup.

NEXT: Use a genuinely held-out repository with an executable answer oracle to
test allocation. Keep v8 fielded BM25 and conservative relation seeds fixed.
Report candidate coverage, retained source coverage, exact context identity,
latency, memory, and zero-generative behavior together. Start with adversarial
cases containing one long distractor, many short partial matches, repeated names,
and a correct low-score neighboring block. Do not promote an allocator that wins
one curve while losing source coverage or fixed latency.

Evidence: `research/CYCLE37_ALPHAEVOLVE.md`,
`experiments/results/cycle37-final-audit-v5/report.json`,
`experiments/results/cycle37-full-v8-final.xml`, and
`experiments/results/cycle37-contract-mutations-v7.json`.

---

## Cycle 38 — target-model validation and hybrid retrieval

OBSERVE: The v8 compiler and runtime already had a complete incremental/fresh
parity audit, but answer quality remained unmeasured on a current executable
oracle. The repository evaluator supplied 12 exact-answer urllib3 2.7.0 behavior
questions. At 2,000 selected tokens, member BM25 covered 58.33% of required span
groups and retained every required span on 5/12 tasks; body-window BM25 covered
34.72% and retained every required span on 2/12.

HYPOTHESIZE: The authorized NIM key could turn the source-coverage comparison into
an answer-quality measurement. A local MiniLM hybrid might recover missing context.
The relation seed channel might be a distractor on this behavior oracle, and a
larger candidate pool might expose useful low-ranked blocks.

MEASURE: The primary Llama NIM run made 48 sequential calls across no-context,
full-context, body-window, and member BM25 arms. All transports succeeded. Exact
answers were 0/12 for no context, 0/12 for full context, 0/12 for body-window,
and 3/12 for member BM25. The member arm's successful tasks were
`retry_after_eligibility`, `server_delay_cap`, and `redirect_header_scope`.
The full-context control consumed 985,569 provider tokens, while the member arm
consumed 20,315; these are provider usage measurements, not dollar claims.

ATTACK: Disabling relations produced 62.5% required-span coverage, 5/12 all-span
tasks, and 4/12 exact Llama answers on a paired 12-call comparison, versus 58.33%,
5/12, and 3/12 with relations enabled. The older 246-question replay measured
relations as beneficial (223/246 versus 205/246), so the default was left unchanged
and the conflict was recorded as a multi-repository follow-up. Candidate limits
30/60/120/240/480 all produced 58.33% coverage and 5/12 all-span tasks; larger
limits only increased latency and were discarded.

The hybrid MiniLM arm took 15.26 seconds to compile 657 embeddings and produced a
2,486,272-byte artifact versus 1,138,688 bytes for member BM25. At 2,000 tokens it
covered 53.47% and 2/12 all-span tasks versus 58.33% and 5/12 for member BM25;
at 4,000 tokens it covered 77.78% and 8/12 versus 76.39% and 7/12. Hybrid remains
explicitly optional and was not promoted as a default.

REJECT: Do not claim a general answer-quality winner from this single developer-known
12-task oracle. Four Nemotron canary calls exhausted the 384-token output cap, and
three of four DeepSeek canary calls timed out, so neither canary is a retrieval
comparison. The live results and model/transport limitations are recorded in
`research/CYCLE38_MODEL_AND_HYBRID_EVAL.md` and
`experiments/results/cycle38-model-hybrid-eval-v1.json`.

KEEP: v8 external-content FTS5, source-aware deletion, source-derived integrity
parity, definition-only symbols, fielded BM25, and optional hybrid retrieval.
The default compiler and selector remain zero-generative; NIM is used only by the
explicit answer evaluator.

NEXT: Run a paired answer study on at least three independently selected
repositories with a stable structured-output model and fixed timeouts. Compare
both relation settings and hybrid retrieval using answer outcomes, retained spans,
candidate coverage, selected tokens, latency, memory, provider usage, and v8
verification together before changing a runtime default.

## Cycle 39 — an external benchmark, and the changes it justified

OBSERVE: Earlier cycles judged NeuralPack on questions its developers wrote (the
CRISP needles and 12-15 behavior oracles), whose data are not in this snapshot. There
was no external, held-out measure of context selection, so no promotion could be
trusted. The first profile of the product on real repositories found that 46 of 103
SWE-bench snapshots could not be compiled at all: one unindexable file aborted the
build.

HYPOTHESIZE: SWE-bench issues are queries nobody at NeuralPack wrote, and the
maintainers' fixes mark what must be found. A pinned, held-out benchmark on them
(NPK-Bench), scored on three targets at once (the fix, the regression-test site and
topical documentation), makes improvements measurable and gaming visible.

MEASURE: NPK-Bench (`benchmarks/npkbench/`) covers dev (SWE-bench Lite, 300 issues),
dev-fast (103), held-out (Verified minus Lite, 407) and conversation memory
(LongMemEval-S, 470 questions). Every dataset is pinned by revision and SHA-256. It
reports paired-bootstrap comparisons, and every experiment is recorded in
`experiments/npkbench/EXPERIMENTS.jsonl`. The decision rule was declared in advance:
a frequency-weighted utility `d_fix + 0.99 d_tests + 0.087 d_docs` must stay
non-negative at every budget, with a significant gain on the addressed target, then
be confirmed once on held-out. Kept, each on that evidence:
- E001: one cached AST parse per file; 1.49x faster compiles, identical artifacts.
- E004: skip-and-report unindexable never-indexed files, taking blocked snapshots
  from 46/103 to 0.
- E002: the definition channel; held-out fix recall up 5.7 to 10.3 points at
  1K-16K.
- E005c: top-block trimming; +13.9 / +7.3 points at 512 / 1K.
- E014: string-prefix scanning; one-file updates 1.5-2.5x faster.
- E017: an opt-in context map; a 25% map share at 2K locates as much as full text
  at 4K.
Dev-fast fix recall went from 0.209 / 0.301 / 0.408 / 0.474 / 0.544 to
0.358 / 0.440 / 0.479 / 0.523 / 0.607 at 1K-16K.

ATTACK: Scoring every selection on tests and documentation exposed four wins that
were transfers:
- Role priors (E006) raised fix recall by collapsing tests.
- Portfolios (E008) moved recall between targets.
- A learned re-ranker (E011) rediscovered the role prior.
- Density ordering for conversations (M002) was a role prior in disguise.
Once built correctly (docs-3), the documentation target showed that demotion costs
14-40 docs points. Its first two constructions were wrong (a mass-reformat commit,
branch-integration merges) and were rebuilt before any decision used them. A
profiler overstated a parse-cache win (E001b), and paired timing rejected it.

REJECT:
- Structural expansions: E003 file aggregation, E005 coarse-to-fine emission for
  every block, E009 callee expansion, E013 sibling collapse.
- Dense re-ranking fused at equal weight (E012): -9 to -11 fix points at 1-2K.
- Diversity, density and paragraph units on memory (M001-M003).
- Skipping per-file `realpath` in scans: a test pins resolution-before-read, which
  matters on Windows.

KEEP: The six changes above, their CLI parity flags (`--no-definitions`,
`--no-trim`, `--strict`, `--map-share`), and NPK-Bench itself. Dense similarity
wins on conversation memory (M004: +6 to +8 points at 2K-8K). The product-form
test mate (E016b: tests +7 points at 2K, fix unchanged within noise) awaits
held-out confirmation.

NEXT: See `NEXT_STEPS.md`. In order:
- Held-out confirmation of E016b and E005c (H001).
- The documentation channel (E018) and prose/code query segmentation (E022).
- Import-aware entity extraction (E023).
- Dense as one fusion channel (E012b) for code.
- The shipped hybrid mode on memory (M006).

# Independent Hostile Audit of NeuralPack

**Audit date:** 2026-09-05
**Auditor:** Independent reviewer (adversarial peer-review posture)
**Repo state audited:** commit `831f2e1`, branch `codex/neuralpack-research`, working tree clean
**Stance:** No prior report, benchmark, theorem, or test result was assumed correct. Every numeric
claim was traced to raw artifacts or re-derived by independent code.

---

## 0. Executive summary

The engineering scaffolding is real: the package imports, the CLI exists, provider adapters exist,
181 tests pass, and the pipeline does measurably reduce token counts on lexically-easy retrieval
tasks. Beyond that, the headline claims do not survive scrutiny.

The three most serious findings:

1. **The optimizer can silently delete 100% of the context, ship a bare question to the model, and
   report it as a 98.84% token reduction** with `fallback_to_raw: False` and `quality_risk: 0.015`.
   The advertised "safety fallback" does not detect total context destruction. Token reduction is
   the optimizer's objective, and destroying context maximizes it.
2. **The "sealed 200-task benchmark" reports 5.0% accuracy for every arm** (baseline, BM25, dense,
   hybrid RRF, NeuralPack) because it scores a mock provider that echoes the first 30 characters of
   the prompt. It measures nothing about answer quality. The MSC holdout runs report **0.0% accuracy
   with "100% quality retention"** — an artifact of a hardcoded divide-by-zero branch.
3. **The real NVIDIA API key from `.env` is committed to git history** in `tests/test_secrets.py`,
   and the secret-scanning test that should catch it swallows its own assertion.

Two claims are outright false as stated: "100% critical-context recall" (counterexample found) and
"sub-millisecond planning overhead" (measured 128 ms at 100K tokens). One theorem is false as
written. Mutation testing shows the test suite fails to detect defects in exactly the three
components that constitute the project's novelty claims.

**Final classification: UNSUBSTANTIATED.** See §12.

---

## 1. Claim-by-claim ledger

Status vocabulary: **VERIFIED** (reproduced independently), **PARTIAL** (true under narrower
conditions than claimed), **UNSUPPORTED** (no adequate evidence), **FALSE** (contradicted by
evidence I produced).

| # | Claim | Source | Evidence found | Reproduced? | Status |
|---|---|---|---|---|---|
| 1 | Provider-independent architecture | `npk/providers/` | 7 adapters + registry, unit-tested | Yes — imports and dispatches | **VERIFIED** |
| 2 | 181 tests pass | test suite | `181 passed, 1 skipped in 11.05s` | Yes | **VERIFIED** (but see §5 — suite is weak) |
| 3 | Token reduction on lexical lookup tasks | benchmarks | 99.96% reduction at 100K with needle retained | Yes | **VERIFIED** (narrow: exact-identifier queries) |
| 4 | "77.73% token reduction on live 10K+ context" | commit `a6832f2`, `holdout-live-code` | Per-task baseline = **3,510–3,516 tokens**, not 10K+ | Reduction yes; "10K+ context" no | **FALSE** (context size misstated) |
| 5 | "100% task accuracy" on sealed 200 suite | `sealed-200-001/summary.json` | `neuralpack_accuracy: 5.0` — and *every* arm is 5.0 | Yes, reproduced | **FALSE** |
| 6 | "100% quality retention" (MSC holdouts) | `holdout-msc-00{1,2,3}` | `baseline_accuracy: 0.0`, `neuralpack_accuracy: 0.0`, retention printed as 100.0 | Yes | **FALSE** (artifact of hardcoded branch) |
| 7 | "100% critical-context recall" | Theorem 3 + reports | Counterexample: needle lost at every depth (§4.3) | Falsified | **FALSE** |
| 8 | Safety fallback to raw context | `npk/planner.py`, CLAIM_AUDIT #10 "VERIFIED" | Total context deletion → `fallback_to_raw: False` | Falsified | **FALSE** |
| 9 | "Sub-millisecond planning overhead" | `profiler_summary.json` | Measured on **710-token** context; 128 ms at 100K | Falsified at scale | **FALSE** (as generalized) |
| 10 | Component ablation study | `component_ablation.json` | 2 of 6 rows toggle dead flags (§3.1) | Rows are void | **UNSUPPORTED** |
| 11 | Cost-based optimizer with quality constraints | `npk/plan.py`, `planner.py` | `quality_risk` is hardcoded `0.0/0.001/0.015/0.045` | — | **UNSUPPORTED** |
| 12 | Verified cost/pricing model | `npk/cost.py` | `gpt-4o-mini` resolves to **gpt-4o pricing (16.7× overcharge)**; unverifiable model entries | Falsified | **FALSE** |
| 13 | Automated secret scanning ("3 tests passing") | `tests/test_secrets.py` | Real key present; scanner swallows its own `AssertionError` | Falsified | **FALSE** |
| 14 | Superiority over BM25 / dense / hybrid RAG | sealed 200 + holdout | All arms tie at 5.0% (meaningless); matched-budget probe ties BM25 2/3 | Not reproduced | **UNSUPPORTED** |
| 15 | NP-completeness of MSC | `research/math/theorems.md` | NP-membership never established | Partially | **PARTIAL** — see math audit |
| 16 | Impossibility of independent Top-K | Theorem 2 | Counterexamples found | Falsified as written | **FALSE** — see math audit |
| 17 | "Exact Pareto knee" | reports | No frontier enumeration exists | — | **UNSUPPORTED** |

---

## 2. The central defect: reward-hacking via context destruction

### 2.1 Reproduction

```bash
.venv/Scripts/python.exe /tmp/empty_ctx.py   # script body in §11
```

A 2,510-token context containing a 3-file import chain plus 40 lexically-similar distractors.
Query: *"What value does resolve_shipping_surcharge produce?"*

**What the model actually receives:**

```
[system] 'You are a precise technical AI answering questions.'
[user]   '\n\nQUESTION: What value does resolve_shipping_surcharge produce?'
```

**What the plan reports:**

```
tokens_avoided: 2481      original: 2510   optimized: 29
reduction: 98.84%
fallback_to_raw: False
chosen: aggressive_hybrid_compress   quality_risk: 0.015
```

The entire context was deleted. The plan reports a 98.84% win and a 1.5% quality risk. Actual
answer probability: zero.

### 2.2 Root cause

`npk/context/info_gain.py` — the greedy selection loop terminates on an **absolute** threshold
applied to a **scale-dependent** quantity:

```python
efficiency = total_gain / math.sqrt(costs[i])
...
if best_candidate == -1 or best_efficiency <= 0.05:
    break
```

In the reproduction the best block (`entry.py`) scores BM25 = 0.0735 at 25 tokens, giving
efficiency = 0.0735/√25 = **0.0147 < 0.05** → the loop breaks on iteration 1 and returns `[]`.
`compute_transitive_closure` over an empty seed set is empty, so `retrieve_relevant_context`
returns `""`.

`npk/planner.py` then treats the empty result as a large win:

```python
dropped = r_stats["original_tokens"] - r_stats["optimized_tokens"]   # = 2481 - 0
if dropped > 0:
    m["content"] = opt_ctx + suffix_part        # opt_ctx == ""
```

**Why this gets worse at scale:** BM25 scores fall as term frequency spreads across a corpus, and
`√cost` grows with block size. Both push `efficiency` toward the fixed 0.05 floor. The collapse is
*more* likely on large, repetitive contexts — precisely NeuralPack's target regime.

### 2.3 Scope

On the sealed 200 synthetic tasks the collapse rate is **0/200** and fact retention is 200/200, so
this is reachable rather than universal. But it is silent, unguarded, and rewarded by the metric.

---

## 3. Benchmark methodology failures

### 3.1 The ablation study toggles dead flags

`ContextExecutionPlanner.__init__` accepts `enable_dedup` and `enable_prefix_opt`, assigns them to
`self`, and **never reads them again**:

```
$ grep -rn "enable_dedup"      npk/ → planner.py:25 (param), planner.py:33 (assign). No reads.
$ grep -rn "enable_prefix_opt" npk/ → planner.py:28 (param), planner.py:36 (assign). No reads.
```

Dedup and prefix alignment run unconditionally. Empirically, `enable_dedup=False` and
`enable_prefix_opt=False` produce byte-identical output (264 tokens, and the chosen plan still
lists `'deduplicate'` and `'provider_prefix_cache'` among its strategies). The
`no_deduplication` and `no_prefix_alignment` rows of `component_ablation.json` are therefore
scientifically void — which is exactly why they report numbers identical to `full_neuralpack`
(1804 tokens / 56.81%).

`enable_retrieval`, `enable_compression`, and `dependency_depth` *are* wired through.

### 3.2 Fabricated "quality retention"

`benchmarks/evaluation_suite.py:480` and `benchmarks/msc_ablation.py:180`:

```python
quality_retention_pct = (npk_acc / base_acc * 100) if base_acc > 0 else 100.0
```

When baseline accuracy is 0 — true for **every mock-provider run** — retention is hardcoded to
100.0. This is the sole source of the "100% quality retention" in
`holdout-msc-001/002/003`, all of which record `baseline_accuracy: 0.0` and
`neuralpack_accuracy: 0.0`.

### 3.3 Accuracy measured against an echo

`npk/providers/mock.py` default response function:

```python
lambda msgs: f"Mock response to: {msgs[-1].get('content', '')[:30]}"
```

It echoes 30 characters. It answers nothing. Every mock-provider "accuracy" number is a measure of
whether the gold string happens to fall in the first 30 characters of the prompt. Hence the sealed
200 suite scoring **5.0% for all five arms** — baseline, BM25, dense, hybrid RRF, and NeuralPack
alike. This suite cannot distinguish any retrieval method from any other.

### 3.4 "Context efficiency" exceeding 100%

`holdout-msc-001/002/003` report `overall_context_efficiency_pct` of **152.11 / 154.09 / 154.09**,
and individual live tasks report up to **118.91%** (`code_h2_jwt_expiration`). Efficiency is
computed as MSC-block tokens ÷ NeuralPack tokens, comparing an *uncompressed block-level* lower
bound against *line-level compressed* output. These are different granularities, so the ratio has
no lower-bound interpretation and can exceed 1. The MSC figure is not a proven minimum; it should
be labelled **Empirical MSC** and only ever compared against block-level selections.

### 3.5 Actual context size per task (the "large context" claim)

Measured directly, not taken from cumulative totals:

| Benchmark | Tasks | **Baseline prompt tokens per task** | Reported total |
|---|---:|---|---:|
| Sealed 200 | 200 | **min 107 / median 326 / max 368** | 45,060 (a *sum*) |
| Live holdout (77.73% claim) | 10 | **3,510–3,516** | 35,134 (a *sum*) |
| Reproduction-001 (50.50% claim) | 9 | ~476 avg | 4,283 (a *sum*) |
| Profiler ("sub-ms") | — | **710** | — |

No benchmark in this repository exceeds ~3.5K tokens per request. The commit message claiming a
"live 10K+ context benchmark" is not supported: it appears to sum across tasks. All published
totals are cumulative and should not be read as context sizes.

### 3.6 Unmatched baseline budgets

In `holdout-live-code`, "standard RAG" uses **120–286 tokens/task** while NeuralPack uses
**530–1,521 tokens/task** — 4–5× more. Reporting 100% vs 80% accuracy from that comparison is not a
like-for-like result; it compares two different points on a cost/quality curve. A valid comparison
tunes the baseline's `top_k` to NeuralPack's token budget. See §7.

---

## 4. Product behavior (public-API testing)

### 4.1 What works

Exercised through the public API (`ContextExecutionPlanner.plan_and_optimize`), not test internals:

- Provider registry resolves and dispatches all 7 adapters.
- Context/query separation extracts trailing `QUESTION:` correctly.
- Conversation and tool-trace compilers trigger on the right context types.
- Single-needle retrieval at 25K/50K/100K tokens: **needle retained at start, middle and end
  positions in all 9 configurations**, at 99.85–99.96% reduction. This is the strongest genuine
  result in the repository (caveat: §7).

### 4.2 Adversarial battery (production defaults)

| Attack | Result |
|---|---|
| 8-hop chain + 30 distractors | PASS |
| Dynamic import / `getattr` | PASS |
| Superseded conversation fact | PASS (no stale leak) |
| Lost-in-the-middle, low overlap | PASS |
| Near-duplicate regional keys | PASS |

**Caveat that matters:** several of these pass for the wrong reason. In the 8-hop case the needle
line is `return 8731` and the query contains the word "return", so it survives by *lexical* overlap,
not graph traversal. Removing that overlap flips the result — see below.

### 4.3 The decisive counterexample

Needle sharing **zero** lexical overlap with the query, reachable only through a 2-hop import chain
(`entry.py → alpha.py → beta.py`), amid 40 lexically-similar distractors:

```
depth=0  needle_kept=False    depth=1  needle_kept=False    depth=2  needle_kept=False
depth=3  needle_kept=False    depth=5  needle_kept=False
retrieval stage: kept=0/43 blocks at every depth
```

The dependency graph is built correctly (`edges[0] = {1}`, 2 edges total) — the selector never seeds
it. Increasing depth does not help, because closure over an empty seed set is empty.
**"100% critical-context recall" is false.**

Separately, at a tight budget the closure expansion **overshoots the token budget**, because
`compute_transitive_closure` runs *after* budget-constrained selection with no re-check:

| budget | depth=1 | depth=2 | depth=3 | depth=10 |
|---:|---:|---:|---:|---:|
| 100 | 113 | 135 | 156 | 192 |

---

## 5. Test-suite quality (mutation testing)

Fresh run: **181 passed, 1 skipped, 0 failed, 0 xfailed** (11.05 s).

Six real defects injected one at a time; suite re-run; source restored via `git checkout`:

| Injected defect | Suite result | Verdict |
|---|---|---|
| Dependency expansion → identity (closure disabled) | 181 passed | **SURVIVED** |
| Query preservation → empty string | 181 passed | **SURVIVED** |
| Safety fallback → never fires | 181 passed | **SURVIVED** |
| Cost calculation → always 0.0 | 2 failed | CAUGHT |
| Deduplication → no-op | 4 failed | CAUGHT |
| Provider registry → always mock | 2 failed | CAUGHT |

**3 of 6 mutants survived — and they are precisely the three components the project claims as its
novelty:** graph-based dependency closure, query conditioning, and the safety fallback. The suite
covers plumbing (cost, dedup, registry) and not the algorithm. Classification: **weak suite**.

---

## 6. Cost audit

**Substring-collision bug** in `npk/cost.py::get_pricing`:

```python
if key in model_name.lower() or model_name.lower() in key:
```

`"gpt-4o"` is a substring of `"gpt-4o-mini"` and precedes it in the dict, so:

```
gpt-4o-mini  →  in=2.5  out=10.0     (should be 0.15 / 0.60)
estimate_cost('gpt-4o-mini', 1_000_000) = $2.50   (should be $0.15)
```

A **16.7× overcharge**, and `gpt-4o-mini` is the planner's *default* `target_model`. Every dollar
figure computed under the default model is inflated by this factor. Unknown models (`gpt-5`, `o3`)
silently fall through to `DEFAULT_PRICING` rather than erroring.

The pricing table also contains entries I could not verify as real released models
(`deepseek-v4-flash-0731`, `deepseek-v4-pro-0813`, `minimax-m3`, `kimi-k3`). These should be
removed or sourced, and the table should carry a "priced as of <date>" stamp.

The README's own headline is internally inconsistent with the commit history: README says
**27.24%** reduction / 45.37% cost saving; commits claim **50.50%** and **77.73%**; the ablation
says **56.81%**. These are different runs on different corpora, never reconciled in one place.

---

## 7. Does NeuralPack beat strong baselines?

Matched-token-budget probe (250 tokens for every method), needle-retention scored:

| Task | NeuralPack | BM25 @ budget | identifier-grep @ budget |
|---|---|---|---|
| T1 exact-identifier | HIT | HIT | HIT |
| T2 two-hop dependency | HIT | HIT | MISS |
| T3 low-lexical-overlap ("concurrently" → `MAX_PARALLEL_WORKERS`) | MISS | MISS | MISS |
| **Total** | **2/3** | **2/3** | 1/3 |

At matched budget, **NeuralPack ties plain BM25**. It beats naive grep. It shows no measured
advantage over the baseline it claims to supersede, and both fail the semantic-gap case.

**This is a 3-task probe, not a benchmark** — it is indicative, not conclusive. But it is the only
matched-budget comparison in existence for this project, and the burden of proof sits with the
claim, not the audit. The existing sealed-200 comparison cannot fill that gap because all arms
score identically at 5.0% (§3.3).

**Not completed:** I did not build baselines using a real neural embedding model or a genuine
cross-encoder reranker (Phases 11–12 as specified). No embedding model is vendored in this repo and
I did not download one. The `run_dense` baseline in `benchmarks/baselines.py` is n-gram based, not a
real embedding model, so the existing "dense" comparison is a strawman regardless.

---

## 8. Security audit

### 8.1 Live API key committed to git history — action required

`tests/test_secrets.py` line 14 embeds a 70-character `nvapi-…` token as a test fixture. Verified by
SHA-256 comparison (values never printed): the token's hash **matches the live key in `.env`
exactly**. It is present in **7 commits**: `b8ab2f5`, `efca842`, `9628a9b`, `a6832f2`, `9f0074f`,
`989db51`, `831f2e1`.

**Mitigating factor:** `git remote -v` is empty — the repository has never been pushed. Exposure is
local-only. **Rotate the key anyway**, since it is in durable local history and would be published
by any future `git push`.

Recommended remediation, in order:
1. Rotate the NVIDIA key at the provider now.
2. Replace the fixture with a synthetic string (e.g. `nvapi-` + 60 `x`s).
3. Purge history (`git filter-repo`) **before** adding any remote.

### 8.2 The secret scanner cannot fail

```python
try:
    content = full.read_text(...)
    match = key_pattern.search(content)
    assert match is None, f"Potential exposed secret found in git tracked file: {f_path}"
except Exception:
    continue
```

`AssertionError` is a subclass of `Exception`, so the bare `except` swallows the very assertion that
detects the secret. Proof:

```
files the pattern DOES match: ['tests/test_secrets.py']
but the test passes:          3 passed in 0.07s
```

The scanner correctly identifies the leaked key and then discards the finding. CLAIM_AUDIT item #11
("Automated secret scanning — VERIFIED, 3 tests passing") is false.

`.env` itself is correctly gitignored and untracked; `.gitignore` coverage is otherwise sound.

---

## 9. Performance audit

Planning latency, production defaults, synthetic code corpus, median of 3–5 runs:

| Context tokens | Median planning | p95 | Output tokens |
|---:|---:|---:|---:|
| 2,212 | 2.7 ms | 4.6 ms | 134 |
| 6,644 | 7.2 ms | 7.7 ms | 134 |
| 26,623 | 28.9 ms | 30.3 ms | 134 |
| 51,054 | 57.3 ms | 58.0 ms | 134 |
| 102,138 | **127.9 ms** | 130.2 ms | 134 |

Roughly linear (~1.25 ms per 1K tokens). The claimed "sub-millisecond overhead" holds only for the
710-token context the profiler actually measured; at 100K it is **~140× larger**. In fairness, 128 ms
against multi-second LLM latency is not a product problem — but the *claim* is false, and the
profiler artifact should record the context size alongside the number.

I did not decompose the 100K measurement into per-stage costs (parsing / BM25 / graph / traversal /
compression); only the total was measured at scale. The existing per-stage breakdown is 710-token
data only.

---

## 10. What I did not do

Stated plainly so the audit is not over-read:

- **No live provider calls.** Every number above is offline. The live NVIDIA NIM results in
  `holdout-live-code` and `reproduction-001` were read as artifacts, not re-executed. Their latency
  spread (706 ms–10,470 ms) is consistent with real network calls, and I found no evidence of
  fabrication — but I did not independently confirm them.
- **No real embedding or reranker baselines** (Phases 11–12) — see §7.
- **No real-repository large-context corpus** (Phase 9). My 25K–100K contexts are synthetic and
  templated; they establish scaling and single-needle retention, not real-world accuracy.
- **No per-stage profiling at scale** (§9).
- **Phases 17–19 (improvements, new algorithms) were not started**, per the instruction to complete
  the audit first. No production code was modified; the working tree is clean.

---

## 11. Reproduction commands

```bash
# Test suite
.venv/Scripts/python.exe -m pytest tests/ -q

# Dead ablation flags
grep -rn "enable_dedup\|enable_prefix_opt" npk/

# Context-collapse reproduction (the central defect)
.venv/Scripts/python.exe /tmp/empty_ctx.py

# Dependency-closure counterexample
.venv/Scripts/python.exe /tmp/isolate_graph.py

# Budget overshoot + depth probe
.venv/Scripts/python.exe /tmp/probe_selector.py

# Latency scaling to 100K
.venv/Scripts/python.exe /tmp/scaling.py

# Large-context needle retention
.venv/Scripts/python.exe /tmp/largectx.py

# Matched-budget baseline comparison
.venv/Scripts/python.exe /tmp/fair.py

# Mutation testing
.venv/Scripts/python.exe /tmp/mutate.py

# Pricing collision
.venv/Scripts/python.exe -c "from npk.cost import estimate_cost; print(estimate_cost('gpt-4o-mini',1000000))"
```

Audit scripts live in the scratch directory (`/tmp/*.py` → `%LOCALAPPDATA%\Temp\`). They are
throwaway probes, not committed; the §13 recommendation is to promote the failing cases into
`tests/` as permanent regressions.

**Raw artifact paths inspected:**
`experiments/runs/2026-09-06-sealed-200-00{1,2}/summary.json`,
`experiments/runs/2026-09-06-holdout-msc-00{1,2,3}/summary.json`,
`experiments/runs/2026-09-06-holdout-live-code/summary.json`,
`experiments/runs/2026-09-06-reproduction-001/summary.json`,
`experiments/results/component_ablation.json`,
`experiments/results/profiler_summary.json`,
`experiments/results/context-optimization/benchmark_summary.json`,
`research/verification/CLAIM_AUDIT.md`, `research/math/theorems.md`.

---

## 12. Final classification

### **UNSUBSTANTIATED**

Justification against the definition ("major existing claims do not survive audit"):

- Every accuracy claim is either measured against an echoing mock (5.0% across all arms) or produced
  by a hardcoded divide-by-zero branch (0% → "100% retention").
- "100% critical-context recall" has a concrete counterexample.
- "Sub-millisecond overhead" is off by ~140× at realistic scale.
- "10K+ context" is off by ~3× and derived from summing across tasks.
- The safety fallback does not fire on total context destruction.
- 2 of 6 ablation rows toggle dead code.
- The cost model overcharges its own default model by 16.7×.
- The one matched-budget comparison shows parity with plain BM25.
- Mutation testing shows the suite does not defend the novelty claims.

This is a verdict on the **evidence**, not on the idea. Query-conditioned context compression is a
legitimate problem, and one capability here is real and worth keeping (§13).

### Strongest genuine capability

**Query-conditioned extractive compression for exact-identifier lookups over large contexts.**
Retaining a needle at 99.96% reduction on a 100K-token context, position-independently, is a real
result. It is not differentiated from BM25 at matched budget on the evidence available, and it has
not been shown to survive the semantic gap (T3). The program-graph slicing that supposedly
distinguishes it did not measurably contribute in any test I ran, and is disabled-by-default in
effect (`dependency_depth=1`).

### Is it differentiated?

**Not on current evidence.** To become so, it needs to beat a *tuned* BM25 and a real embedding
baseline at matched token budgets on tasks that are not exact-identifier lookups.

---

## 13. Prioritized remediation

**P0 — security**
1. Rotate the NVIDIA API key.
2. Replace the real key in `tests/test_secrets.py` with a synthetic fixture.
3. Remove `except Exception: continue` from the scanner, or narrow it to `OSError`/`UnicodeDecodeError`.
4. Purge git history before adding any remote.

**P0 — correctness**
5. Guard against empty/near-empty selection in `retrieve_relevant_context`; if the selector returns
   nothing, fall back to raw context rather than shipping an empty prompt.
6. Make `quality_risk` a function of what was actually removed (fraction of blocks dropped, whether
   any query term survives), not a hardcoded constant.
7. Replace the absolute `0.05` efficiency floor with a scale-free criterion (e.g. relative to the
   max observed efficiency), or make it a documented, tested parameter.
8. Re-check the token budget after transitive-closure expansion.
9. Fix `get_pricing` to match exact model IDs longest-first; add a regression test asserting
   `gpt-4o-mini != gpt-4o` pricing.

**P1 — honesty of reporting**
10. Wire up `enable_dedup` / `enable_prefix_opt`, or delete them and retract the two ablation rows.
11. Make `quality_retention_pct` return `None`/`n/a` when `base_acc == 0`, never 100.0.
12. Stop reporting mock-provider accuracy as accuracy; label it fact-retention.
13. Restate every benchmark in **per-task** context tokens; retract "10K+ context".
14. Rename MSC efficiency to **Empirical MSC** and only compare like granularities.
15. Record context size next to every latency number; retract "sub-millisecond" as a general claim.

**P1 — evaluation**
16. Re-run every comparison at matched token budgets with a tuned `top_k`.
17. Add a real embedding baseline and a real cross-encoder reranker before any superiority claim.
18. Promote the failing cases from §4.3 and §2.1 into `tests/` as permanent regressions.
19. Add tests that fail when dependency closure, query preservation, or the fallback break.

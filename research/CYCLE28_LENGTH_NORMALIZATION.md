# Test the seed scorer's length penalty

Status: all 3,996 LOCAL observations and independent audit complete. No product promotion.
Verdict remains PIVOT REQUIRED.

The false raise hint was real, but its removal did not recover the traceback
constructor at small budgets. Short context-manager methods still outrank the
longer constructor. This motivates testing the existing scorer's length penalty
before adding another index, encoder or packing rule.

## Hypothesis and controls

CONJECTURE: weaker length normalization may recover relevant long functions
currently crowded out by short signature matches. It may also demote useful
short definitions. Neither direction is assumed to improve answer quality.

This parameter is established retrieval machinery, not a new invention.
Robertson and Zaragoza describe the tradeoff between document verbosity and
scope, and treat parameter choice as an empirical question.
[Primary source, sections 3.4.5 and 3.5](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf).

The frozen plan is `cycle28-length-penalty-v1`, SHA-256
`dc454d58eb98ae2a0ff9af1e3b31d65d95a617fb7808e919eb01ab25d87b04a1`.
It declares five b values: 0, .25, .5, .75 and 1; k1 stays at 1.2. Each uses the
conservative intent guard. A sixth, original-scorer arm retains original intent
and b=.75. Compare b variants against the guarded b=.75 arm to isolate the
length change; the raw original control also includes the known intent error.

There are 222 inspected questions, 3,513 identical source blocks and three exact
NIM context caps: 512, 2,048 and 8,192. The plan contains 3,996 observations.
Each request has the same 558,878 available source tokens from 155 public Python
files. Original cl100k document lengths remain the scorer's normalization
metadata; they are not substituted for NIM budget counts or used in a mixed-unit
efficiency ratio.

The unchanged original and guarded .75 rankings reproduce the prior plan on all
222 questions. EMPIRICAL: each non-default b changes candidate order on all 222
queries. This is a parameter-wiring result, not a quality result. All declared
cells must finish before choosing a candidate. Source-based retention and
definition exposure remain diagnostics, not answer accuracy or sufficient
context certificates.

## Limited mathematical observation

PROVED UNDER ASSUMPTIONS: fix positive term frequency t, term weight w,
saturation k, document/average length ratio r, and b in [0,1]. For the scorer's
pre-bonus term contribution,

`f(b) = w t (k+1) / [t + k(1-b+br)]`,

its derivative is

`f'(b) = -w t (k+1) k (r-1) / [t + k(1-b+br)]²`.

The denominator is positive throughout the interval. All numerator factors
except the leading minus sign and (r-1) are positive. Therefore increasing b
reduces this term contribution for above-average length, increases it for
below-average length, and leaves it unchanged at average length. This follows
by direct differentiation; a SymPy 1.14.0 check independently simplifies the
difference between the derived and stated expressions to zero.

This simple calculus observation is not claimed as novel. It applies before
the scorer's structural bonuses, symbol boosts, scoping and token-budget packing.
It does not establish a final ranking, relevance gain or best parameter.

EMPIRICAL exact-arithmetic illustration: with k=6/5, weight one, average length
55, a short document (length 10, frequency 1) scores 1 at b=0 and 242/161 at
b=3/4. A longer document (length 100, frequency 2) scores 11/8 and 484/433.
Their order reverses. No relevance labels are attached to this illustration.
The runner and results are `cycle28-length-math.py` and
`cycle28-length-math.json`; finite arithmetic examples are not universal proofs.

## Implementation and verification

The experiment reuses the frozen rival's candidate function with a private
globals mapping for each call. It does not patch process-wide constants or
rewrite the ranking formula. Query text, lexical facets, postings, source
metadata and structural intent stay fixed within the five challengers. Because
the existing structural bonus scales with the best BM25 score, its magnitude
can move with normalization; that coupling remains explicit in this experiment.

Thirteen tests cover parameter validation, unchanged queries and concurrent
requests using different penalties. Two new mutation tripwires catch an ignored
parameter and a leaking process-global override. The full canonical suite passes
990 tests with two explicit symlink skips; all 103 mutants are killed across
328 current Python source files. The full reports are
`cycle28-length-canonical-full.xml` and
`cycle28-length-canonical-mutations.json`.

The concurrent test uses a fixture scorer to isolate the shared-globals risk.
Actual candidate reproduction uses the frozen scorer's ordinary serial SQLite
connection; this does not claim that one SQLite connection is concurrently usable.

Selection runs the existing public-selector experiment harness and will be
checked with the independent source/count/admission auditor. Identical
query/ranking/budget combinations explicitly share local computations. These
cached, concurrent diagnostic timings cannot establish clean query latency,
compilation cost, amortization or net dollar savings. No target model runs in
this selection study; NeuralPack's default runtime remains zero-generative-LLM.

## Completed parallel evidence

The intent study is now independently audited: 2,664 observations, 789 distinct
admission orders and 56,381 source-item occurrences all pass. Original and both
guarded modes retain 182/225/242 of 246 annotations at the three caps. Disabling
all structural lookup retains 168/206/232. These are seed-lookup results on
inspected questions, not evidence that graph expansion helps. The narrow guard
changes no annotated success outcome and leaves the constructor failure at the
two smaller caps.

All 45 planned target-profile requests have now been attempted once: 28 LIVE
answers and 17 HTTP 503 responses. All 28 hosted prompt counts match independent
local counts. Correct / answered / planned outcomes are BM25 5/8/15, CRISP
7/10/15, and no-context 3/10/15. Each arm still has missing answer outcomes, so
its accuracy is N/A. The seven jointly answered BM25/CRISP pairs have one CRISP
win and six ties; eight pairs are missing. This does not establish a general
answer-quality winner.

On identical evidence, the newer target configuration has two wins, zero losses
and five ties against the original configuration for each retrieval arm, with
eight missing pairs apiece. It jointly changes thinking flags and output
allowance, so this is not an isolated thinking-effect claim. The original
non-thinking and larger SQLAlchemy studies remain open.

Keep the structural-lookup control and guarded intent comparison. Do not promote
the guard as a solution to the traceback problem. Next: complete the five-setting
budget sweep, audit every result, examine per-task losses and cost-quality
frontiers, and retain a parameter change only if the broader evidence supports
it. The full 8,658-cell packing audit also remains in progress.

The completed intent and target-profile checkpoint is archived as
`cycle28-intent-checkpoint.zip`: 41,016,122 bytes, 4,249 files, SHA-256
`b18384c01abff8062cebf91598175b05c5ea3f898b802f41bad9d926dd4b891d`.
All member hashes and ZIP CRCs pass. 315,511 decoded/SQLite pattern checks find
no recognized credential match. The archive includes the frozen length-study
inputs and explicitly leaves its selections, the full packing audit and the
overall goal open. The older target responses are referenced through their
previous verified checkpoint. It is not a complete independent-validation claim.

## Focused traceback reproduction after generation

All 3,996 observations completed, using 3,333 distinct local selector computations.
Independent full source/count/admission replay is running. A separate focused
check verifies whole-context counts and target-file spans for the original
traceback failure across all 18 mode/budget cells. It identifies the method
precisely as `Traceback.from_exception`, a factory method (earlier records call
it the constructor).

At b=0 or .25, the factory moves to zero-based rank 0; at .5 it moves to rank 1.
All three settings retain its annotation at 2,048 tokens. The guarded .75 arm
ranks it tenth and still misses it; b=1 ranks it thirteenth and misses it.
All modes miss at 512 because the target block cannot fit there, and all retain
it at 8,192. This confirms a narrow mechanism, not an aggregate quality win.
The focused result is `cycle28-length-traceback.json`; the full-matrix losses
still govern any parameter decision. No parameter is promoted from this case.

## Complete audit: the motivating fix does not win overall

The full independent audit passes all 3,996 records, 3,333 distinct admission
orders and 73,914 source-item checks. The upstream tokenizer verifies every
whole-context cap. `cycle28-length-audit-full.json` binds all raw records;
`cycle28-length-audited-summary.json` independently aggregates its audited rows,
paired task losses and mean-token/source-hit frontier with DuckDB.

| Guarded BM25 b | Hits at 512 | Hits at 2,048 | Hits at 8,192 |
| --- | ---: | ---: | ---: |
| 0 | 172 | 215 | 238 |
| .25 | 181 | 222 | 239 |
| .5 | 180 | 225 | 241 |
| .75 control | 182 | 225 | 242 |
| 1 | 180 | 228 | 242 |

Each value is source hits out of the same 246 annotations. The original
unguarded .75 arm matches the guarded control's counts. At 2K, b=0 gains four
annotations but loses 14; .25 gains four and loses seven; .5 gains three and
loses three. The traceback factory is one gain, insufficient to justify those
other losses. At 8K, all three weaker penalties lose annotations with no gains.

The b=1 arm gains three annotations and loses none at 2K, but gains three and
loses five at 512. It ties the control's annotations at 8K. On the 15 behavior
questions, primary-definition exposure changes from 8/10/12 at .75 to 9/11/12
at 1. This is source exposure, not answer success or sufficient evidence.

EMPIRICAL decision: reject a general weakening of the length penalty. Retain
b=1 as a challenger for the 2K setting, with its 512-token regressions visible.
No arm earns universal or default promotion. The questions were already
inspected; these small changes require fresh tasks and real answer validation.
The conjectured single-case mechanism is supported, while the hoped-for broad
retrieval gain from weakening normalization is not supported by this sweep.

The next retrieval comparison should include this tuned strong baseline.
The separate compiled-boundary counter preserves measured selections while
reducing local cost; it does not turn these retrieval losses into quality gains.

# Cycle 28: small manually seeded evidence is not automatically better

Verdict: **PIVOT REQUIRED**. This experiment rejects a tempting shortcut: select
only the named primary functions and assume the reduced context will improve
target reasoning. It changes research tooling, not NeuralPack's compiler/runtime,
default selection, `.npk` schema or zero-generative-optimizer policy.

The completed transport-recovery pass now gives NeuralPack BM25 all15 answers:
five pass the frozen task contract. Native CRISP has seven passes with one answer
still missing, so it wins this particular comparison regardless of that missing
outcome. See the final checkpoint section below; the earlier table preserves the
separately frozen recovery-after18 comparison.

## Frozen diagnostic and source audit

The prior cycle recorded wrong answers despite complete function/table exposure.
Two reference arms now use the same 15 inspected public-library questions and
executed expected answers as the earlier BM25/CRISP comparison. Target generation
settings and the 2,048-token evidence cap are unchanged. The primary functions
are manually chosen from the earlier diagnostic; this is not automatic retrieval,
an unseen benchmark, a proven sufficient context, MSC, or a quality upper bound.

`reference_primary` supplies complete primary function/method definitions.
`reference_module_bindings` adds their directly referenced, unconditional
top-level imports and assignments. The compiler's symbol tables distinguish
function-body globals from shadowing locals. See the primary
[Python symbol-table documentation](https://docs.python.org/3.12/library/symtable.html).
The prototype parses and copies source; it never executes imports or initializers.
It does not close transitive or dynamic dependencies.

The source attack found three definitions named `MultiDict.getlist`: overload
stubs at lines259/261 and the implementation at262. The reference seed explicitly
pins the implementation's line in the hash-bound Werkzeug3.1.3 source. Ambiguous
names without an explicit line are rejected, not silently resolved to a stub or
last match. This is manual diagnostic metadata, not a new automatic resolution
algorithm. A permanent regression test and mutation tripwire cover the ambiguity.

An independent audit reconstructs source spans with the prior definition parser,
checks exact source bytes and allowable declarations, reconstructs full context
payloads, recounts token budgets/prompt framing, and verifies every question and
system prompt. It hashes 155 source files and recounts **558,878 available source
tokens per request**. This is the source-file representation, not the 559,083
compiled-block count used in separate cache profiles. The primary/augmented views
range from96 to1,383 tokens with provenance included. No context was cut to fit.

Plan SHA-256:
`8986f0dcc3ab257553bf7707ed23fe2221036745d02c7abd877d08a60a8f60f5`.
All30 observations were frozen before dispatch. Six arm pairs produce the same
payload, yielding **24 unique new requests**, disjoint from the parent requests.
Those six pairs share one returned answer; they are not independent repetitions.
Order uses fixed shuffle seed2912. Source/plan/asset/code changes, missing cells,
orphan responses and uncertain previous attempts prevent dispatch.

The final API call remains the target consumer. Preparation, counting, source
analysis, selection and audits use no generative models or network calls.
No arbitrary repository code is executed by this prototype. Real oracle results
are inherited from the separately pinned, deliberately executed library tests.

## Actual answer results

After a verified1,897-second service cooldown, bounded single-worker calls use
15-second minimum start intervals. Three batches make10,10 and4 attempts, yielding
9,6 and4 answers. Final totals are **24 attempts,19 answers,5 HTTP503 failures**.
Every request is terminal, but answer evaluation remains incomplete. All19
returned prompt counts match the pinned local tokenizer and template. No reference
payload was retried. No answer was resampled to improve its grade.

The answer reporter records `attempt_stage_complete=true` and
`answer_stage_complete=false`. Its COMPLETE status describes attempts only.
An independent comparison regrades archived response/ledger snapshots against
the unchanged executed oracle, checks LIVE/REPLAY provenance and shared settings,
and recounts context tokens. Baselines use the frozen recovery-after18 checkpoint.

| Method | Mean selected tokens | Correct | Answered | Missing |
|---|---:|---:|---:|---:|
| Manual primary functions | 368.1 | 4 | 13 | 2 |
| Manual functions + direct module bindings | 415.7 | 5 | 11 | 4 |
| NeuralPack BM25,60 candidates | 2,034.3 | 5 | 12 | 3 |
| Native CRISP with NIM budget guard | 2,038.6 | 7 | 13 | 2 |
| No-context control | 0 | 1 | 10 | 5 |

All arms have15 planned tasks; complete accuracy remains N/A. The retrieval arms
share a2,048-token cap; actual lengths differ. The no-context arm is explicitly
a0-token control. Token reduction alone is not a win or a cost-quality improvement.

**EMPIRICAL fixed-trial bound:** even if both missing primary-function answers
were correct, that arm could reach only6 correct tasks, below native CRISP's7
already correct tasks. The paired primary-vs-CRISP outcomes are0 wins,3 losses,
9 ties and3 missing pairs. The corresponding direct-binding comparison has
0 wins,1 loss,9 ties and5 missing pairs. It establishes no improvement over CRISP.

Adding direct bindings relative to primary-only gives2 wins,0 losses,8 ties and
5 missing pairs. Five of the ties are identical payloads, not new confirmations.
Among tasks with different contexts there are2 wins,0 losses,3 ties and4 missing
pairs. This limited, post-hoc, stochastic observation does not establish graph
superiority or justify enabling a new subsystem by default.

The key MIME task's augmented reference receives a503, so the compact function
plus literal-table counterfactual remains unanswered. Its primary-only response
is wrong. In the integer-conversion task, the full primary function is present,
but the target returns7 for decimal string12.7 where the executed oracle returns12.
That response is shared by both reference arms. The experiment does not isolate
omission, target reasoning, presentation, or sampling as a universal cause.

Reference ledger SHA-256:
`7c5c8ad240965329090e20f83682969e69926c74e64abbe1e5a34065e8126f3f`.
Reporter SHA-256:
`a00aa6bd0a0ddf1f79e7db06c590ae15e93ba30859c043947bac21c6051f47b8`.
See `cycle28-reference-answer-24.json` and `cycle28-reference-comparison-24.json`.
Historic and current stochastic responses span different times; provider drift
and incomplete transport outcomes limit causal inference. No billing rate or
local compute price is invented, and no dollar-saving claim is made.

## Attacks, decision and next hypothesis

The local counterexample runner reproduces missing configuration in default
arguments, conditional declarations, and transitive initializers. It stores
synthetic sources and selected contexts with hashes and assertions. These are
explicit limitations of the reference builder, not verified runtime capabilities.
Function-body symbol-table names alone do not cover defaults evaluated in the
enclosing scope. Unconditional top-level binding extraction does not cover
control flow. One-hop expansion does not close an initializer's dependencies.

Canonical validation passes **1,106 tests**, skips two symlink tests, and kills
**138/138 mutants** by assertion failures. The report binds349 current Python
sources. Six new mutants cover scope/shadowing, overload choice, physical Unicode
line handling, empty seeds, whole-context budget accounting and validation bypass.
The independent payload audit, raw-answer comparison and three limitation cases
are additional executable experiments, not extra unit-test counts.

KEEP the audited counterfactual infrastructure and explicit rejection of ambiguous
reference definitions. DISCARD the main-function-only strategy as a proposed
improvement for this workload. Do not promote manual seeds or one-hop declarations
into the automatic runtime. No champion or core-format change is made.

**CONJECTURE:** the next useful diagnostic should separate missing dependencies
from target reasoning limits before investing in another retrieval architecture.
Use fully specified, executable small examples and freeze any stronger target
configuration as a separate experiment; preserve the current contexts and every
old answer. Improved answers from another target configuration would be target
evidence, not NeuralPack gains. A deployable dependency selector would separately
need scope/default/control-flow handling, budget checks at each expansion and
matched-budget evidence on new tasks. More tokenizer polish is lower priority.

## Completed recovery pass and final comparison

After the last four reference transports succeed, a verified2,431-second cooldown
and exact ledger checks permit resuming only the31 eligible original payloads
that have never received their one recovery attempt. Batches10/10/10/1 return
8/6/8/1 answers:23 newly recovered answers and8 additional503s. The first18
recovery attempts are preserved. The resulting49-attempt recovery pass yields
35 answers and14 HTTP503 failures, with zero never-retried eligible payloads.
All134 original-or-recovered returned prompt counts match. These134 answers come
from197 historical API attempts; the original148-attempt ledger remains intact.

This cycle makes55 new API attempts:24 reference calls plus31 recovery calls,
with42 returned answers. These are returned responses, not42 successful tasks.
Across both experiments there are221 historical API attempts. No failed retry or
existing answer is resampled. Later512/8K/full stages of the original plan still
contain268 never-attempted payloads, and no full558K LIVE call has been made.

The final independent comparison uses `cycle28-recovery-answer-49.json` and
`cycle28-reference-answer-24.json`, preserving the earlier comparisons and their
execution-source snapshots.

| Method | Correct of15 planned | Answered | Missing | Complete accuracy |
|---|---:|---:|---:|---:|
| NeuralPack BM25 | 5 | 15 | 0 | 33.3% |
| Native CRISP | 7 | 14 | 1 | N/A |
| Field-weighted lexical | 7 | 12 | 3 | N/A |
| Manual primary functions | 4 | 13 | 2 | N/A |
| Manual functions + direct bindings | 5 | 11 | 4 | N/A |
| No-context control | 1 | 14 | 1 | N/A |

CRISP's known7 passes exceed BM25's complete5 passes and the compact primary
arm's maximum possible6 passes in this fixed trial. The manual binding arm still
shows no observed win against CRISP. Field-weighted lexical retrieval has at
least7 passes, exceeding plain BM25 on these tasks, but does not establish an
advantage over CRISP or across new corpora/budgets. No champion is promoted.

A further post-hoc diagnostic prevents over-attributing strict failures to
reasoning. One failure in each reference arm contains the expected `TypeError`
class prefix plus extra unverified error text instead of the requested class
name alone. Both remain failures under the frozen contract. The primary arm has
eight other value/shape mismatches; the binding arm has four plus one JSON parse
failure. BM25's ten failures are other value/shape mismatches. This diagnostic
changes no original grade, does not validate the added error-message claims,
and is not a replacement accuracy metric. Synthetic tripwires prevent confusing
a different exception class or ordinary text prefix with the expected class.
See `cycle28-answer-error-kinds.json`.

Verified checkpoint: `experiments/results/cycle28-reference-checkpoint.zip`,
6,873,164 bytes,1,076 files, SHA-256
`3899f1aeb37aa9cae08b28b8fad1cae1c10080ef15956517a8a60f9989603f26`.
All member hashes/CRCs and349 source bindings pass. The1,076 decoded pattern
checks find no recognized credentials; this is not a proof for every secret
format. Both target ledgers are quiescent and all launched processes terminal.
The broader research goal remains active. This cycle records progress through
negative evidence, not completion or a promoted retrieval architecture.

# Structural-intent controls after the rival counterexample

Status: LOCAL research; no product promotion. Verdict remains PIVOT REQUIRED.

We are building a compiled, local source selector. It must pick useful source
passages before the application's chosen answering model runs. These experiments
make zero generative optimization calls and do not edit the CRISP project.

## Discovery and isolated change

The frozen CRISP planner infers `(raises, exc)` from a question about constructing
traceback information. It splits `BaseException` into a word containing
`exception`, treats that noun as a raise action, and takes `exc` from `exc_type`.
The resulting bonus promotes `Parser.fail`. Its identifier regex also takes the
partial string `aseException` from inside `BaseException`.

The permanent original reproduction is
`experiments/runs/packs/cycle28-intent-counterexample-v1`. Removing only the
relation changes the constructor's zero-based rank from 11 to 10. Repetitive
context-manager methods remain ahead of it. This is not an answer fix.

`benchmarks/structural_intent.py` adds four research controls:

| Mode | Change to the original inferred relations |
|---|---|
| original | Preserve them exactly |
| disabled | Remove all structural bonuses |
| action | Require a whole raise/throw action word in the original question |
| conservative | Also require a whole argument name; abstain around negative, catching or literal-mention language |

The helper preserves the original query and lexical facet weights. It returns a
new plan and explicit suppression reasons. No numerical confidence or calibrated
probability is assigned. Dotted argument components are allowed; underscore and
camel-case subwords cannot manufacture an argument. The original lexical
identifier bug remains unchanged in this isolated experiment. The helper's whole
name extraction is not a claim that the rival's entire planner has been repaired.

## Attacks and known limits

Twenty-two permanent tests cover actual action words, exception nouns, catching,
negation, ASCII and curly-apostrophe contractions, quoted code, identifier
substrings, mixed clauses, byte-preserved Unicode questions, and request isolation.
They include positive controls so simply disabling every relation fails.
Two additional mutation tripwires deliberately bypass the guard or disable all
relations; both are killed by assertion failures.

The conservative policy deliberately abstains on “Where is ValueError raised and
TypeError not raised?” even though that contains a valid positive clause. It also
abstains on “raised without being caught.” These losses remain in the regression
suite. This is a limited global surface rule, not a natural-language parser.
Lexical retrieval continues when a relation is suppressed; suppression does not
certify a safe or complete evidence set.

FALSIFIED: this conservative rule recognizes every positive raises question.
The mixed-clause example is a direct counterexample. There is no universal
quality, seed precision, sufficiency or answer-preservation theorem here.

## Frozen comparison

`cycle28-intent-guards-v1` has plan SHA-256
`fc5bf682bf179f21f1cab2b6d8c47610d233661cb3234f15724cc8cc6287b58b`.
It fixes 222 inspected questions, four modes, and exact NIM context budgets
512/2,048/8,192: 2,664 observations. The source corpus is the same 155 Python
files from Rich, Jinja and Werkzeug. Each request has 558,878 available source
tokens; this is a per-request count, not a cumulative context claim.

Preparation reproduced every original candidate list from the earlier packing
plan. EMPIRICAL: disabling relations changes rankings on 46/222 queries. Each
guard changes only 1/222: the known traceback question. This says little about
generalization to negative intent, which the existing corpus barely exercises.

Every distinct query/ranking/budget combination runs the actual public selector.
Equivalent modes explicitly reference the same local computation. Source bodies,
spans, exact assembled budgets, preserved query bytes and fallback status are
checked. The independent auditor replays unique admission orders and checks all
output records against original source. It does not certify semantic intent.
The selection study completed all 2,664 observations using 789 distinct public
selector computations. Its independent audit now passes every record, all 789
distinct admission sequences and 56,381 source-item checks. These observations
are local retrieval measurements, not answer accuracy.

A targeted inspection, now covered by the full audit, still misses the annotated
constructor at 512 and 2,048 tokens under both original and conservative plans;
both include it at 8,192. The narrow intent correction has not repaired this
selection failure.

## Verification and parallel work

The canonical CPython 3.12.10 suite passed 977 tests with two explicit symlink
skips; all 101 mutants were killed and 325 Python hashes matched. Reports:
`cycle28-intent-canonical-full.xml` and
`cycle28-intent-canonical-mutations.json`. A subsequent audit-only change groups
record visits by query and increases its exact-string cache to 4,096 entries.
The complete canonical checks passed again in the `-v2` reports: 977 passed,
two skipped and all 101 mutants killed. All 325 current Python hashes match.
The earlier evidence is retained. No admission or source check was removed.

The 8,658-cell packing matrix has completed. Full independent source, exact-cost
and admission-order auditing is in progress. A slower first full-audit attempt
was intentionally stopped after reporting 600 checks; no partial report was
published. Its code and cancellation record are retained in the run directory.
The previously verified 500-row archive remains valid.

The new environment could not read the old parent `.npk`. We restored its
byte-identical, SHA-verified member from the accessible packing-500 archive into
`cycle28-readable-inputs-v1`. No ACL or original artifact was changed. The
recovery record binds archive and restored-artifact hashes.

The authorized target-profile diagnostic has resumed after the permission
environment changed. Its quiescent 39-request report has 25 LIVE answers and 14
HTTP 503 responses. All 25 successful hosted prompt counts equal the independent
local counts. It paused after three consecutive service errors; six requests
remain unattempted. This is still one
target answer call per context; the optimizer makes none. Missing transports
remain missing, and neither optimizer nor target accuracy is inferred from them.

The identical-evidence target-configuration comparison at this checkpoint has:

| Source | New configuration wins / losses / ties / missing pairs |
|---|---|
| No context | 1 / 0 / 2 / 12 |
| NeuralPack BM25 | 2 / 0 / 4 / 9 |
| Native guarded CRISP | 2 / 0 / 3 / 10 |

These checkpoint results are EMPIRICAL paired outcomes from single stochastic answers, not an
isolated thinking effect or proof of model superiority. The settings jointly
change thinking, low-effort behavior and output allowance. Under the new
configuration, NeuralPack and CRISP have only four jointly answered task pairs;
all tie, and 11 pairs remain missing. No retrieval winner is established.
Reports: `cycle28-library-low-effort-answer-39.json` and
`cycle28-target-profile-pairs-39.json`.

Keep: explicit controls, honest abstention reasons, permanent positive/negative
cases and exact-budget verification. Discard: treating an exception noun or an
identifier fragment as evidence of a requested action. Next: audit paired
selection gains/losses, finish the target-profile diagnostic, and test stronger
retrieval without assuming that forcing source variety helps. One high-value
challenger is to vary the seed scorer's length normalization: the constructor
still sits behind short methods with matching signature words. Sweep against
the original scorer on the whole question set, keep exact budget controls, and
measure losses on short-definition questions. This is an unimplemented
hypothesis, not a claim that less normalization will be better.

## Final target-profile attempts and next frozen study

After a 21-minute cooldown, the six never-attempted requests were dispatched.
No completed request was retried. All 45 requests now have terminal outcomes:
28 LIVE answers and 17 HTTP 503 responses. All 28 hosted prompt counts match.
The final report still gives N/A accuracy to every incomplete-answer arm.
Correct / answered / planned counts are BM25 5/8/15, CRISP 7/10/15 and none
3/10/15. Jointly answered BM25/CRISP pairs contain one CRISP win and six ties;
eight pairs are missing. No general answer-quality winner is established.

The final same-context configuration comparison is 1/0/2/12 for no context,
2/0/5/8 for BM25 and 2/0/5/8 for CRISP (wins/losses/ties/missing). The earlier
39-attempt checkpoint remains preserved. Final reports are
`cycle28-library-low-effort-answer-45.json` and
`cycle28-target-profile-pairs-45.json`.

The five-setting length-normalization study is now implemented and frozen at
3,996 observations. Its original and guarded .75 rank gates pass on all 222
questions. It is running without changing the product default. See
CYCLE28_LENGTH_NORMALIZATION.md. Current full verification passes 990 tests
with two skips and kills all 103 mutants; 328 Python hashes match.

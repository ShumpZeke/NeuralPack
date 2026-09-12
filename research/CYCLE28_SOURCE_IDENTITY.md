# Cycle 28: source identity and target-answer failures

Verdict: **PIVOT REQUIRED**. All measured results here are **EMPIRICAL**.
The compiler/runtime continues to make zero generative LLM calls. No renderer,
encoder, graph expansion or target-answer configuration is promoted by this work.

## What the answer failures reveal

The original frozen plan now has 108 DONE attempts: 81 returned answers,
26 HTTP 503 failures and one HTTP 429 failure. Its latest eight-request batch
paused after three consecutive 503 responses. No request remains in flight;
40 never-attempted requests remain in its first 2K/no-context stage.
The independent `cycle28-library-answer-108.json` captures a quiescent ledger
and verifies that all 81 distinct successful prompt counts match actual usage.
Every arm remains incomplete; answer accuracy stays N/A.

We separately inspected the earlier, frozen 100-attempt checkpoint. The
diagnostic lists 22 primary implementations across 15 behavior questions and
checks literal presence of their whole definitions, including decorators.
This list was chosen after inspecting source and some answers. It is neither
necessary nor sufficient evidence: unlisted helpers, initialization, configuration
and platform state can matter, while useful partial views need not contain a
whole function. It is not MSC or an accuracy substitute.

At the 2K cap, BM25 had six returned answers whose contexts contained all listed
implementations; four were wrong. Native guarded CRISP had seven such answers;
three were wrong, including two JSON-format failures. Among the observed errors:
clamping negative remaining work to zero despite the supplied subtraction,
returning the default for Jinja's decimal conversion despite its float fallback,
and retaining a Unicode filename despite the supplied ASCII-normalization code.
These observations motivate testing the consumer as well as the retriever;
they do not attribute every error to model reasoning alone.

The first diagnostic incorrectly excluded returned JSON-null/malformed answers
from a summary response count. The corrected version uses transport success to
count returned responses, then records parsing separately. Both versions and
their exact source are retained; `cycle28-library-failure-v2` supersedes v1.
The primary answer report and its grades were unaffected. A permanent test
distinguishes null, malformed JSON and a missing transport response.

## Carrying source identity into the consumer text

An `Evidence` item preserves a path, span and qualified name, but the default
`context_text()` joins only its raw source body. For example, `Task.remaining`
can reach a consumer as `def remaining(self)` without `Task` or the file path.
The same body can occur in different classes or files. This is a concrete
representation limitation; it does not by itself establish an answer failure.

The research renderer prefixes each unchanged body with one JSON metadata line:

```text
# source ["rich/progress.py:992-997","Task.remaining"]
    @property
    def remaining(self) -> Optional[float]:
        ...
```

The example above abbreviates the body only for this document. Actual experiment
contexts preserve every byte of each selected source body; there is no generated
summary or ellipsis substitution. Metadata is escaped onto one ASCII JSON line.
Headers and separators are charged to the actual whole-context tokenizer count,
including during dependency admission and final budget reconciliation. Individual
item token counts still describe raw bodies and are labeled accordingly.

`benchmarks/provenance_renderer.py` is a research adapter around the public
selector. Its checked AST transformation changes only candidate admission to
accept source identity as well as text, plus the result's context rendering.
It forwards the existing frozen seed-channel substitutions. It adds no default
CLI behavior, provider dependency, remote query rewrite or generative call.

## Matched-budget challenge

`cycle28-provenance-render-v1` fixes the same 15 questions, audited seed rankings,
3,513 compiled source blocks and pinned NIM tokenizer. Available source is
558,878 tokens per request. Three seed methods, three caps and two formats
produce 270 selections. The raw controls reproduce all 135 corresponding
previous selections. The header arm additionally saves a paired raw context
containing exactly the same bodies; that diagnostic intentionally leaves the
header tokens unused and is not a competent full-budget baseline.

The independent auditor does not import the candidate renderer or selector.
It consumes headers and exact body lengths, checks spans against original source,
replays greedy packing from saved rankings, counts assembled contexts, and checks
all controls. All 270 cells pass, covering 3,742 source-item occurrences, with
zero budget violations. Apparent header text inside a source body remains data;
an empty body cannot receive evidence credit from its metadata.

At the 2,048-token cap:

| Seed method | Raw: all listed functions exposed | Headers: all exposed | Median net header tokens | Mean body tokens, raw → headers |
|---|---:|---:|---:|---:|
| BM25, 60 candidates | 9/15 | 7/15 | 151 | 2,034.3 → 1,870.6 |
| Indexed path/name fields, 160 | 10/15 | 9/15 | 145 | 2,043.3 → 1,872.8 |
| CRISP scorer plus literal raise lookup on shared blocks, 160 | 10/15 | 10/15 | 166 | 2,043.0 → 1,863.0 |

This is source exposure, not answer accuracy. Headers displace listed definitions
for BM25's `rich_zero_unknown` and `jinja_integer_fallback`, and for the field
scorer's `rich_overshoot`. At 512 tokens, field scoring loses one task and the
CRISP-derived scorer trades one exposure gain for one loss. At 8K, field scoring
still loses `rich_overshoot`. These counterexamples and exact contexts remain in
the frozen records. Timings used a shared count cache and exclude seed lookup;
they are diagnostic, not a new latency claim.

**CONJECTURE:** qualified source identity may help a consumer distinguish scopes
enough to justify its token cost. The displacement counterexamples attack this
conjecture. No answer calls using these headers have yet run, so it remains
experimental. Location labels alone also do not reconstruct all lexical state.

## A separate target configuration diagnostic

`cycle28-library-low-effort-v1` fixes 45 observations: the original 15 questions
with 2K BM25, 2K native guarded CRISP, and no context. All source bytes, questions,
system instructions and oracle grades match their parents. Only target generation
changes: `enable_thinking=true`, `low_effort=true`, and an 8,192 output-token cap.
The original plan used thinking disabled and a 2,048 output-token cap. These
settings change together; this is not an isolated causal test of thinking.
The target still receives one request; no two-call reasoning-budget helper is used.

The model's [official card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard)
documents configurable reasoning and sampling. The independently pinned model
README and chat template contain the low-effort flag. The frozen local preflight
verifies all selected prompt counts, payload identities, source bytes and parent
grading. Hosted low-effort framing remains unverified until an actual response
supplies usage. This plan was chosen after observing errors, not preregistered.

Two local setup failures were fixed before any request: the research payload's
boolean flag allowlist did not include `low_effort`, and the executor read JSON
with the Windows locale encoding. The latter corrupted non-ASCII questions in
UTF-8 plans and triggered the request-integrity guard. JSON reads now specify
UTF-8; a regression simulates a cp1252 default and verifies original query bytes
reach dispatch. Existing plans and their request hashes were not rewritten.

The six-call first batch and its permitted retry both failed to launch because
automatic approval review timed out. The diagnostic ledger still has zero entries;
there are zero new calls for this plan. User guidance on retry is pending. This
is distinct from the original plan's actual HTTP transport failures.

## Keep, discard and next test

Keep exact source attribution, honest missing-answer accounting, explicit UTF-8
plan reads, and the independent rendering/packing audit. Discard automatic
promotion of source labels: they consume real budget and can displace useful code.
Also discard the assumption that better needle retrieval must improve answers.

Next, complete the unchanged-context target diagnostic when execution can proceed.
Then compare header and raw output with both same-evidence controls and competent
matched-budget controls. If neither helps, investigate source-state completeness
and the known short-boilerplate ranking loss instead of adding a remote optimizer.
The original 416-request evaluation and SQLAlchemy work remain open. These 15
source-informed questions do not meet the independent final-validation standard.

The current bundled CPython 3.12.14 suite passes **924 tests with 22 skips** in
35.25 seconds. Twenty skipped oracle tests require CPython 3.12.10; two require
symlink permission. All **96 mutants are killed**, including source-identity
erasure, ignoring header cost, dropping null responses and locale-corrupting a
plan. The source hashes cover `npk`, `benchmarks` and `tests`.

Earlier in this cycle the canonical full suite passed 943 tests with two skips,
before the subsequent UTF-8 executor repair. After that repair, its 24 targeted
executor/auditor checks passed on canonical Python. The final canonical full
rerun and its allowed retry both failed to launch due to approval timeouts;
it remains pending. These earlier results are not relabeled as a current full
pass. Initial fixture/setup errors and their failed XML reports are retained.

The verified archive is `experiments/results/cycle28-render-checkpoint.zip`:
27,977,476 bytes, 2,606 source/evidence files, SHA-256
`ef17eaf4700a93a348c6c02a13f12b9dcd494a99bcc2e239f530b0271697eff6`.
Every member's hash and ZIP CRC passed. Its 315,946 decoded/SQLite pattern
checks found zero recognized credential matches; this is not a universal
absence proof. The archive records the goal as open and preserves the pending
canonical/API work. Earlier archives remain unchanged.

# Exact-version manuals and answer provenance

Status: **PIVOT REQUIRED**. The known-task corpus experiment is complete. The
separate cycle 18 DeepSeek run was pending at this checkpoint and completed
during cycle 20. No compiled-runtime change or
retrieval challenger is promoted.

The hypothesis was that missing API documentation, rather than another query
splitter, explained difficult source-behavior failures. Three whole manuals
(`collections`, `functools`, `contextlib`) were added from CPython commit
`0cc81280367df838c4b199f8f0378837165071c2`, the pinned 3.12.10 source revision.
The original 135 files remained byte-identical. Available context increased
from 559,738 to 589,949 chars/4 estimated tokens per request, with 2,213 compiled
blocks in the larger corpus. These counts are not cumulative totals.

LOCAL evaluation reconstructed all 432 selections from exact source spans:
36 known questions × two corpora × BM25/weighted fields × 512/2,048/8,192 caps.
All 216 original-corpus contexts reproduced cycle 18. The code-span diagnostic
fell on the eight difficult cases after adding manuals, but that diagnostic
does not recognize equivalent manual prose and cannot establish answer quality.

Three shuffled compilation trials measured a median 3,687.38 ms for a full build
and 531.62 ms for adding the three new files to the accepted pack. Incremental
compilation parsed three files and skipped 135 unchanged files. All six complete
representations and 108 paired query outputs agreed. Source scanning/hashing
remains linear; the initial pack copy and post-build integrity checks were
excluded from timing. CPU tests/mutations did not overlap; LIVE IO and uncontrolled
host activity did. The pack occupied 13,860,864 bytes. This exercises existing
incremental infrastructure; it is not a before/after optimization claim.

Answer validation used `nvidia/nemotron-3-super-120b-a12b`, temperature 1, top-p
0.95, thinking disabled, and a 2,048 output-token cap. The frozen comparison has
360 observations but only 246 unique request payloads. It reused 173 terminal
parent records as explicit REPLAY, including 56 failed attempts, and made 73 new
LIVE attempts. The new calls returned 55 answers and 18 HTTP 503 errors. A pause
after consecutive errors was followed by a cooldown and execution of only the
unattempted requests. No old failed/uncertain request was retried.

On the eight difficult questions, manuals versus original source produced:

| Method | Input evidence cap | Wins | Losses | Ties | Missing pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 2,048 | 0 | 2 | 2 | 4 |
| BM25 | 8,192 | 0 | 0 | 3 | 5 |
| Weighted fields | 2,048 | 0 | 0 | 6 | 2 |
| Weighted fields | 8,192 | 0 | 1 | 3 | 4 |

Several older controls improved, but outcomes are sparse, settings are sampled
once, and shared payloads are not independent replications. The data does not
support generalizing the manual addition as an answer-quality improvement.
Actual provider input-token usage is reported separately from estimated caps.
Full-context and remote-preprocessor answers were not measured; billing, local
compute dollars and net savings remain N/A.

Reusing answers exposed a reporting boundary: prior results must not become new
API calls. Each replay now retains the exact original LIVE response, original
frozen plan and their hashes. It must reconstruct byte-for-byte except for the
explicit replay mode, zero new calls and origin references. Reported content and
usage must agree with the raw provider response. Tampering, mismatched settings,
unfinished parent runs and invented counts fail closed. Paired corpus reporting
also rejects duplicate or missing comparison cells. Hash consistency is not
independent proof that a provider executed a request.

Validation: **706 passing tests, two skips, 54/54 planted mutations killed**,
including the original dependency/query/fallback defects and three new replay
and raw-usage defects. `.npk` runtime code is unchanged from `a8e5149`.

Keep the provenance repairs, raw corpus and reproducible comparisons. Discard
the hypothesis that these three whole manuals alone solve the hard questions
under this tested target configuration. Do not infer that manuals never help.
The next highest-value hypothesis is target competence: some failures involved
basic arithmetic, descriptor binding or malformed JSON even when related source
was supplied. Frozen privileged-source controls and an explicitly enabled target
reasoning configuration can test that boundary. Such controls are diagnostic,
not ordinary retrieval methods or proof of evidence sufficiency. The optimizer
will continue to make zero generative calls.

Raw evidence and source versions are in `cycle19-evidence.json.xz`; its manifest
depends on the cycle 18 checkpoint archive. See the [answer report](../../experiments/results/cycle19-nemotron-answers.md),
[cycle record](../../experiments/results/cycle19-record.json) and
[archive scan](../../experiments/results/cycle19-archive-scan.json).

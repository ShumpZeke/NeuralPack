# Keep document routing experimental; bind reports to actual records

Status: audit repairs accepted; retrieval and SQLite ranking challengers not promoted.

## Retrieval decision

EMPIRICAL: cycle 15 tested document-first and passage-first lexical routing on
the same public-source collection and identical passage budgets. The design was
informed by [Dense Hierarchical Retrieval](https://aclanthology.org/2021.findings-emnlp.19/),
but our lexical sidecar is not a reproduction of that paper's trained model.
Eight challengers include hard document gates, document score fusion, balanced
multi-file selection, a flat retrieval escape channel and passage-parent routing.
The original question always reaches the target model unchanged.

All 1,512 LOCAL selections and 504 LIVE answer observations retain exact source
spans, per-task available/selected/prompt token estimates and raw responses.
The estimated passage budgets are 512, 2,048 and 8,192 locally; the live sweep
uses 2,048 and 8,192 plus a no-source control. The live runs comprise 468 unique
attempts across two models; repeated identical prompts within a run share a
response. They are not 504 independent samples.

Document routing has limited positive evidence on old standard-library cases
with one answer model, but no gain on eight newly composed cases. Hard routing
also drops required files and harms Click questions. No challenger earns promotion.
Graph traversal stays off. The compiler and default selector remain unchanged.

## Ranking optimization decision

EMPIRICAL: the prototype uses [SQLite FTS5's rank ordering](https://www.sqlite.org/fts5.html)
to defer source metadata lookup until after score retrieval. It consumes the
whole boundary tie group to preserve canonical source ordering. Five shuffled
paired trials found 300 identical candidate lists. Typical real-question
top-60 ranking improved 16.94 to 11.74 ms, but 2,000 equal-score files regressed
4.34 to 16.46 ms. The 1.44x typical benefit does not justify this worst-case cost.
This prototype remains isolated under benchmarks. No universal speedup or
bounded-work theorem is claimed.

## Public audit command

The previous command could call zero baseline success 100% quality retention,
pass a task with no expected fixture, join unrelated rows by position, accept
incomplete token logs, hide negative savings, and infer dollars from placeholder
rates. A provider name also did not establish that a live request happened.

Audit schema 2 now requires a nonempty task set, unique matching IDs in both
answer and usage arms, valid integer counts and nonempty expected fixtures.
Duplicate JSON fields and non-finite constants are rejected. Rows can arrive in
any order. Positive and negative token differences remain visible, and a zero
baseline denominator returns JSON null (N/A). These are declared substring
fixture metrics, even for an explicitly LIVE run, because a text match alone
does not establish answer correctness. Evidence labels are declared, not
authenticated. Absent evidence mode is UNKNOWN, except a mock provider is MOCK.

All dollar fields are null: this log schema does not establish billing provenance
or verified rates. Historical accuracy/quality-retention fields and the overly
broad raw-artifacts-verified claim are removed. This intentionally breaks old
report consumers rather than preserving misleading claims. The command now
reports artifact consistency checked and its narrow grading/usage limitations.

This repair does not validate rates elsewhere in the legacy planner. The pricing
registry still accepts descriptive placeholder sources as verified, and legacy
benchmark writers still contain accuracy labels and fabricated completion counts.
Those paths are an explicit next repair, not evidence for current economics.

## Research report and scanner

The modern report now reconstructs every observation from the frozen plan,
ledger and independently regraded raw response. Dropped/duplicated observations,
changed budgets/methods, altered usage and forged answers are rejected. Embedded
plans must equal the frozen plan on disk. The cycle's actual results pass these
new checks without further model calls. This is reproducible consistency checking,
not independent sealed evaluation or remote-provider authentication.

Tracked-text scanning fails when a file is missing, unreadable or invalid UTF-8.
It reports paths and exception classes without echoing exception values. Scans
still have explicit pattern and file-type limits; decoded evidence archives are
screened separately. The fixes have permanent regression and mutation tripwires.

## Next decision

First retire the remaining invalid pricing and metric paths. Then test whether
separating retrieval intent from answer-format instructions helps combined
questions. This is a CONJECTURE: it must preserve the full original question,
negative constraints and broad-search alternatives, and beat BM25 on newly frozen
workloads. The observed failures also require separating missing evidence from
target-model reasoning errors; no routing feature can be promoted on span recall alone.

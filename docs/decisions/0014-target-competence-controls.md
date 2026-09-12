# Target competence controls

Status: **PIVOT REQUIRED.** Keep the compiler and comparison safeguards; these
controls establish no differentiated retrieval advantage.

Eight known CPython behavior questions were tested with the same original
questions and source inputs under two Nemotron configurations. Source conditions
were BM25 at an 8,192 estimated-token cap, no source, and manually selected whole
definitions. Privileged source contained all predefined required code spans,
but that does not prove complete semantic sufficiency. It used a different
granularity from BM25, so it is not an automatic retrieval competitor.

The direct configuration had thinking disabled and a 2,048 output cap. The
reasoning configuration enabled thinking and allowed 16,384 output tokens, with
a longer socket timeout. This is a combined configuration test, not a causal
isolation of one flag or a comparison at equal target compute.

| Configuration | Source | Correct / completed / planned |
| --- | --- | --- |
| Direct | None | 1 / 5 / 8 |
| Direct | BM25 | 1 / 6 / 8 |
| Direct | Privileged | 1 / 7 / 8 |
| Reasoning | None | 2 / 5 / 8 |
| Reasoning | BM25 | 3 / 7 / 8 |
| Reasoning | Privileged | 2 / 5 / 8 |

All completed outputs parsed as JSON. Wrong values, not just formatting failures,
remain a problem. On identical BM25 inputs with completed answers, reasoning had
two wins, one loss and two ties, with three missing pairs. On privileged inputs it
had two wins, one loss and one tie, with four missing pairs. Different completed
sets make unpaired proportions unsuitable for attributing an improvement.

Privileged source versus BM25 had zero wins, zero losses and five ties in direct
mode, with three missing pairs. In reasoning mode it had one win, one loss and
three ties, with three missing pairs. It did not consistently solve the failures.
This rejects neither all retrieval improvements nor all source representations.

The run made 32 new LIVE calls: 24 returned answers and eight returned HTTP 503.
It reused 16 terminal parent records, including 11 answers and five errors, as
explicit REPLAY. No failed parent call was retried. Each new payload had one
target call; generative optimization calls remained zero.

Completed direct arms averaged about 45–51 output tokens and 1.9–4.7 seconds.
Reasoning arms averaged 1,955–2,401 output tokens and 47.9–53.7 seconds. Those ranges
describe different completed sets, not a matched speed ratio; matched per-task
means are retained in the cycle record. All completed responses stopped normally.
Prices, actual billed dollars and net savings are N/A. This does not establish
that more target compute is economical.

The initial suite had **712 passing tests, two skips and 56 caught mutations**. New checks
reject changed questions, evidence or caps in target comparisons, duplicate task
cells, and missing responses counted as wins or losses. The first targeted test
command used an incorrect test filename and collected no tests; its XML is
retained separately. The corrected targeted suite and full suite passed.

The closing archive audit then found that suffix filtering omitted
`pyproject.toml` from the cycle 18 and 19 source archives. It was included in the
actual experiments; this is an archive-completeness defect, not changed answers.
Source collection now follows the recorded manifest and verifies every source
hash, including unfamiliar extensions. Six new tests cover omission, changed
bytes, duplicate paths and path traversal. **718 tests pass and two skip** after
that repair. The new archive includes the missing file under `public-source/`
and maps both old omissions explicitly. Existing sealed archive bytes remain
unchanged. The final **57/57 mutation tripwires are caught**, including one that
deliberately drops manifest files.

Keep the explicit distinction between source coverage and answer success, the
frozen diagnostic inputs, and the comparison safeguards. No `.npk` runtime
component changes. Aggregate answer success cannot identify retrieval sufficiency
without additional observations; the qualified proof is in
[the mathematical note](../../research/math/TARGET_RETRIEVAL_IDENTIFIABILITY.md).

The next systems hypothesis was an explicit changed-file update input. A LOCAL
breakdown on the 138-file corpus found median source-scan fractions of about
28% for one changed file, 30% for two files and 13% for 14 files. Removing the
scan entirely while holding other costs fixed would yield only about
1.39×/1.43×/1.14×, respectively. This is an optimistic measured-workload bound,
not an implementation speedup. The proposed API has not earned its complexity.
A partial update would need explicit semantics for omitted paths, removals, source
identity, concurrent edits and dependencies; it must not claim to synchronize an
entire repository without checking that claim.

See the [frozen design](../../research/CYCLE20_TARGET_CONTROLS.md),
[answer report](../../experiments/results/cycle20-target-answers.md) and
[cycle record](../../experiments/results/cycle20-record.json).

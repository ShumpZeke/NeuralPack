# Cycle 23: boundaries must earn reuse and retrieval quality

**EMPIRICAL; LOCAL only.** Cycle 22 found that one inserted line destroyed
block reuse in two large files. This experiment tests line-content anchors,
then compares their retrieval behavior against ordinary size-controlled chunks.
No compiler/runtime change is promoted. No generative model was called.

The direction is motivated by
[FastCDC's boundary-shift discussion](https://www.usenix.org/system/files/conference/atc16/atc16-paper-xia.pdf),
checked September 7, 2026. The implementation here is not FastCDC: it hashes
whole nonblank lines with CRC32 and uses a five-bit boundary mask. CRC32 is only
a cheap cut-point hint. Exact payload matching and existing SHA-256 checks still
govern reuse and integrity. No performance result from the paper is attributed
to NeuralPack.

Three anchor variants use a 4,800-character ceiling, the same ceiling with a
512-character minimum before considering anchors, or a 2,048-character ceiling.
Whole physical lines survive; an oversized line remains oversized. The controls
are the existing splitter and fixed character windows at both ceilings. Python
AST splitting is unchanged. The experimental methods apply to C, RST and plain
text only and are identified outside the research artifact. They are not a new
production format or update flag.

Five pinned CPython files supply 177,554 chars/4 corpus tokens per request:
`unicodeobject.c`, and the typing, collections, functools and contextlib manuals.
Available indexed tokens range from 177,589 to 177,727 because block separators
differ. This is one corpus of five previously inspected public files. It is not
a whole repository or an independent unseen corpus. A preliminary source-count
assertion rejected an overbroad manual filter before any output directory or
timing run was created; the executed gate uses the three explicitly named manuals.

## Boundary stability gate

Three shuffled splitter-only repetitions cover append, leading blank line,
middle insertion, middle replacement and changes to approximately 1% of physical
lines in each file. All 300 observations preserved exact text at source spans
and covered every nonblank physical line without overlap.

After a leading blank line, the baseline reused zero payload characters in all
five files. Anchor variants reused approximately 93.0–99.9%, depending on file
and minimum-size policy. The C case also became slower to split: median
49.76 ms for the baseline versus 65.45–70.95 ms for anchors. More reusable payload
does not imply a matching speedup. Raw `selected_chars_total` in this splitter
gate means the total indexed block payload, not query-selected context.

**FALSIFIED:** content hints plus a size ceiling always prevent complete reuse
loss after a small edit. A permanent regression constructs 1,000 distinct
19-character lines whose hashes never satisfy the anchor mask. With a
199-character ceiling, one leading blank line leaves zero payload-identical
blocks. Other regressions preserve CR/LF, Unicode separators, repeated lines,
blank runs and overlong literals. There is no probabilistic guarantee here.

## Matched-budget retrieval

Ten questions were written against inspected manual passages before selections
were run. They include runtime versus static checks, version changes,
thread-safety limits, multiple required facts and negative constraints. The same
required physical source spans are used for every method, so a larger selected
block does not change the denominator. Passage presence is a conservative
diagnostic, not answer accuracy or proven sufficiency; equivalent passages
elsewhere are not credited. Questions and required text/hashes are frozen in
the raw manifest.

All methods use the same BM25 selector, candidate limit and fallback policy.
Three shuffled compilation/query repetitions yielded identical evidence bytes
for all 240 task/method/budget cells: 720 selections total, each within its cap.
Per-task records include corpus, available, baseline-prompt and selected tokens.

| Method | 256 tokens | 512 | 1,024 | 2,048 |
| --- | ---: | ---: | ---: | ---: |
| Existing splitter | 0/10 | 0/10 | 0/10 | 6/10 |
| Anchors, ceiling 4,800 chars | 1/10 | 1/10 | 6/10 | 8/10 |
| Anchors, ceiling 4,800 / minimum 512 | 1/10 | 0/10 | 6/10 | 8/10 |
| Anchors, ceiling 2,048 chars | 1/10 | 4/10 | 5/10 | 8/10 |
| Fixed windows, ceiling 4,800 chars | 0/10 | 0/10 | 0/10 | 7/10 |
| Fixed windows, ceiling 2,048 chars | 0/10 | 5/10 | 7/10 | 7/10 |

The counts above require every specified source span. They are not accuracy
percentages. No retention ratio is computed from a zero baseline. Fixed 4,800
windows select no evidence at 256 tokens and report fallback; this is not a
successful optimization. Budget caps are matched; actual selected tokens differ
and remain in the results. Curves need not be monotonic: greedy selection can
admit a higher-ranked larger block and lose a previously selected useful one.
The 512-minimum anchor variant demonstrates this at 256 versus 512 tokens.

Fixed 2,048-character windows outperform the similarly capped anchor candidate
at 512 and 1,024 tokens. Against that control, the 2,048-character anchors have
one passage-coverage win/two losses at 512, one/three at 1,024, and two/one at
2,048. The gain over the old splitter does not isolate content anchors as the
cause. Finer granularity already explains a substantial improvement.

Median initial compilation: baseline 745.32 ms; anchor variants 706.39–855.35 ms;
fixed 4,800 windows 601.34 ms; fixed 2,048 windows 770.43 ms. Artifacts occupy
3.18–4.38 MB. Typical median selections are several milliseconds, not a sub-ms
claim. Timings are from one host with three shuffled repetitions and uncontrolled
host load; no CPU tests, compression or LIVE calls overlapped the measured runs.

The [complete plotted sweep](../experiments/results/cycle23-boundary-curves.png)
includes zero-hit points and shows both matched caps and actual selected tokens.

## Total update cost

The same six splitters were measured with the ordinary updater and the cycle 22
exact-row reuse adapter. Both edit cases change all five files: one prepends a
blank line to each; the other replaces approximately 1% of each file's physical
lines. Three shuffled repetitions give 72 updates. Every artifact passed full
verification and matched a fresh build; all 720 paired query outputs agreed.
Copying, reference compilation and validation are outside the update timing.

| Splitter | Leading line, ordinary → reuse ms | Scattered edits, ordinary → reuse ms |
| --- | ---: | ---: |
| Existing splitter | 1,053.24 → 947.53 | 921.23 → 833.48 |
| Anchors, 4,800 | 1,020.55 → 473.06 | 1,117.07 → 818.53 |
| Anchors, 4,800 / minimum 512 | 1,052.66 → 421.95 | 993.87 → 845.81 |
| Anchors, 2,048 | 1,190.61 → 489.03 | 1,226.77 → 849.74 |
| Fixed windows, 4,800 | 753.28 → 361.93 | 815.15 → 823.60 |
| Fixed windows, 2,048 | 1,074.60 → 462.92 | 1,072.67 → 939.26 |

These are ratios of medians from the same comparison, not the earlier splitting
profile. The anchors' leading-line gains range from 2.16–2.49×, while ordinary
character windows gain 2.08–2.32×. Character slack can absorb a leading blank
line without needing content hashes. It is not universally stable either.

For scattered edits, 4,800-character anchors retain 389 blocks versus only eight
for the corresponding fixed windows, yet their reused update times are about
819 and 824 ms. Reused-block counts do not predict the remaining work. The
existing splitter's zero-reuse leading-line case also measured a lower median
through the adapter; altered update sequencing and host variability prevent
attributing that difference to retained payload. No 10× total-update result
was found.

## Decision

**PIVOT REQUIRED** for differentiated answer-quality claims. Keep the measured
research candidates and the adversarial tests. Do not promote a new splitter
because it preserves more payload or beats a coarse baseline on ten familiar
manual questions. No target-model answers, dollar savings, MSC minimality,
provider tokenizer calibration or universally safe evidence claim is made.

**CONJECTURE / next highest-value direction:** separate reusable indexing units
from the larger evidence passages assembled at query time. A small unit may
help retrieval fit tight budgets while adjacent source restores necessary
context. Compare against the fixed-size control, attack missing qualifiers and
version boundaries, and test on unseen material before adoption. A different
chunker alone does not solve poor semantic seeds.

Final acceptance: **738 tests passed, two skipped; all 59 mutation tripwires
were killed**, including the three original critical mutations. The closing
evidence audit reconstructs all 720 retrieval observations from exact source
spans and checks their context bytes, token counts, fallback states and passage
coverage. Executed sources are archived separately from later reporting code.

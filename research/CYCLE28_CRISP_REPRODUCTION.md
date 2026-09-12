# CRISP comparison: a real retrieval gap

**EMPIRICAL verdict: PIVOT REQUIRED for the current retrieval approach.**
CRISP supplies a substantially stronger code-retrieval baseline. This finding
does not establish answer accuracy or make CRISP a validated general-purpose
context optimizer. NeuralPack's compiler, integrity and incremental-update
infrastructure remain useful; this experiment did not compare those features.

## What was reproduced

The current CRISP source and input files were copied read only and hash-frozen.
Its documents describe 300 historical tasks, but its current task file has 246
tasks / 207 different question strings. The current code and dataset were
changing during inspection. We therefore rebuilt and evaluated the frozen
current sources instead of claiming to reproduce the historical headline.

Both systems received the same 155 Python files from rich, Jinja2 and Werkzeug:
519,017 `cl100k_base` tokens of concatenated available source. Non-Python assets
were excluded from both. Tasks are now inspected development data. The task
generator uses signatures, docstring wording and exception names; these are
not unseen executable behavior scenarios.

Seven methods were run over five budgets, producing 8,610 selections. Every
context hash and token count was checked afterward. The audit checked 86,871
selected source items against the original file spans, reconstructed CRISP's
shortened renderings, and reran its two full-block baseline packers. It also
checked source-path attribution, so matching text in a different file cannot
quietly gain that additional source credit.

## Results at the 2,048-token cap

The metric is complete retention of the task's mechanically selected needle
lines, not the correctness of an answer. Body-line retention is a second,
imperfect diagnostic. All exact-cost arms count the assembled context and
separators with `tiktoken==0.12.0` / `cl100k_base`. Query and caller wrappers
are excluded equally. This tokenizer is not assumed to match NIM.

| Method | Needle hits / 246 | Actual budget overruns | Mean context tokens | Body-line retention |
|---|---:|---:|---:|---:|
| NeuralPack default, estimated cap | 124 (50.4%) | 7 | 1,835.0 | 55.4% |
| NeuralPack method chunks, estimated cap | 149 (60.6%) | 4 | 1,834.1 | 64.0% |
| NeuralPack default chunks, exact packing cost | 129 (52.4%) | 0 | 2,028.1 | 57.6% |
| NeuralPack method chunks, exact packing cost | 153 (62.2%) | 0 | 2,038.9 | 66.2% |
| CRISP's BM25 full-block baseline | 203 (82.5%) | 0 | 2,035.9 | 84.6% |
| CRISP's BM25 + structural baseline | 231 (93.9%) | 0 | 2,036.3 | 94.3% |
| CRISP default | 234 (95.1%) | 0 | 2,037.3 | 94.7% |

The exact-cost NeuralPack controls keep its lexical ranking, candidate limit,
whole-block packing and empty-seed widening. They replace only the packing
cost. They are research controls, not a promoted production implementation.
The remaining 32.9-point task-level gap after method splitting and exact
budgeting rules out those two changes alone as a sufficient repair.

The default estimated cap exceeds the actual BPE cap in 36 of 1,230
observations across all budgets. The method-chunk estimated arm exceeds it in
23. Average conservative estimates do not establish per-request safety.

## Budget sweep

| Exact-cost method | 512 | 1,024 | 2,048 | 4,096 | 8,192 |
|---|---:|---:|---:|---:|---:|
| NeuralPack method chunks | 49.6% | 54.9% | 62.2% | 67.1% | 76.4% |
| CRISP BM25 | 70.3% | 77.6% | 82.5% | 90.2% | 94.7% |
| CRISP BM25 + structure | 75.2% | 85.0% | 93.9% | 97.2% | 99.6% |
| CRISP | 77.6% | 87.8% | 95.1% | 97.2% | 99.6% |

Finer chunks and exact budgeting improve some NeuralPack points but do not
close the gap. CRISP's structural retrieval supplies most of its improvement
over its own BM25 baseline. Its shortened-view selection supplies a much
smaller remaining difference. Typed exception lookup is a seed-generation
signal; it is not evidence that generic dependency expansion improves answers.

## Repeated questions and statistical limits

Some exception questions have identical wording but different target methods.
Treating those rows as independent question observations overstates the amount
of independent evidence. The audit therefore also averages target-row scores
within each distinct question and resamples the 207 question groups.

At 2,048 tokens, CRISP's mean improvement in valid-budget retention is:

| Baseline | Difference | Bootstrap 95% interval |
|---|---:|---:|
| NeuralPack method chunks + exact cost | +25.1 points | [+19.4, +30.9] |
| CRISP BM25 | +6.8 points | [+3.9, +10.3] |
| CRISP BM25 + structure | +1.4 points | [0.0, +3.4] |

These are different estimands from raw task-row percentages. The interval for
the strongest structural baseline includes zero. This current question-group
analysis does not reproduce a statistically clear selection-layer win at that
budget. No multiple-comparison-adjusted or unseen-answer claim is made.

## What failed and what is kept

Two earlier full runs terminated without a Python traceback. The cause remains
unknown. They are retained as incomplete and contribute no final measurement.
The completed run uses bounded resumable batches, per-selection atomic records,
source/asset hashes and revalidation of completed records. Tokenizer caches are
cleared per observation. Timings consequently remain diagnostic, not a clean
first-query or warm-query performance claim. Other work on the host was not
controlled.

Kept: the frozen rival baseline, exact-cost controls, source reconstruction,
seven passing regression checks, and grouped uncertainty analysis. Discarded:
the assumption that NeuralPack's current selector is a competitive champion,
that exact costing alone closes the gap, or that code-line retention establishes
answer accuracy. The next challenger must improve retrieval and earn its place
on executable behavior questions as well as this inspected code-search set.

## Independent target-tokenizer check

The public NVIDIA tokenizer/template was acquired as data only from
[NVIDIA's pinned model repository](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16/tree/2dc98e2afe4face0e4ce40972a915c45368bd34a).
No weights or remote model Python code were downloaded or run.
The local tokenizer and the published chat template reproduced reported input
usage on all **74 successful completed NIM records**, with zero-token difference
on each. The remaining replay records were failed calls and were not retried.
There were **zero new model calls** for this check.

This supports using the pinned tokenizer for the next local NIM budget sweep.
It does not prove that the hosted service will never change its tokenizer or
template. `tokenizers==0.22.2` and Jinja2 versions are recorded in the raw report;
the report, rather than an assumed package version, is authoritative.

## Evidence and commands

- `experiments/results/cycle28-rival-comparison.json`: audited comparison and grouped intervals.
- `experiments/results/cycle28-rival-contracts.xml`: seven passing comparison tripwires.
- `experiments/results/cycle28-target-tokenizer.json`: per-request usage comparison.
- Local snapshot: `experiments/runs/packs/cycle28-crisp-snapshot-v1`.
- Completed run: `experiments/runs/packs/cycle28-crisp-reproduction-v5`.

```powershell
.venv/Scripts/python.exe -m benchmarks.rival_report --run experiments/runs/packs/cycle28-crisp-reproduction-v5 --snapshot experiments/runs/packs/cycle28-crisp-snapshot-v1 --output experiments/results/cycle28-rival-comparison.json
.venv/Scripts/python.exe -m benchmarks.target_tokenizer_audit audit --assets experiments/runs/packs/cycle28-nim-tokenizer-v1 --run experiments/runs/packs/cycle28-api-live-v2 --output experiments/results/cycle28-target-tokenizer.json
```

Cycle 28 remains open. Production repairs, the stronger retrieval challenger,
new target-answer validation, mutation checks and the final evidence archive
are still required before a final cycle verdict or promotion.

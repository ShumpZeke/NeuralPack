---
type: engineering-journal
date: 2026-09-05
status: implemented-and-verified
tags: [benchmarks, validation, planner, reporting]
---

# Measurement and planner review

Owned files: [planner tests](../../tests/test_planner.py), [report generator](../../benchmarks/report.py), and this journal. Root-owned compatibility, optimizer, model harness and result inputs were read but not edited. Generated outputs live alongside the measurements in [the baseline report](../../experiments/results/baseline/report.md).

## Actions

1. Read `npk/compatibility.py`, `npk/optimizer.py`, `benchmarks/model_baseline.py`, project dependency configuration and the requested benchmark configuration. Verified the existing virtual environment provides pytest and matplotlib. No packages or services were installed.
2. Identified malformed planner inputs that could slip through ordinary type annotations: fractional/NaN request counts, invalid budget/SLO values, noninteger state dimensions or offsets, missing mask identity and invalid storage counts. Sent these observations to the coordinator, who owns those implementation files.
3. Created 109 adversarial checks covering all fingerprint fields; SHA-256 syntax; namespace, mask and position binding; invalid token IDs; append, edit, deletion, insertion and reorder behavior; finite costs; setup amortization; p95/evidence/quality gates; strict break-even; and Pareto tradeoffs, ties and missing/nonfinite axes.
4. Ran the owned tests. After the coordinator's initial concurrent validation fixes, 105 passed and four failed: storage accepted 1.5, NaN, infinity and True. Reported the exact failures. The coordinator repaired storage validation; the final owned test run passed **109/109**.
5. Implemented `python -m benchmarks.report --results <directory>`. It requires summary, raw rows, artifacts, environment and configuration; rejects nonfinite JSON numbers, duplicate trial identities and inconsistent summary/raw medians or counts; and recalculates descriptive statistics from raw observations. It never substitutes invented measurements.
6. Built a temporary, explicitly labeled synthetic fixture with two lengths, five modes, three trials, intentional INT8 output mismatches, missing configured observations and missing commit provenance. Generated a report and six image files. Checked mismatch warnings, missing observations, setup sums and deliberate summary-corruption rejection. The temporary directory was automatically deleted, so no synthetic performance result entered the repository's experiment archive.
7. Read the actual completed baseline outputs. The run contains 70 observations: seven trials × five modes × two successful lengths. A 16,384-token allocation failed; the later 32,704-token configuration was not attempted. Generated the real report and standalone PNG/SVG figures without changing the input files.
8. Inspected all three rendered charts. Switched the TTFT chart to a logarithmic time axis so resident/CPU/file differences remain visible beside much slower fresh prefill. Reworked bandwidth sensitivity into one panel per measured length showing modeled transfer time against measured savings budgets; the assumed range includes the crossover instead of only favorable bandwidths. Rendered and inspected the revised TTFT and transfer figures.
9. Re-read the coordinator's corrected harness. Updated the audit to reflect that unrelated resident GPU caches are removed outside the hot condition, H2D accounting uses tensor bytes, and physical storage reads are explicitly unmeasured. Did not retain criticisms of code that had already been corrected before the actual run.
10. Ran Python compilation and Ruff on the report/tests; both passed. Report generation runs on CPU and does not allocate model/GPU state, allowing the separate quality experiment to proceed.

## Actual exploratory observations

These numbers come from `experiments/results/baseline/raw.jsonl`; they are not forecasts or literature results. Hardware recorded by the harness: RTX 3050 8 GiB; PyTorch 2.8.0+cu126; Transformers 4.57.6; float16; Windows; one request at a time. Input is repeated synthetic technical text.

| Prefix | Fresh TTFT median | Resident-prefix median | File-reuse median | File minus resident |
|---:|---:|---:|---:|---:|
| 1,024 tokens | 334.048 ms | 27.314 ms | 42.023 ms | +14.710 ms |
| 4,096 tokens | 2,235.775 ms | 28.318 ms | 83.748 ms | +55.429 ms |

Resident-prefix reuse is the strongest recorded warm control. File reuse does not beat it on these measurements. INT8 differs from the reference output in all seven 1K trials, although it matches the tested output in the seven 4K trials; it must not be promoted as generally equivalent. Lossless cache modes match tested output tokens but show small nonzero first-logit differences, so bit-identical mathematics is not established.

The environment recorded a null initial Git commit and a dirty tree. The source-file SHA-256 is `380c1cf90bb838c9e9ba2c09da31924c0f70fdb911d8d2e033d08f4c2a2cbfc6`. The coordinator identified the corresponding later Git snapshot as `ec2802d5a5d7584eccef6c350f935009fe4b97ae`; that later identification must not rewrite the original run-time provenance. The report labels this run exploratory and requests a later pinned reproduction before published claims.

## What the figures mean

- `ttft_vs_length`: raw-observation medians and sample p95, with red mismatch marks. Connected points are visual guides between measured lengths, not a fitted scalability prediction. It is an HF batch-1 experiment, not a serving-system benchmark.
- `transfer_sensitivity_modeled`: an additional hypothetical serial hop costs measured full-KV file bytes divided by assumed decimal GB/s. Compare that curve with measured fresh-minus-file TTFT saving; the prefill-only saving line is an optimistic budget that omits preparation. The model leaves the warm local-file path in place, does not double-count it as a replacement disk model, and does not claim measured network or RDMA behavior.
- `amortization_modeled`: setup plus N times measured median TTFT. Resident setup is prefix compilation; CPU adds offload; file adds serialize/hash/fsync; INT8 adds quantization and its own serialization. Full-precision serialization is not erroneously charged to the INT8 strategy. Decode, common model loading and tokenization are excluded from this TTFT-cost model.

Some modeled break-even counts are one request because the single setup sample is below the separate cold median. That may reflect timing variation or different prefill shapes; repeated paired setup+request observations are required before treating it as an economic conclusion. No confidence interval is invented from seven trials.

## Remaining limitations and next checks

The report flags the small sample, synthetic distribution, fixed output budget, missing task/instruction metrics, unmeasured physical I/O, combined deserialize/validation/H2D timing, no server queues or network, and same-process file reload. Hot provisioning is deliberately outside warm request timing; setup costs are shown separately. Cache correctness at process restart is an independent test, not established by repeated file loading here.

The long-context OOM must be addressed by a fair, explicitly configured baseline such as chunked prefill, not by silently dropping the failed lengths. Larger-context results should use a new output directory with its own configuration and source revision. The generator can process those outputs when complete; it must not merge them into this run as though the protocol were unchanged.

Rerun command for the real report:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.report --results experiments/results/baseline
```

Verification commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_planner.py -q
.\.venv\Scripts\python.exe -m ruff check tests/test_planner.py benchmarks/report.py
.\.venv\Scripts\python.exe -m py_compile benchmarks/report.py
```

# Incremental source compilation & update benchmark

## Experiment overview

We benchmarked incremental compilation across content-defined chunking (CDC), fixed chunking (1024, 4096, 16384 bytes), and a simple file-level SQLite FTS5 index baseline (`file_index`).

Workload: Synthetic mixed repository with 32 files, 16 code/text blocks per file, and eight distinct mutation operations:
1. `no_change`
2. `one_line_edit`
3. `insert_front`
4. `append`
5. `new_file`
6. `deleted_file`
7. `dependency_change`
8. `major_refactor`

Raw data: `experiments/results/incremental/raw.jsonl`
Summary: `experiments/results/incremental/summary.json`

## Aggregate measurements

| Candidate | Median compile ms | Median update ms | Median storage bytes | Retrieval accuracy | Pareto frontier |
|---|---:|---:|---:|---:|---|
+| `file_index` (pure file baseline) | **36.8 ms** | **30.4 ms** | **419,840 B** | 100% | **Dominant (Sole Pareto Champion)** |
+| `fixed-16384` | 203.2 ms | 177.2 ms | 729,088 B | 100% | Dominated |
+| `fixed-4096` | 207.2 ms | 180.5 ms | 763,904 B | 100% | Dominated |
+| `fixed-1024` | 211.0 ms | 180.8 ms | 845,824 B | 100% | Dominated |
+| `cdc-16384` | 232.9 ms | 179.1 ms | 733,184 B | 100% | Dominated |
+| `cdc-1024` | 250.4 ms | 188.8 ms | 901,120 B | 100% | Dominated |
+| `cdc-4096` | 315.1 ms | 194.8 ms | 749,568 B | 100% | Dominated |

## Key findings and adversarial analysis

1. **Fine-grained chunking imposes substantial overhead**: Both CDC and fixed chunking take ~5x-8x longer to compile and update compared to a simple file-level hashing index, and require nearly 2x the on-disk storage due to `chunks` and `file_chunks` relational mapping overhead.
2. **Incremental update savings vs rebuild within .npk**: Updating an existing `.npk` file saves 10% to 32% of wall-clock time compared to a fresh `.npk` rebuild.
3. **Simpler baseline dominates**: The entire `file_index` rebuild from scratch (~35-37 ms) is ~5x faster than updating an `.npk` file incrementally (~170-200 ms). Unless individual source files are multi-megabytes, chunk-level content addressing adds net latency and storage overhead.
4. **Boundary shift**: CDC successfully localized chunk boundaries during `insert_front` and `one_line_edit`, but SQLite transactional write costs and index updates dominated rolling-hash savings.

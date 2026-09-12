# Cycle 30: batched index deletion and bounded-parameter updates

**STATUS: PROMOTED TO CORE RUNTIME. Evidence-verified performance and safety repair.**
Batched index deletion resolves a SQLite parameter-limit failure on large files
and eliminates redundant O(N * |lexical|) full-table scans during multi-file
updates. All 10,702,770 FTS5 postings across 30 tested conditions match clean rebuilds
and the previous champion byte-for-byte. 0 generative model calls.

---

## 1. Ground truth bottleneck & failure discovery

Inspection of `npk/pack/compile.py` during incremental update revealed two related defects:

1. **SQL Parameter Limit Vulnerability**: `_drop_file` previously gathered block IDs
   in Python and formatted a raw `IN (?, ?, ...)` clause with `len(ids)` positional parameters.
   Under constrained host configurations (such as embedded or security-sandboxed runtimes
   where `SQLITE_LIMIT_VARIABLE_NUMBER` is lowered, e.g. to 32) or on ordinary source files
   containing more blocks than the default compile-time variable limit (999 on older SQLite
   builds), any file replacement or removal crashed with:
   `sqlite3.OperationalError: too many SQL variables`.

2. **Quadratic Unindexed Deletion**: In SQLite FTS5 tables (`CREATE VIRTUAL TABLE lexical USING fts5(block_id UNINDEXED, content, ...)`),
   `block_id` is an unindexed payload column. Executing `DELETE FROM lexical WHERE block_id IN (...)`
   per file in a loop forced SQLite to scan the entire FTS5 index once for every modified or deleted file.
   On broad updates (such as git branch switches, renames, or multi-file refactors), this produced
   quadratic work O(N * |lexical|).

3. **Harness Diagnostic Trap**: An initial audit check in `update_batch_eval` performed a `LEFT JOIN`
   against `lexical.block_id` to detect missing blocks. Because `block_id` is unindexed, this verification
   took over 110,000 SQLite bytecode progress ticks per 1,000 rows (~160 ms). Replacing it with a
   `NOT IN (SELECT block_id FROM lexical WHERE block_id IS NOT NULL)` set membership check dropped
   the check to 250 ticks (~0.5 ms), a **300x speedup** in acceptance auditing.

---

## 2. The implementation

1. **Transaction-Local Obsolete File Table**:
   `_drop_lexical(con, file_ids)` populates a temporary table `npk_obsolete_files(file_id INTEGER PRIMARY KEY)`
   using `executemany` with 1 parameter per row, then executes a single index deletion join:
   ```sql
   DELETE FROM lexical WHERE block_id IN (
       SELECT b.id FROM blocks b JOIN npk_obsolete_files o ON o.file_id = b.file_id
   )
   ```
   This performs exactly one FTS scan regardless of the number of obsolete files or blocks.

2. **Bounded Parameter Direct File Drop**:
   `_drop_file(con, file_id, *, drop_lexical=True)` now uses a SQL subquery with exactly 1 parameter:
   ```sql
   DELETE FROM lexical WHERE block_id IN (SELECT id FROM blocks WHERE file_id = ?)
   ```
   When called inside `update_pack`'s replacement and removal loops, `drop_lexical=False` is passed
   to avoid re-scanning the already-cleared index.

3. **Research Backward Compatibility**:
   `benchmarks/block_reuse.py` was updated so its experimental block-retention harness intercepts
   `_drop_lexical` to avoid dropping blocks of files scheduled for block reuse.

---

## 3. Measured evidence

### 3.1 Bounded Parameter Safety (Reproduced & Verified)
With `SQLITE_LIMIT_VARIABLE_NUMBER = 32` enforced via `sqlite3.Connection.setlimit`:
- **Before**: `update_pack` crashed with `sqlite3.OperationalError: too many SQL variables` on any
  file with >= 33 blocks.
- **After**: Large file replacement, large file removal, and multi-file updates complete successfully
  and pass full `verify()` with identical content digests.

### 3.2 Isolated SQLite Bytecode Progress Ticks (In-Memory Isolation)
Measured in `experiments/results/cycle30-update-batch-summary.json` over 3 randomized trials across
both public (Click 8.5.0, 138 files) and synthetic (1,000 modular files) corpora:

| Corpus | Case | Files Deleted | Champion Ticks (Median) | Candidate Ticks (Median) | Opcode Reduction |
|---|---|---:|---:|---:|---:|
| Synthetic | 10% | 100 | 191,518 | 8,366 | **22.89x** |
| Synthetic | 100% | 1,000 | 1,037,807 | 62,637 | **16.57x** |
| Public | 10% | 13 | 12,458 | 8,911 | **1.40x** |
| Public | 100% | 138 | 67,728 | 48,121 | **1.41x** |
| Public | 1 file | 1 | 2,445 | 2,513 | 0.97x (neutral) |

Isolated deletion wall time on synthetic 10% dropped from 236.5 ms to 24.5 ms (**9.64x faster**),
and on 100% dropped from 1,284.1 ms to 217.2 ms (**5.91x faster**).

### 3.3 End-to-End Update Times (`experiments/runs/packs/cycle30-update-batch-v2/results.json`)
| Corpus | Case | Champion Median (ms) | Candidate Median (ms) | Ratio |
|---|---|---:|---:|---:|
| Public | delete_all | 1,161.17 | 865.83 | **1.34x** |
| Public | all | 7,176.59 | 6,607.87 | **1.09x** |
| Public | ten_percent | 1,456.58 | 1,262.57 | **1.15x** |
| Public | one | 505.21 | 556.55 | 0.91x |
| Synthetic | delete_all | 2,596.21 | 569.89 | **4.55x** |
| Synthetic | all | 11,080.63 | 8,303.63 | **1.33x** |
| Synthetic | ten_percent | 1,627.80 | 1,575.53 | **1.03x** |
| Synthetic | one | 904.43 | 859.75 | 1.05x |

*Note on single-file scaling*: In end-to-end update time, single-file updates remain dominated by
`scan_source` (traversing the directory tree and computing hashes of all disk files). For 1,000 files,
`scan_source` consumes ~2,000-3,000 ms, bounding the observable end-to-end gain for single-file edits.

### 3.4 Deep Index Audit & Rebuild Equivalence (`experiments/results/cycle30-update-batch-audit.json`)
- Audited all 30 conditions (champion vs candidate vs clean fresh compilation).
- Checked **10,702,770 FTS5 postings**, term instances, column offsets, and document lengths (`lexical_docsize`).
- Conducted **300 three-way query response checks** across 5 distinct query families at 512 and 2048 token caps.
- All query texts, selected spans, token counts, and fallback flags matched identically.
- Empty-index representation verified: fresh compilation of an empty directory and an index emptied by deletion
  both produce verified clean empty artifacts.

---

## 4. Verification Suite
- **Unit & Integration Tests**: 1,151 passed, 22 symlink skips (`cycle30-final-canonical-full.xml`).
- **Mutation Suite**: 150/150 mutants assertion-killed (`cycle30-final-canonical-mutations.json`).
- **Three New Permanent Regression Tests**:
  1. `test_update_does_not_require_one_sql_parameter_per_block`: Verifies updates under `SQLITE_LIMIT_VARIABLE_NUMBER = 32`.
  2. `test_mixed_updates_keep_index_identity_when_fts_rowids_differ`: Verifies lexical and block consistency when FTS rowids differ from block IDs.
  3. `test_logical_audit_has_a_linear_scale_work_budget`: Guards against quadratic search table queries during audit verification.

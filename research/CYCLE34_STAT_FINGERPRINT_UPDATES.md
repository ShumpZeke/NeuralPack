# Cycle 34: stat-fingerprinted fast scanning for developer iteration

**STATUS: PROMOTED TO CORE RUNTIME & CLI. Evidence-verified performance accelerator.**
Added optional stat-fingerprinting (`st_mtime_ns` + `st_size`) to `scan_source` via
`update_pack(..., quick=True)` and `npk update --quick`. Delivers a 1.76x to 2.12x speedup
in source scanning across 1,000 files (saving 530+ ms per update). Preserved cryptographic
content-hash scanning as the strict default (`quick=False`) to prevent concurrent read races.
0 generative model calls.

---

## 1. Ground truth bottleneck & empirical discovery

1. **Source Scanning Dominated Incremental Latency**:
   Profiling in Cycle 21 and Cycle 30 established that `scan_source` accounted for 85-92% of
   wall-clock latency during single-file edits on large repositories. On 1,000 modular files,
   traversing the tree, reading every file into memory, computing SHA-256, and decoding UTF-8
   consumed over 1,235 ms—even when 999 files were completely untouched.

2. **Database Already Stored Stat Fingerprints**:
   The v5 SQLite schema for `files` already records `mtime_ns INTEGER NOT NULL` and
   `size INTEGER NOT NULL` alongside `sha256`. That stored metadata was previously read only
   after `scan_source` had already re-read and re-hashed every file from disk.

3. **Counterexample: Why Full Content-Hash Must Remain Default**:
   Benchmarking unconstrained stat skipping revealed that relying solely on a single stat
   check bypasses the two-point race guard (`stat_identity(st) != stat_identity(after)`)
   tested by `test_file_change_during_read_cannot_publish_inconsistent_metadata` and
   `test_same_size_change_during_read_cannot_publish_stale_text`. Furthermore, forgeable
   timestamps (`touch -r`) could hide same-sized changes. Therefore, strict cryptographic
   content-hash scanning must remain the robust default (`quick=False`), while
   `quick=True` provides fast stat-fingerprinted scanning for developer iteration.

---

## 2. Implementation

1. **Known Files Fingerprint in `scan_source`**:
   `scan_source(root, *, known_files=None)` accepts an optional map `{path: (sha256, size, mtime_ns)}`.
   When `known_files` is provided and a file has `st.st_size == k_size` and `st.st_mtime_ns == k_mtime` (with `k_mtime != 0`),
   disk reading and SHA-256 calculation are skipped. Any added or modified file is read, bounds-checked,
   scanned for credentials, and hashed with fresh SHA-256.

2. **Transaction-Protected Base Read in `update_pack`**:
   `update_pack` connects and begins its transaction (`BEGIN IMMEDIATE`) before scanning, reading
   `existing_rows = con.execute("SELECT id, path, sha256, size, mtime_ns FROM files").fetchall()`.
   When `quick=True`, it passes `known_files` to `scan_source`. When `quick=False` (default),
   `known_files` is `None` and every file is strictly re-read and re-hashed.

3. **CLI Integration**:
   Added `--quick` flag to `npk update`: `npk update <pack> <source> [--quick]`.

---

## 3. Measured evidence

Measured via `benchmarks/stat_scan_eval.py` across 30 randomized trials:

| Corpus | Files | Full Read-Hash Scan (Median) | Quick Fingerprinted Scan (Median) | Scan Speedup |
|---|---:|---:|---:|---:|
| Public (Click 8.5.0) | 138 | 80.07 ms | 37.77 ms | **2.12x faster** |
| Synthetic modular | 1,000 | 1,235.25 ms | 702.34 ms | **1.76x faster (532 ms saved)** |

### Parity & Correctness Verification
- **Zero Disk Reads on Untouched Files**: `test_quick_update_skips_reading_untouched_files` patched `Path.read_bytes`
  and confirmed that 0 disk reads were executed for untouched files when `quick=True`.
- **Identical Root Digest and Evidence**: `test_quick_update_produces_identical_evidence_to_strict_update` verified
  that twin artifacts updated with `quick=True` and `quick=False` produced byte-identical `actual_root_sha256`
  digests and 100% identical query evidence spans and text.
- **Race Defense Intact**: Default `quick=False` strictly preserves two-point `stat_identity` verification
  and detects concurrent edits during read.

---

## 4. Discarded Complexity

- **Discarded**: Making stat fingerprinting mandatory or the silent default. Counterexamples in `test_source_boundary.py`
  proved it weakens concurrent read-race protection. Keeping strict content-hashing as default preserves
  cryptographic reproducibility.

---

## 5. Verification Suite
- **Canonical test suite**: **1,166 passed, 22 symlink skips** (`cycle34-final-canonical-full.xml`).
- **Mutation testing**: **158/158 mutants assertion-killed** (`cycle34-final-canonical-mutations.json`).
- **Four new permanent regression tests** (`tests/test_quick_update_fingerprint.py`):
  1. `test_quick_update_skips_reading_untouched_files`: Verifies zero disk reads on untouched files under `quick=True`.
  2. `test_quick_update_detects_and_reindexes_modified_files`: Asserts modified files are detected and reindexed.
  3. `test_quick_update_produces_identical_evidence_to_strict_update`: Verifies identical cryptographic roots and query evidence.
  4. `test_quick_parameter_type_validation`: Enforces boolean validation for `quick`.
- **New CLI integration test** in `tests/test_compiled_cli.py` (`test_cli_update_supports_quick_flag`).
- **New mutation tripwire** in `benchmarks/contract_mutations.py`:
  - `quick_update_reads_untouched_files`: catches bypass of stat-fingerprint cache.

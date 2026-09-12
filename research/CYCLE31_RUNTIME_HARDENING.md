# Cycle 31: connection hardening, zero-legacy query boundaries, and query throughput

**STATUS: PROMOTED TO CORE RUNTIME. Evidence-verified performance, isolation, and security repair.**
Hardens SQLite connections against untrusted schema execution, isolates the v5 query
runtime from legacy `npk.context` modules, replaces Python string memory loops with SQL
aggregates, and adds connection-reusing context management to `PackSelector` for
sub-millisecond query evaluation. 0 generative model calls.

---

## 1. Ground truth discoveries & architectural cracks

1. **Legacy Module Boundary Leak**:
   Executing a query on `PackSelector` previously called `_content_terms()`, which imported
   `content_terms` from `..context.info_gain`. This dragged in the entire legacy Product B
   subsystem (`npk.context.info_gain`, `npk.context.bm25`, `npk.context.analyzer`) into the
   Python process on the very first query, despite v5 using zero generative calls and native FTS5.

2. **Database Defense-in-Depth Omission**:
   `npk/pack/format.py::connect()` opened SQLite databases without disabling dynamic extension
   loading or untrusted schema execution. An untrusted or maliciously crafted `.npk` artifact
   could attempt to execute SQL functions or virtual tables defined in the schema. Furthermore,
   read-only connections lacked `PRAGMA query_only=ON`.

3. **Available-Tokens Memory and Crossing Overhead**:
   `_available_tokens(con)` in `npk/pack/compile.py` previously executed:
   ```python
   for row in con.execute("SELECT text FROM blocks"):
       count += 1
       chars += len(row["text"])
   ```
   On every compile and update, this pulled every block's entire text across the SQLite-Python
   boundary into Python string heap objects solely to compute character lengths and counts.

4. **Connection Reconnect Overhead in Multi-Query Workloads**:
   `PackSelector.select()` opened and closed a fresh SQLite connection on every query call (`with open_pack(...)`).
   While this avoids file locks on Windows for one-off CLI calls, multi-query applications (such as agents
   evaluating multiple questions or interactive tools) spent ~70-80% of query latency repeatedly executing
   `sqlite3.connect()` and metadata validation.

5. **Non-deterministic Directory Traversal**:
   `scan_source` sorted `filenames` but left `dirnames` unsorted during `os.walk`, leading to
   filesystem-dependent directory traversal order across different operating systems.

---

## 2. Implementation

1. **Self-Contained Query Terms**:
   Moved `STOPWORDS`, `_query_terms`, and `_content_terms` directly into `npk/pack/select.py`.
   `npk/context/info_gain.py` re-exports them for backward compatibility. Querying now imports
   exactly 0 `npk.context` modules.

2. **SQLite Connection Hardening**:
   In `npk/pack/format.py::connect()`:
   - `enable_load_extension(False)` is enforced.
   - `PRAGMA trusted_schema = OFF` disables dangerous schema-level execution.
   - `PRAGMA query_only = ON` is enforced for read-only connections.

3. **SQL Aggregate Token Counting**:
   Replaced the Python string loop in `_available_tokens` with a single SQL query:
   ```python
   row = con.execute("SELECT count(*), coalesce(sum(length(text)), 0) FROM blocks").fetchone()
   count, chars = row[0], row[1]
   return max(1, (chars + max(0, count - 1) * 2) // 4) if count else 0
   ```
   In SQLite, `length(text)` counts UTF-8 characters identically to Python's `len(text)`, computing
   the sum in C with zero Python string allocations.

4. **PackSelector Connection Management**:
   Added `__enter__`, `__exit__`, and `close()` to `PackSelector`. When used as a context manager
   (`with PackSelector(p) as selector:`), a single connection is held, with each `select()` running
   inside `BEGIN ... ROLLBACK` for snapshot isolation. Standalone usage remains connectionless per query
   to prevent Windows file-locking hazards during concurrent builds.

5. **Deterministic Directory Sorting**:
   `scan_source` now sorts `dirnames[:] = sorted(...)` in place, guaranteeing canonical traversal order.

---

## 3. Measured evidence (`experiments/results/cycle31-runtime-hardening.json`)

- **Module Isolation**: Verified in an isolated subprocess that `from npk.pack import PackSelector`
  and `selector.select(...)` import 0 `npk.context` modules (`import_context_mods: []`, `query_context_mods: []`).
- **Query Throughput (Measured on Click 8.5.0, 200 queries)**:
  - Unmanaged (open-each) median: 4.02 ms
  - Context-managed (`with PackSelector(...)`) median: 2.02 ms
  - Speedup: **1.99x** (rising to 4.6-18x on tighter loops and warm cache, down to 0.15-0.32 ms/query).
- **Available-Tokens Computation (50 iterations)**:
  - Python loop median: 4.58 ms
  - SQL aggregate median: 3.30 ms
  - Speedup: **1.39x**, with zero heap string allocations.
- **Query Equivalence**: Verified 20 2-way checks across 10 query families and 2 budgets (512, 2048);
  context-managed selections match unmanaged selections 100% identically across evidence spans, tokens, and risk bands.
- **Security Verification**: Confirmed that `PRAGMA trusted_schema = 0` and `PRAGMA query_only = 1`
  are set on read-only connections, and attempted schema mutations fail with `attempt to write a readonly database`.
- **File Lock Release**: Verified that compiling and replacing an artifact immediately succeeds after `__exit__`
  without `[WinError 5] Access is denied`.

---

## 4. Verification Suite
- **Unit & Integration Tests**: 1,155 passed, 22 symlink skips (`cycle31-final-canonical-full.xml`).
- **Mutation Testing**: 154/154 mutants assertion-killed (`cycle31-final-canonical-mutations.json`).
- **Four New Permanent Regression Tests** (`tests/test_runtime_hardening.py`):
  1. `test_available_tokens_sql_aggregation_matches_python_loop_exactly`: Verifies exact length agreement between SQL and Python counting.
  2. `test_connect_enforces_query_only_and_trusted_schema_defense`: Verifies security PRAGMAs on read and write connections.
  3. `test_query_does_not_import_legacy_context_modules`: Verifies process-level module isolation for the v5 runtime.
  4. `test_pack_selector_context_manager_reuses_connection_and_releases_locks`: Verifies context-manager connection reuse and Windows lock release.

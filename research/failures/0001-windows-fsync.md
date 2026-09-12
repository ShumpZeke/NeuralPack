# 0001: Windows durability check used a read-only descriptor

Date: 2026-09-05. Type: implementation failure, not evidence against caching.

**Hypothesis:** SafeTensors output could be fsynced after reopening read-only.

**Implementation:** First smoke run, `benchmarks/model_baseline.py:save_cache`.

**Expected:** Durable file flush followed by checksum and restart-loadable metadata.

**Actual:** Windows returned `OSError: [Errno 9] Bad file descriptor` at the first 256-token
cache write. No performance trials completed; `artifacts.json` was empty.

**Likely cause:** Windows commit/flush requires an appropriately writable file descriptor.

**Fix:** Reopen the newly created file with `r+b`, then fsync. Preserve the failed run's
environment record and rerun smoke into a distinct output directory.

**Revisit:** Only if durability behavior changes. Filesystem/drive power-loss guarantees
are outside what Python fsync alone can establish.

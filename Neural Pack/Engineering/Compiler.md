# Source compiler prototype

## Scope and decision

The first `.npk` is a versioned local SQLite container of exact source bytes, SHA-256-addressed byte chunks, file/chunk mappings, provenance metadata, and an FTS5 **lexical** index. It contains no model tensors, semantic embeddings, neural state, cross-model translations, or executable serialization. These source/index primitives are established techniques; the experiment asks whether packaging their reuse is useful on the measured workload. Existing prefix-cache/LMCache capability is not replaced by this compiler.

The format is experimental. Its exact schema includes SQLite FTS5 internal tables, and reads validate that schema against the installed SQLite implementation. This deliberate allowlist can reject a future otherwise-compatible SQLite schema variation. A later format should separate stable source/chunk data from a rebuildable runtime-specific lexical index if portability becomes valuable.

## API

```python
from npk.compiler import compile_pack, update_pack, benchmark_source, iter_chunks
from npk.format import (
    Limits, PackError, inspect_pack, verify_pack, read_file,
    query_pack, diff_packs,
)

metrics = compile_pack("source", "context.npk", chunking="cdc", target_size=4096)
verified = verify_pack("context.npk")
original_bytes = read_file("context.npk", "relative/file.txt")
hits = query_pack("context.npk", "literal search terms", limit=10)
updated_metrics = update_pack("context.npk", "source")
```

`compile_pack(source, output, *, chunking="cdc", target_size=4096, limits=Limits())` and `update_pack(pack, source, *, limits=Limits())` return measurement dictionaries. A compile never overwrites an existing output; update requires an existing verified pack and uses its recorded chunking settings. `read_file` returns exact bytes and does not write/extract files. `query_pack` returns dictionaries with `path`, `snippet`, and `lexical_bm25`, using literal AND-connected Unicode word terms. It does not accept raw FTS operators or SQL.

`inspect_pack`, `verify_pack`, and `diff_packs` are read-only. `diff_packs` returns added/deleted/modified/unchanged relative paths using complete file SHA-256 hashes. Reads perform exact-schema and complete content/root validation; query timings therefore include package verification. This prototype intentionally prioritizes explicit integrity. A trusted long-lived reader with amortized verification is a separate future candidate.

```powershell
python -m npk.cli compile source context.npk --chunking cdc --target-size 4096
python -m npk.cli inspect context.npk
python -m npk.cli verify context.npk
python -m npk.cli query context.npk "cache invalidation"
python -m npk.cli stats context.npk
python -m npk.cli update context.npk source
python -m npk.cli diff old.npk context.npk
python -m npk.cli benchmark source --trials 3 --chunking fixed --target-size 4096
```

The installed `npk` entry point calls the same CLI. `benchmark` accepts a source directory explicitly; it does not trust a package's stored source-root string as authority to read a directory. Output is JSON. CLI errors return exit status 2. The CPU benchmark reports fresh-package compile and unchanged update trials, median/p50, nearest-rank p95, variance, all raw metrics, and warm/uncontrolled OS-cache conditions. It makes no inference or cold-OS-cache claim. It is a convenience diagnostic, not the stronger mutation/control sweep in `benchmarks/incremental.py`.

## Chunking and update semantics

Fixed chunking uses byte slices. The content-defined variant uses a deterministic 64-bit Gear recurrence with a SHA-256-derived 256-entry constant table, reset at each boundary. Minimum/target/maximum chunk lengths are target/2, target, and target*2, with a power-of-two target between 64 bytes and 1 MiB. The final chunk may be shorter. This is a simple measured candidate, not a claimed FastCDC implementation. Empty files have zero chunk references and the SHA-256 hash of empty bytes.

Every compile and update enumerates, reads, and SHA-256 hashes **all included files**. Source-read work is linear in included input size. Changed files are rechunked completely. Existing chunk hashes reuse their stored bytes; unchanged files retain their chunk mappings and original lexical rows. Changed text files replace their entire lexical row and all their mapping rows. Deleted files remove their mappings/index rows, and unreferenced chunks are removed. No global lexical rebuild occurs, but validation and root computation scan the package. Content chunk reuse does not imply reuse of dependent causal KV state.

Source text means valid UTF-8 without NUL bytes. All other files remain losslessly stored as binary and receive no lexical row. Source bytes also occur in the lexical index's content storage, so deduplicated chunk byte count is **not total container storage**. SQLite may retain freed pages after deletion; updates do not run global `VACUUM`. Measure physical `storage_bytes` separately.

## Metrics contract

| Field | Meaning |
| --- | --- |
| `elapsed_seconds` | Complete public compile/update call, including reads and validation |
| `source_bytes_read`, `source_files_read` | Included source bytes/files actually read and hashed |
| `source_read_and_hash_seconds` | Enumeration, source reads, and file hashing together |
| `source_hash_seconds` | File SHA-256 portion of the preceding time |
| `chunking_seconds` | Chunk-boundary generation and per-chunk SHA-256 for changed files |
| `sqlite_write_and_root_seconds` | Source/index mutations plus root work; update also includes precommit verification |
| `validation_seconds` | Explicit verification calls; overlaps the update write/root interval and must not be summed with it |
| `files_added/modified/deleted/unchanged` | File state transitions |
| `chunks_new` | Unique chunk records newly inserted during this operation |
| `chunks_reused` | Distinct hashes whose stored bytes were reused, including duplicates inserted earlier in this operation |
| `chunks_reused_from_previous_pack` | Reused distinct hashes already present before this operation |
| `chunk_refs_reused` | Reused references, including repeated references to the same stored chunk |
| `chunks_deleted` | Unreferenced unique chunks removed |
| `lexical_rows_changed` | Logical index row deletions plus insertions |
| `logical_rows_changed` | File/map/chunk/index row mutations, excluding metadata and FTS internals |
| `sqlite_total_changes` | SQLite's mutation count for source/index work, including FTS internal work; excludes metadata/root updates |
| `storage_bytes` | Actual SQLite file length, including source, indexes, metadata, and free pages |
| `unique_chunk_bytes` | Sum of unique stored source chunk bytes only |

These fields are CPU/source/index measurements. No inference milliseconds, FLOPs avoided, semantic retrieval score, network savings, or sublinear source reads are inferred.

## Safety and integrity boundaries

Reader connections use SQLite `mode=ro`, `query_only`, disabled extension loading, `trusted_schema=OFF`, and a read transaction for a stable snapshot that honors writer locks. The exact table/index/virtual-table schema is allowlisted; triggers, views, unexpected tables, and unknown metadata fields fail. SQL statements are fixed and user strings are parameterized. Configured byte/file/chunk/metadata/query limits and a SQLite VM progress budget bound work. Defaults permit 10,000 files, 128 MiB included bytes, 16 MiB per file, 200,000 unique chunks, 2 MiB per chunk, and 512 MiB container size.

All stored paths must be canonical relative POSIX paths, with no traversal, drives, backslashes, control characters, Windows invalid characters/device names, or case collisions. The source scanner rejects encountered symlinks and junctions, checks containment, and checks file identity/size/modification time before and after reads. The scanner is intended for the user's local source tree; it is not an OS-level sandbox against an adversary concurrently racing filesystem changes. No extraction command is exposed.

Default exclusions cover `.git`, `.venv`, other VCS/dependency caches, `.env*`, common credential/secret names and key/certificate suffixes, plus `.npk` artifacts/sidecars. The operation reports excluded relative paths. Filename exclusions cannot prove that arbitrary ordinary source files contain no secrets; this is a local package and is never uploaded by this code.

Each chunk's full SHA-256 is checked, files are reconstructed and checked against complete source hashes, ordinals/references are validated, lexical content must match its source, and a framed SHA-256 digest covers all logical data plus metadata and FTS internal rows. This detects corruption and stale/tampered components relative to the stored digest. It is **not a signature or authentication**: someone who controls a package can generate a different internally consistent package and root. Source-root/version/timestamps are provenance records, not authenticated identity. The root is package-specific and includes timestamps; source/chunk hashes carry stable content identity.

Compiles build a private sibling temporary SQLite file, fully verify it, then publish with an atomic no-overwrite hard link. This requires hard-link support at the chosen local output filesystem; an unsupported filesystem fails instead of risking overwrite. Updates use `BEGIN IMMEDIATE`, validate again under the write lock, verify the result before commit, and roll back failures. The original database is not globally rebuilt.

## 2026-09-05 action and failure journal

After finishing the 28-task corpus/evaluator, the main agent assigned the bounded source compiler. Announced the public API and metrics before implementation so the independent incremental benchmark could use them. Inspected the existing `npk` directory and package entry point to avoid editing the main agent's compatibility/optimizer modules.

Created `npk/__init__.py`, `npk/format.py`, `npk/compiler.py`, and `npk/cli.py` within the assigned ownership. Implemented deterministic chunking, exact byte reconstruction, strict SQLite reads, linear source scanning, incremental chunk/lexical persistence, transactional updates, integrity validation, JSON CLI commands, and a labeled CPU convenience benchmark. Added `tests/test_pack.py` covering round trip, query, source exclusions/limits, path safety, corruption/truncation, hostile schema, wrong metadata, edited/deleted sources, no-overwrite output, and rollback.

The first 24-test run found two test cleanup errors on Windows: `with sqlite3.connect(...)` does not close the connection, so the test left the database locked during temporary-directory cleanup. Replaced those test connections with `contextlib.closing`; rerun passed all executed tests. One real symlink creation test was skipped because Windows denied the required creation privilege. No security setting or privilege was changed. Reported the same connection-lifecycle issue in the independent benchmark to the main agent without editing its file.

Review caught and fixed the deleted-text `lexical_rows_changed` counter, broadened environment-file exclusions, made enumeration errors fail instead of silently omitting files, required `.npk` output names to avoid self-inclusion on update, bounded metadata-row loading, and made CLI SQLite errors structured. Replaced an initial immutable reader optimization with normal read-only SQLite transactions to preserve concurrency locks and snapshot consistency. Added tests for unknown metadata and stored traversal even when the integrity root is recomputed.

No CPU performance sweep was run while the main agent's GPU quality run was active. Unit/integrity checks use tiny temporary fixtures and establish implementation behavior, not comparative speed. The independent mutation benchmark must execute and preserve raw measurements before this source compiler receives any performance claim.

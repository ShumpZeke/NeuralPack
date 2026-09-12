"""Measured local source compilation. Chunk/index reuse is not neural KV reuse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time
from typing import Any, Iterator

from . import __version__
from .format import (
    FORMAT_VERSION, SCHEMA, Limits, PackError, _verify_connection, configure_connection,
    metadata, root_digest, safe_relative_path, verify_pack,
)


EXCLUDED_NAMES = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".env", "credentials", "credentials.json", "credentials.yaml", "credentials.yml",
    "secrets", "secrets.json", "secrets.yaml", "secrets.yml", "id_rsa", "id_ed25519",
    ".aws", ".ssh", ".azure", ".gcloud", "token.json", "tokens.json",
})
GEAR = tuple(int.from_bytes(hashlib.sha256(f"NeuralPack gear v1 {i}".encode()).digest()[:8], "little") for i in range(256))


@dataclass(frozen=True)
class SourceFile:
    path: str
    data: bytes
    sha256: str


def _excluded(name: str) -> bool:
    lower = name.casefold()
    return lower in EXCLUDED_NAMES or lower.startswith((".env", ".npk-build-")) or lower.endswith((".npk", ".npk-journal", ".npk-wal", ".npk-shm", ".pem", ".key", ".p12", ".pfx"))


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _scan_source(source: str | Path, limits: Limits) -> tuple[Path, list[SourceFile], dict[str, Any]]:
    started = time.perf_counter()
    original = Path(source)
    if _is_link(original) or not original.is_dir():
        raise PackError("source must be a real directory, not a symlink/junction")
    root = original.resolve()
    records: list[SourceFile] = []
    skipped = []
    total_bytes = 0
    hashing_seconds = 0.0
    folded: set[str] = set()
    def walk_error(error: OSError) -> None:
        raise PackError(f"cannot enumerate source: {error}") from error
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=walk_error):
        current = Path(directory)
        kept = []
        for name in sorted(dirs):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if _is_link(path):
                raise PackError(f"source symlink/junction is forbidden: {relative}")
            if _excluded(name):
                skipped.append(relative + "/")
            else:
                safe_relative_path(relative)
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if _is_link(path):
                raise PackError(f"source symlink is forbidden: {relative}")
            if _excluded(name):
                skipped.append(relative)
                continue
            safe_relative_path(relative)
            if relative.casefold() in folded:
                raise PackError("source has case-colliding file paths")
            folded.add(relative.casefold())
            if not path.is_file() or not path.resolve().is_relative_to(root):
                raise PackError(f"source is not a regular contained file: {relative}")
            before = path.stat()
            if before.st_size > limits.max_file_bytes or total_bytes + before.st_size > limits.max_source_bytes:
                raise PackError("source byte limit exceeded")
            if len(records) >= limits.max_files:
                raise PackError("source file count limit exceeded")
            with path.open("rb") as stream:
                data = stream.read(limits.max_file_bytes + 1)
            after = path.stat()
            identity = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if _is_link(path) or identity(before) != identity(after) or len(data) != before.st_size:
                raise PackError("source changed while it was being read")
            total_bytes += len(data)
            if len(data) > limits.max_file_bytes or total_bytes > limits.max_source_bytes:
                raise PackError("source byte limit exceeded during read")
            hash_start = time.perf_counter()
            file_hash = hashlib.sha256(data).hexdigest()
            hashing_seconds += time.perf_counter() - hash_start
            records.append(SourceFile(relative, data, file_hash))
    records.sort(key=lambda record: record.path)
    return root, records, {
        "source_files_read": len(records), "source_bytes_read": total_bytes,
        "source_read_and_hash_seconds": time.perf_counter() - started,
        "source_hash_seconds": hashing_seconds, "excluded_paths": sorted(skipped),
    }


def iter_chunks(data: bytes, *, chunking: str = "cdc", target_size: int = 4096) -> Iterator[bytes]:
    """Fixed chunks or reset-at-boundary 64-bit Gear content-defined chunks.

    CDC min/target/max = target/2, target, target*2. Gear constants are fixed by
    SHA-256 labels. This is a simple experimental variant, not FastCDC parity.
    """
    if chunking not in ("fixed", "cdc"):
        raise ValueError("chunking must be fixed or cdc")
    if type(target_size) is not int or target_size < 64 or target_size > 1024 * 1024 or target_size & (target_size - 1):
        raise ValueError("target_size must be a power of two from 64 to 1048576")
    if chunking == "fixed":
        for offset in range(0, len(data), target_size):
            yield data[offset:offset + target_size]
        return
    start, rolling = 0, 0
    minimum, maximum = target_size // 2, target_size * 2
    for index, byte in enumerate(data):
        rolling = ((rolling << 1) + GEAR[byte]) & ((1 << 64) - 1)
        length = index + 1 - start
        if length >= minimum and ((rolling & (target_size - 1)) == 0 or length >= maximum):
            yield data[start:index + 1]
            start, rolling = index + 1, 0
    if start < len(data):
        yield data[start:]


def _text(data: bytes) -> str | None:
    try:
        decoded = data.decode("utf-8")
        return decoded if "\0" not in decoded else None
    except UnicodeError:
        return None


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _set_metadata(connection: sqlite3.Connection, values: dict[str, str]) -> None:
    connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", values.items())


def _apply_sources(connection: sqlite3.Connection, records: list[SourceFile], *, chunking: str, target_size: int, limits: Limits) -> dict[str, Any]:
    start_changes = connection.total_changes
    old_files = dict(connection.execute("SELECT path,sha256 FROM files"))
    old_chunks = {row[0] for row in connection.execute("SELECT hash FROM chunks")}
    known_chunks = set(old_chunks)
    current_paths = {record.path for record in records}
    deleted = sorted(old_files.keys() - current_paths)
    logical_rows = 0
    deleted_lexical = 0
    for path in deleted:
        logical_rows += connection.execute("SELECT COUNT(*) FROM file_chunks WHERE path=?", (path,)).fetchone()[0]
        lexical_count = connection.execute("SELECT COUNT(*) FROM lexical WHERE path=?", (path,)).fetchone()[0]
        logical_rows += lexical_count
        deleted_lexical += lexical_count
        connection.execute("DELETE FROM lexical WHERE path=?", (path,))
        connection.execute("DELETE FROM files WHERE path=?", (path,))
        logical_rows += 1
    counters: dict[str, Any] = {
        "files_added": 0, "files_modified": 0, "files_deleted": len(deleted), "files_unchanged": 0,
        "chunks_new": 0, "chunk_refs_reused": 0, "chunking_seconds": 0.0,
        "lexical_rows_changed": deleted_lexical,
    }
    reused_unique = set()
    for record in records:
        if old_files.get(record.path) == record.sha256:
            counters["files_unchanged"] += 1
            for (chunk_hash,) in connection.execute("SELECT hash FROM file_chunks WHERE path=?", (record.path,)):
                counters["chunk_refs_reused"] += 1
                reused_unique.add(chunk_hash)
            continue
        content = _text(record.data)
        exists = record.path in old_files
        counters["files_modified" if exists else "files_added"] += 1
        if exists:
            previous_refs = connection.execute("SELECT COUNT(*) FROM file_chunks WHERE path=?", (record.path,)).fetchone()[0]
            previous_lexical = connection.execute("SELECT COUNT(*) FROM lexical WHERE path=?", (record.path,)).fetchone()[0]
            connection.execute("DELETE FROM file_chunks WHERE path=?", (record.path,))
            connection.execute("DELETE FROM lexical WHERE path=?", (record.path,))
            logical_rows += previous_refs + previous_lexical
            counters["lexical_rows_changed"] += previous_lexical
        connection.execute("INSERT INTO files(path,sha256,size,is_text) VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,size=excluded.size,is_text=excluded.is_text", (record.path, record.sha256, len(record.data), int(content is not None)))
        logical_rows += 1
        start = time.perf_counter()
        chunks = list(iter_chunks(record.data, chunking=chunking, target_size=target_size))
        chunk_records = [(hashlib.sha256(chunk).hexdigest(), chunk) for chunk in chunks]
        counters["chunking_seconds"] += time.perf_counter() - start
        for ordinal, (chunk_hash, chunk) in enumerate(chunk_records):
            if chunk_hash in known_chunks:
                counters["chunk_refs_reused"] += 1
                reused_unique.add(chunk_hash)
            else:
                if len(known_chunks) >= limits.max_chunks or len(chunk) > limits.max_chunk_bytes:
                    raise PackError("chunk count or size limit exceeded")
                connection.execute("INSERT INTO chunks(hash,data,size) VALUES(?,?,?)", (chunk_hash, chunk, len(chunk)))
                known_chunks.add(chunk_hash)
                counters["chunks_new"] += 1
                logical_rows += 1
            connection.execute("INSERT INTO file_chunks(path,ordinal,hash) VALUES(?,?,?)", (record.path, ordinal, chunk_hash))
            logical_rows += 1
        if content is not None:
            connection.execute("INSERT INTO lexical(path,content) VALUES(?,?)", (record.path, content))
            counters["lexical_rows_changed"] += 1
            logical_rows += 1
    unreferenced = connection.execute("SELECT COUNT(*) FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM file_chunks fc WHERE fc.hash=c.hash)").fetchone()[0]
    connection.execute("DELETE FROM chunks WHERE NOT EXISTS (SELECT 1 FROM file_chunks fc WHERE fc.hash=chunks.hash)")
    logical_rows += unreferenced
    counters.update(
        chunks_reused=len(reused_unique), chunks_reused_from_previous_pack=len(reused_unique & old_chunks),
        chunks_deleted=unreferenced, logical_rows_changed=logical_rows,
        sqlite_total_changes=connection.total_changes - start_changes,
    )
    return counters


def _check_settings(chunking: str, target_size: int, limits: Limits) -> None:
    list(iter_chunks(b"", chunking=chunking, target_size=target_size))
    if target_size * 2 > limits.max_chunk_bytes:
        raise ValueError("target size exceeds configured chunk byte limit")


def _finish_metrics(pack: Path, metrics: dict[str, Any], started: float, validation_seconds: float) -> dict[str, Any]:
    metrics.update(
        elapsed_seconds=time.perf_counter() - started, validation_seconds=validation_seconds,
        storage_bytes=pack.stat().st_size,
        measurement_scope="CPU source read/hash/chunk/SQLite lexical-index work; no model inference",
        source_read_policy="all included source files are read and SHA-256 hashed on every compile/update",
    )
    return metrics


def compile_pack(source: str | Path, output: str | Path, *, chunking: str = "cdc", target_size: int = 4096, limits: Limits = Limits()) -> dict[str, Any]:
    started = time.perf_counter()
    _check_settings(chunking, target_size, limits)
    target = Path(output).absolute()
    if target.suffix.casefold() != ".npk":
        raise PackError("compiled output must use the .npk suffix")
    if target.exists() or _is_link(target):
        raise FileExistsError(f"output already exists: {target}")
    if not target.parent.is_dir():
        raise PackError("output parent directory must already exist")
    root, records, metrics = _scan_source(source, limits)
    handle, temporary_name = tempfile.mkstemp(prefix=".npk-build-", suffix=".tmp", dir=target.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        configure_connection(connection, limits, readonly=False)
        connection.executescript(SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        stamp = _utc()
        _set_metadata(connection, {
            "format_version": str(FORMAT_VERSION), "compiler_version": __version__,
            "chunking": chunking, "target_size": str(target_size), "source_root": str(root),
            "created_utc": stamp, "updated_utc": stamp, "sqlite_version": sqlite3.sqlite_version,
            "excluded_names": json.dumps(sorted(EXCLUDED_NAMES)), "root_sha256": "0" * 64,
        })
        write_start = time.perf_counter()
        metrics.update(_apply_sources(connection, records, chunking=chunking, target_size=target_size, limits=limits))
        _set_metadata(connection, {"root_sha256": root_digest(connection)})
        connection.commit()
        metrics["sqlite_write_and_root_seconds"] = time.perf_counter() - write_start
        connection.close()
        connection = None
        verify_start = time.perf_counter()
        verification = verify_pack(temporary, limits=limits)
        validation_seconds = time.perf_counter() - verify_start
        # Atomic no-overwrite publication; a concurrent preexisting target fails.
        os.link(temporary, target)
        temporary.unlink()
        metrics.update(operation="compile", chunking=chunking, target_size=target_size,
                       files=verification["files"], chunks=verification["chunks"],
                       root_sha256=verification["root_sha256"], unique_chunk_bytes=verification["unique_chunk_bytes"])
        return _finish_metrics(target, metrics, started, validation_seconds)
    finally:
        if connection is not None:
            connection.close()
        if temporary.exists():
            temporary.unlink()


def update_pack(pack: str | Path, source: str | Path, *, limits: Limits = Limits()) -> dict[str, Any]:
    started = time.perf_counter()
    target = Path(pack)
    # Fail read-only verification before opening an untrusted DB for updates.
    verify_start = time.perf_counter()
    verify_pack(target, limits=limits)
    validation_seconds = time.perf_counter() - verify_start
    root, records, metrics = _scan_source(source, limits)
    if _is_link(target):
        raise PackError("package symlinks/junctions are forbidden")
    connection = sqlite3.connect(target.resolve().as_uri() + "?mode=rw", uri=True)
    try:
        configure_connection(connection, limits, readonly=False)
        connection.execute("BEGIN IMMEDIATE")
        verify_start = time.perf_counter()
        _verify_connection(connection, limits)  # recheck under the write lock
        validation_seconds += time.perf_counter() - verify_start
        info = metadata(connection, limits)
        chunking, target_size = info["chunking"], int(info["target_size"])
        write_start = time.perf_counter()
        metrics.update(_apply_sources(connection, records, chunking=chunking, target_size=target_size, limits=limits))
        _set_metadata(connection, {"source_root": str(root), "updated_utc": _utc()})
        _set_metadata(connection, {"root_sha256": root_digest(connection)})
        # Validate before committing, so a failed update preserves the old pack.
        verify_start = time.perf_counter()
        verification = _verify_connection(connection, limits)
        validation_seconds += time.perf_counter() - verify_start
        if connection.execute("PRAGMA page_count").fetchone()[0] * connection.execute("PRAGMA page_size").fetchone()[0] > limits.max_container_bytes:
            raise PackError("updated container exceeds byte limit")
        connection.commit()
        metrics["sqlite_write_and_root_seconds"] = time.perf_counter() - write_start
        metrics.update(operation="update", chunking=chunking, target_size=target_size,
                       files=verification["files"], chunks=verification["chunks"],
                       root_sha256=verification["root_sha256"], unique_chunk_bytes=verification["unique_chunk_bytes"])
    except (sqlite3.Error, PackError):
        connection.rollback()
        raise
    finally:
        connection.close()
    return _finish_metrics(target, metrics, started, validation_seconds)


def _distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "n": len(values), "median": statistics.median(values), "p50": statistics.median(values),
        "p95": ordered[max(0, math.ceil(0.95 * len(values)) - 1)],
        "mean": statistics.mean(values), "variance": statistics.pvariance(values),
        "p95_method": "nearest rank",
    }


def benchmark_source(source: str | Path, *, trials: int = 3, chunking: str = "cdc", target_size: int = 4096, limits: Limits = Limits()) -> dict[str, Any]:
    if type(trials) is not int or not 1 <= trials <= 100:
        raise ValueError("trials must be an integer between 1 and 100")
    results = []
    # Temp files are outside source, avoiding self-inclusion during repeated scans.
    with tempfile.TemporaryDirectory(prefix="neuralpack-benchmark-") as directory:
        for trial in range(trials):
            pack = Path(directory) / f"trial-{trial}.npk"
            cold = compile_pack(source, pack, chunking=chunking, target_size=target_size, limits=limits)
            warm = update_pack(pack, source, limits=limits)
            results.append({"trial": trial, "full_compile": cold, "unchanged_update": warm})
    full = _distribution([row["full_compile"]["elapsed_seconds"] for row in results])
    update = _distribution([row["unchanged_update"]["elapsed_seconds"] for row in results])
    return {
        "benchmark": "CPU source compiler: full compile versus unchanged update",
        "no_inference_measurements": True,
        "cache_condition": "fresh package per trial; OS filesystem caches uncontrolled and generally warm",
        "source": str(Path(source).resolve()), "chunking": chunking, "target_size": target_size,
        "full_compile_seconds": full, "unchanged_update_seconds": update,
        "median_full_over_update_ratio": full["median"] / update["median"] if update["median"] else None,
        "raw_trials": results,
    }

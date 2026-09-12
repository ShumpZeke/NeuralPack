"""Strict, bounded SQLite source container. No pickles or executable payloads."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Any, Iterator


FORMAT_VERSION = 1
SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE chunks(hash TEXT PRIMARY KEY, data BLOB NOT NULL, size INTEGER NOT NULL);
CREATE TABLE files(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL, is_text INTEGER NOT NULL);
CREATE TABLE file_chunks(path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE, ordinal INTEGER NOT NULL, hash TEXT NOT NULL REFERENCES chunks(hash), PRIMARY KEY(path, ordinal));
CREATE INDEX file_chunks_hash ON file_chunks(hash);
CREATE VIRTUAL TABLE lexical USING fts5(path UNINDEXED, content, tokenize='unicode61');
"""
METADATA_KEYS = frozenset({
    "format_version", "compiler_version", "chunking", "target_size", "source_root",
    "created_utc", "updated_utc", "sqlite_version", "excluded_names", "root_sha256",
})
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class PackError(ValueError):
    """A package or source violates the prototype's integrity/safety rules."""


@dataclass(frozen=True)
class Limits:
    max_files: int = 10_000
    max_source_bytes: int = 128 * 1024 * 1024
    max_file_bytes: int = 16 * 1024 * 1024
    max_chunks: int = 200_000
    max_chunk_bytes: int = 2 * 1024 * 1024
    max_container_bytes: int = 512 * 1024 * 1024
    max_metadata_bytes: int = 64 * 1024
    max_query_chars: int = 4096

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in self.__dict__.values()):
            raise ValueError("all Limits values must be positive integers")


def safe_relative_path(value: str) -> str:
    """Stored paths are portable relative POSIX paths, never extraction commands."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise PackError("invalid stored path")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PackError("control character in path")
    if any(char in value for char in '\\:<>"|?*') or value.startswith("/"):
        raise PackError("absolute, drive, or backslash path is forbidden")
    pieces = value.split("/")
    if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in pieces):
        raise PackError("path traversal or nonportable path component")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(part.split(".")[0].casefold() in reserved for part in pieces):
        raise PackError("Windows device path is forbidden")
    if str(PurePosixPath(value)) != value:
        raise PackError("path is not canonical")
    return value


def _schema_rows(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").fetchall()


@lru_cache(maxsize=1)
def _expected_schema() -> tuple[tuple[Any, ...], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SCHEMA)
        return tuple(_schema_rows(connection))
    finally:
        connection.close()


def validate_schema(connection: sqlite3.Connection) -> None:
    if tuple(_schema_rows(connection)) != _expected_schema():
        raise PackError("schema is not the exact allowed NeuralPack schema")


def configure_connection(connection: sqlite3.Connection, limits: Limits, *, readonly: bool) -> None:
    connection.enable_load_extension(False)
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA foreign_keys=ON")
    if readonly:
        connection.execute("PRAGMA query_only=ON")
    if hasattr(connection, "setconfig") and hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, max(limits.max_file_bytes, limits.max_chunk_bytes) + limits.max_metadata_bytes)
    connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 32 * 1024)
    # Bound malformed-file VM work; Python hashing is additionally bounded by bytes.
    remaining = [100_000]
    def progress() -> int:
        remaining[0] -= 1
        return int(remaining[0] <= 0)
    connection.set_progress_handler(progress, 1000)


@contextmanager
def open_readonly(pack: str | Path, limits: Limits = Limits()) -> Iterator[sqlite3.Connection]:
    path = Path(pack)
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise PackError("package symlinks/junctions are forbidden")
    if not path.is_file() or path.stat().st_size > limits.max_container_bytes:
        raise PackError("package is missing, not a file, or above size limit")
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        configure_connection(connection, limits, readonly=True)
        connection.execute("BEGIN")  # stable read snapshot; honor concurrent-writer locks
        validate_schema(connection)
        yield connection
    except sqlite3.Error as error:
        raise PackError(f"invalid or unreadable SQLite package: {error}") from error
    finally:
        if connection is not None:
            connection.close()


def metadata(connection: sqlite3.Connection, limits: Limits = Limits()) -> dict[str, str]:
    rows = connection.execute("SELECT key,value FROM metadata ORDER BY key LIMIT ?", (len(METADATA_KEYS) + 1,)).fetchall()
    if len(rows) != len(METADATA_KEYS) or {row[0] for row in rows} != METADATA_KEYS:
        raise PackError("unknown or missing metadata fields")
    if any(type(key) is not str or type(value) is not str for key, value in rows):
        raise PackError("metadata must contain strings")
    if sum(len(key.encode()) + len(value.encode()) for key, value in rows) > limits.max_metadata_bytes:
        raise PackError("metadata byte limit exceeded")
    result = dict(rows)
    if result["format_version"] != str(FORMAT_VERSION):
        raise PackError("unsupported package version")
    if result["chunking"] not in ("fixed", "cdc"):
        raise PackError("unsupported chunking algorithm")
    try:
        size = int(result["target_size"])
        excluded = json.loads(result["excluded_names"])
    except (ValueError, TypeError, RecursionError) as error:
        raise PackError("malformed compiler metadata") from error
    if size < 64 or size > 1024 * 1024 or size & (size - 1) or size * 2 > limits.max_chunk_bytes:
        raise PackError("invalid chunk size")
    if not isinstance(excluded, list) or any(type(name) is not str for name in excluded):
        raise PackError("invalid excluded-names metadata")
    if not HASH_PATTERN.fullmatch(result["root_sha256"]):
        raise PackError("invalid root digest")
    return result


def _hash_value(digest: Any, value: Any) -> None:
    if value is None:
        tag, raw = b"n", b""
    elif type(value) is bytes:
        tag, raw = b"b", value
    elif type(value) is str:
        tag, raw = b"s", value.encode("utf-8")
    elif type(value) is int:
        tag, raw = b"i", str(value).encode("ascii")
    else:
        raise PackError("unsupported SQLite value type")
    digest.update(tag + len(raw).to_bytes(8, "big"))
    digest.update(raw)


def root_digest(connection: sqlite3.Connection) -> str:
    """Hash logical rows, including FTS internals; digest is integrity, not a signature."""
    digest = hashlib.sha256(b"NeuralPack-SQLite-v1\0")
    table_queries = (
        ("metadata", "SELECT key,value FROM metadata WHERE key != 'root_sha256' ORDER BY key"),
        ("chunks", "SELECT hash,data,size FROM chunks ORDER BY hash"),
        ("files", "SELECT path,sha256,size,is_text FROM files ORDER BY path"),
        ("file_chunks", "SELECT path,ordinal,hash FROM file_chunks ORDER BY path,ordinal"),
        ("lexical_data", "SELECT id,block FROM lexical_data ORDER BY id"),
        ("lexical_idx", "SELECT segid,term,pgno FROM lexical_idx ORDER BY segid,term"),
        ("lexical_content", "SELECT id,c0,c1 FROM lexical_content ORDER BY id"),
        ("lexical_docsize", "SELECT id,sz FROM lexical_docsize ORDER BY id"),
        ("lexical_config", "SELECT k,v FROM lexical_config ORDER BY k"),
    )
    for name, query in table_queries:
        _hash_value(digest, name)
        for row in connection.execute(query):
            digest.update(b"r")
            for value in row:
                _hash_value(digest, value)
        digest.update(b"e")
    return digest.hexdigest()


def _verify_connection(connection: sqlite3.Connection, limits: Limits) -> dict[str, Any]:
    validate_schema(connection)
    info = metadata(connection, limits)
    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise PackError("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise PackError("broken chunk references")
    counts = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("files", "chunks", "file_chunks", "lexical_content")}
    if counts["files"] > limits.max_files or counts["chunks"] > limits.max_chunks or counts["file_chunks"] > limits.max_chunks * 16 or counts["lexical_content"] > limits.max_files:
        raise PackError("record count limit exceeded")
    source_bytes = stored_bytes = 0
    for chunk_hash, data, size in connection.execute("SELECT hash,data,size FROM chunks"):
        if type(chunk_hash) is not str or not HASH_PATTERN.fullmatch(chunk_hash) or type(data) is not bytes or type(size) is not int:
            raise PackError("invalid chunk record types")
        if not 1 <= size <= limits.max_chunk_bytes or len(data) != size:
            raise PackError("invalid chunk size")
        stored_bytes += size
        if stored_bytes > limits.max_source_bytes or hashlib.sha256(data).hexdigest() != chunk_hash:
            raise PackError("chunk byte limit or hash mismatch")
    lexical = {}
    for path, content in connection.execute("SELECT path,content FROM lexical"):
        if type(path) is not str or type(content) is not str or path in lexical:
            raise PackError("invalid or duplicate lexical row")
        if len(content.encode("utf-8")) > limits.max_file_bytes:
            raise PackError("lexical content too large")
        lexical[path] = content
    folded = set()
    for path, file_hash, size, is_text in connection.execute("SELECT path,sha256,size,is_text FROM files ORDER BY path"):
        safe_relative_path(path)
        if path.casefold() in folded:
            raise PackError("case-colliding file paths")
        folded.add(path.casefold())
        if type(file_hash) is not str or not HASH_PATTERN.fullmatch(file_hash) or type(size) is not int or not 0 <= size <= limits.max_file_bytes or type(is_text) is not int or is_text not in (0, 1):
            raise PackError("invalid source file record")
        source_bytes += size
        if source_bytes > limits.max_source_bytes:
            raise PackError("source byte limit exceeded")
        digest, actual_size, pieces = hashlib.sha256(), 0, []
        for index, (ordinal, data) in enumerate(connection.execute("SELECT fc.ordinal,c.data FROM file_chunks fc JOIN chunks c ON c.hash=fc.hash WHERE fc.path=? ORDER BY fc.ordinal", (path,))):
            if type(ordinal) is not int or ordinal != index:
                raise PackError("noncontiguous chunk ordinals")
            actual_size += len(data)
            if actual_size > size:
                raise PackError("file chunk map exceeds source size")
            digest.update(data)
            if is_text:
                pieces.append(data)
        if actual_size != size or digest.hexdigest() != file_hash:
            raise PackError("source reconstruction hash mismatch")
        if is_text:
            try:
                content = b"".join(pieces).decode("utf-8")
            except UnicodeError as error:
                raise PackError("invalid text file encoding") from error
            if "\0" in content or lexical.pop(path, None) != content:
                raise PackError("lexical content differs from source")
        elif path in lexical:
            raise PackError("binary file has lexical row")
    if lexical:
        raise PackError("lexical row has no matching source")
    if connection.execute("SELECT 1 FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM file_chunks fc WHERE fc.hash=c.hash) LIMIT 1").fetchone():
        raise PackError("unreferenced chunks")
    if root_digest(connection) != info["root_sha256"]:
        raise PackError("package root digest mismatch")
    return {
        "verified": True, "format_version": FORMAT_VERSION, "files": counts["files"],
        "chunks": counts["chunks"], "chunk_references": counts["file_chunks"],
        "source_bytes": source_bytes, "unique_chunk_bytes": stored_bytes,
        "lexical_files": counts["lexical_content"], "root_sha256": info["root_sha256"],
        "metadata": info,
    }


def verify_pack(pack: str | Path, *, limits: Limits = Limits()) -> dict[str, Any]:
    with open_readonly(pack, limits) as connection:
        result = _verify_connection(connection, limits)
    result["storage_bytes"] = Path(pack).stat().st_size
    return result


def inspect_pack(pack: str | Path, *, limits: Limits = Limits()) -> dict[str, Any]:
    result = verify_pack(pack, limits=limits)
    result["representation"] = "lossless source bytes + content-addressed chunks + SQLite FTS5 lexical index"
    result["neural_state"] = False
    result["authenticated_provenance"] = False
    return result


def read_file(pack: str | Path, relative_path: str, *, limits: Limits = Limits()) -> bytes:
    safe_relative_path(relative_path)
    with open_readonly(pack, limits) as connection:
        _verify_connection(connection, limits)
        if not connection.execute("SELECT 1 FROM files WHERE path=?", (relative_path,)).fetchone():
            raise KeyError(relative_path)
        return b"".join(row[0] for row in connection.execute("SELECT c.data FROM file_chunks fc JOIN chunks c ON c.hash=fc.hash WHERE fc.path=? ORDER BY fc.ordinal", (relative_path,)))


def query_pack(pack: str | Path, query: str, *, limit: int = 10, limits: Limits = Limits()) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip() or len(query) > limits.max_query_chars:
        raise ValueError("query must be nonempty and within the character limit")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    # Literal terms only: user input cannot become FTS operators or SQL syntax.
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    if not terms:
        return []
    expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
    with open_readonly(pack, limits) as connection:
        _verify_connection(connection, limits)
        rows = connection.execute("SELECT path, snippet(lexical,1,'[',']',' ... ',24), bm25(lexical) FROM lexical WHERE lexical MATCH ? ORDER BY bm25(lexical),path LIMIT ?", (expression, limit)).fetchall()
        return [{"path": row[0], "snippet": row[1], "lexical_bm25": row[2]} for row in rows]


def diff_packs(old: str | Path, new: str | Path, *, limits: Limits = Limits()) -> dict[str, Any]:
    records = []
    for pack in (old, new):
        with open_readonly(pack, limits) as connection:
            _verify_connection(connection, limits)
            records.append(dict(connection.execute("SELECT path,sha256 FROM files")))
    before, after = records
    return {
        "added": sorted(after.keys() - before.keys()),
        "deleted": sorted(before.keys() - after.keys()),
        "modified": sorted(path for path in before.keys() & after.keys() if before[path] != after[path]),
        "unchanged": sorted(path for path in before.keys() & after.keys() if before[path] == after[path]),
    }

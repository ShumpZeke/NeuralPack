"""Version 8 compiled context artifact backed by SQLite and FTS5.

The container provides indexed retrieval, transactions and portable storage.
Integrity covers schema, contents and derived index data. Hash verification is
separate from fast retrieval and cannot authenticate a self-declared publisher.
Current cost measurements and limitations are recorded in EVOLUTION_LOG.md.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterator, List, Optional

#: Bump on any schema change. Readers refuse artifacts they do not understand.
PACK_FORMAT_VERSION = 8

# Format v8 uses external-content FTS5. Generated postings do not duplicate the
# source body, and the external content row supplies stable document statistics
# after incremental deletes/inserts. The connection hardening contract relies
# on trusted-schema support available in SQLite 3.31.0+.
MIN_SQLITE_VERSION = (3, 31, 0)
READ_CACHE_BYTES = 8 * 1024 * 1024
MAX_READ_MMAP_BYTES = 256 * 1024 * 1024
SQLITE_MAX_VALUE_BYTES = 2 * 1024 * 1024 + 64 * 1024
SQLITE_MAX_STATEMENT_BYTES = 32 * 1024
READ_PROGRESS_INTERVAL = 1000
READ_PROGRESS_CALLBACKS = 100_000

#: Compile modes. ``deterministic`` is CPU-only and requires no model of any
#: kind; ``semantic`` additionally stores a local embedding index.
MODE_DETERMINISTIC = "deterministic"
MODE_SEMANTIC = "semantic"
COMPILE_MODES = (MODE_DETERMINISTIC, MODE_SEMANTIC)

SCHEMA = """
CREATE TABLE manifest(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE files(
    id        INTEGER PRIMARY KEY,
    path      TEXT NOT NULL UNIQUE,
    sha256    TEXT NOT NULL,
    size      INTEGER NOT NULL,
    language  TEXT NOT NULL DEFAULT 'unknown',
    mtime_ns  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX files_sha ON files(sha256);

CREATE TABLE blocks(
    id         INTEGER PRIMARY KEY,
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    tokens     INTEGER NOT NULL,
    sha256     TEXT NOT NULL,
    text       TEXT NOT NULL,
    -- Normalized path metadata is the external-content value for FTS5. The
    -- user-facing path remains files.path, so this column is never emitted.
    path       TEXT NOT NULL
);
CREATE INDEX blocks_file ON blocks(file_id);
CREATE INDEX blocks_sha  ON blocks(sha256);

-- Exact identifier lookup: the cheapest and highest-precision seed channel.
CREATE TABLE symbols(
    name     TEXT NOT NULL,
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL,
    is_def   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX symbols_name ON symbols(name);
CREATE INDEX symbols_block ON symbols(block_id);

-- Selective, syntactic facts used only as retrieval seeds. A relation row says
-- where syntax occurs; it does not assert that the path executes at runtime.
CREATE TABLE relations(
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL,
    name     TEXT NOT NULL,
    PRIMARY KEY(block_id, kind, name)
);
CREATE INDEX relations_lookup ON relations(kind, name);
CREATE INDEX relations_block ON relations(block_id);

-- Structural dependency edges. EXPERIMENTAL: retained but not enabled by
-- default because matched-budget benchmarks have not yet shown it improves
-- selection (see docs/decisions/0003).
CREATE TABLE deps(
    src_block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    dst_block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    PRIMARY KEY(src_block_id, dst_block_id, kind)
);

-- Optional. Present only for mode='semantic'. Model id is recorded so a reader
-- can refuse a mismatched query encoder.
CREATE TABLE embeddings(
    block_id INTEGER PRIMARY KEY REFERENCES blocks(id) ON DELETE CASCADE,
    dim      INTEGER NOT NULL,
    vector   BLOB NOT NULL
);

CREATE TABLE provenance(
    file_id     INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    source_uri  TEXT NOT NULL,
    collected_utc TEXT NOT NULL
);

-- Constant assignments, used to detect contradicting variants of the same
-- symbol at query time (see npk/pack/conflict.py). Cycle 1 measured four task
-- families at 0% recall purely because contradicting evidence was retrieved
-- alongside the correct evidence.
CREATE TABLE assignments(
    symbol     TEXT NOT NULL,
    block_id   INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    value_hash TEXT NOT NULL,
    PRIMARY KEY(symbol, block_id, value_hash)
);
CREATE INDEX assignments_symbol ON assignments(symbol);
CREATE INDEX assignments_block ON assignments(block_id);

CREATE VIRTUAL TABLE lexical USING fts5(
    text, name, path,
    content='blocks', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2 tokenchars '_'"
);

CREATE TABLE integrity_files(
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    digest BLOB NOT NULL CHECK(typeof(digest)='blob' AND length(digest)=32)
);
-- No FK: deleted file IDs must survive in the journal until sealing.
CREATE TABLE integrity_dirty(file_id INTEGER PRIMARY KEY);
"""

MANIFEST_KEYS = (
    "format_version", "compiler_version", "mode", "created_utc", "updated_utc",
    "source_root", "embedding_model", "embedding_dim", "block_count",
    "file_count", "available_tokens", "root_sha256",
)


class PackError(ValueError):
    """The artifact is malformed, unreadable, or a version we cannot serve."""


def validate_encoder_identity(identity: Any) -> None:
    """Only the implemented embedding-space contract is supported."""
    if (not isinstance(identity,dict) or type(identity.get("version")) is not int
        or identity["version"]!=1 or not isinstance(identity.get("model_id"),str)
        or not identity["model_id"] or not isinstance(identity.get("revision"),str)
        or not re.fullmatch(r"[0-9a-f]{40}",identity["revision"])
        or type(identity.get("max_length")) is not int or identity["max_length"]<=0
        or identity.get("pooling")!="mask_mean_l2_v1"
        or type(identity.get("document_char_limit")) is not int
        or identity["document_char_limit"]!=2000):
        raise PackError("unknown or missing encoder identity; recompile semantic artifact")


def require_encoder_match(manifest: Dict[str,str], actual: Any) -> None:
    try:
        expected=json.loads(manifest.get("encoder_identity") or "null")
    except (ValueError,TypeError) as exc:
        raise PackError("malformed encoder identity; recompile semantic artifact") from exc
    validate_encoder_identity(expected)
    validate_encoder_identity(actual)
    if expected != actual or manifest.get("embedding_model")!=actual["model_id"]:
        raise PackError("local encoder does not match the artifact; recompile or use lexical retrieval")


@dataclass(frozen=True)
class Block:
    """One selectable unit of evidence."""

    id: int
    file_id: int
    path: str
    ordinal: int
    kind: str
    name: Optional[str]
    start_line: int
    end_line: int
    tokens: int
    text: str

    @property
    def span(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


def connect(path: str | Path, *, readonly: bool = True, create: bool = False) -> sqlite3.Connection:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        required = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        raise PackError(f"SQLite {required}+ is required for format-v{PACK_FORMAT_VERSION} FTS5 storage")
    p = Path(path).absolute()
    # Quote URI delimiters in literal paths; '#'/percent escapes must not open
    # a plausible sibling instead. Only unpublished compilation may create DBs.
    mode = "ro" if readonly else "rwc" if create else "rw"
    try:
        con = sqlite3.connect(p.as_uri()+f"?mode={mode}", uri=True)
    except sqlite3.OperationalError:
        raise PackError("cannot open the requested artifact; check its path and access") from None
    try:
        if hasattr(con, "enable_load_extension"):
            con.enable_load_extension(False)
        con.execute("PRAGMA trusted_schema=OFF")
        if hasattr(con, "setconfig") and hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
            con.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
        if hasattr(con, "setlimit"):
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQLITE_MAX_VALUE_BYTES)
            con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, SQLITE_MAX_STATEMENT_BYTES)
        if not readonly:
            # Portable artifacts should not create -wal/-shm files when queried.
            # Updates use SQLite's rollback journal; compilation publishes by rename.
            con.execute("PRAGMA journal_mode=DELETE")
            con.execute("PRAGMA foreign_keys=ON")
        else:
            con.execute("PRAGMA query_only=ON")
            # These are connection-local read optimizations. SQLite may decline
            # mmap on a filesystem that cannot map the file; the selector still
            # has the ordinary page-cache path in that case.
            try:
                size = p.stat().st_size
                mmap_size = min(max(size, READ_CACHE_BYTES), MAX_READ_MMAP_BYTES)
                con.execute(f"PRAGMA mmap_size={mmap_size}")
                con.execute(f"PRAGMA cache_size={-(READ_CACHE_BYTES // 1024)}")
                con.execute("PRAGMA temp_store=2")
            except (OSError, sqlite3.DatabaseError):
                pass
            # Bound pathological virtual-machine work in a single reader
            # connection. Representative product queries use at most 11
            # callbacks at this interval; the high ceiling leaves substantial
            # room for large legitimate artifacts while failing closed on a
            # crafted query or schema that expands unexpectedly.
            remaining = [READ_PROGRESS_CALLBACKS]

            def progress() -> int:
                remaining[0] -= 1
                return int(remaining[0] <= 0)

            con.set_progress_handler(progress, READ_PROGRESS_INTERVAL)
        con.row_factory = sqlite3.Row
    except BaseException as error:
        # Ownership has not reached open_pack/the compiler yet. Release even on
        # cancellation; only expected storage failures are mapped to PackError.
        con.close()
        if isinstance(error,sqlite3.DatabaseError):
            raise PackError("cannot initialize the requested artifact connection") from None
        raise
    return con


@contextmanager
def open_pack(path: str | Path, *, readonly: bool = True) -> Iterator[sqlite3.Connection]:
    con = connect(path, readonly=readonly)
    try:
        if readonly:
            # Candidate IDs, source rows and integrity reads belong to one
            # snapshot even if a writer commits between individual SELECTs.
            con.execute("BEGIN")
        yield con
    finally:
        con.close()


def read_manifest(con: sqlite3.Connection) -> Dict[str, str]:
    try:
        rows = con.execute("SELECT key, value FROM manifest").fetchall()
    except sqlite3.DatabaseError as exc:
        raise PackError(f"unreadable pack: {exc}") from exc
    if any(not isinstance(r['key'],str) or not isinstance(r['value'],str) for r in rows):
        raise PackError("artifact manifest keys and values must be text")
    return {r["key"]: r["value"] for r in rows}


def require_supported(manifest: Dict[str, str]) -> None:
    raw = manifest.get("format_version")
    if raw is None:
        raise PackError("pack has no format_version")
    try:
        version = int(raw)
    except ValueError as exc:
        raise PackError(f"bad format_version {raw!r}") from exc
    if version != PACK_FORMAT_VERSION:
        raise PackError(
            f"unsupported pack format v{version}; this build requires v{PACK_FORMAT_VERSION}; recompile or upgrade npk"
        )
    from .contracts import require_manifest_values
    require_manifest_values(manifest)


def compute_root_digest(con: sqlite3.Connection, *, cached: bool = False) -> str:
    """V8 root. Full reads are default; cached mode is only for controlled sealing.

    Full computation checks every actual file leaf against the cache and also
    hashes schema, global metadata and FTS storage. Cached sealing assumes a
    valid accepted base and complete trigger invalidation inside the transaction.
    Neither a self-recorded root nor cached sealing authenticates a publisher.
    """
    from .integrity import compute_digest
    return compute_digest(con,cached=cached)


def verify(path: str | Path, *, expected_root: Optional[str] = None) -> Dict[str, Any]:
    """Check contents/indexes. A trusted expected_root additionally pins identity.

    An untrusted artifact can replace its own recorded digest; self-checks do
    not authenticate publishers. Corruption returns an explicit invalid result.
    """
    try:
        return _verify_contents(path, expected_root=expected_root)
    except (sqlite3.DatabaseError, PackError, OSError, UnicodeError) as exc:
        return {"ok": False, "errors": [str(exc)], "verification_level": "contents_and_indexes_v8"}


def _verify_contents(path: str | Path, *, expected_root: Optional[str]) -> Dict[str, Any]:
    with open_pack(path) as con:
        manifest = read_manifest(con)
        require_supported(manifest)
        from .contracts import require_stored_types
        require_stored_types(con)
        recorded = manifest.get("root_sha256", "")
        actual = compute_root_digest(con)
        counts = {
            "files": con.execute("SELECT COUNT(*) c FROM files").fetchone()["c"],
            "blocks": con.execute("SELECT COUNT(*) c FROM blocks").fetchone()["c"],
            "symbols": con.execute("SELECT COUNT(*) c FROM symbols").fetchone()["c"],
            "relations": con.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"],
            "embeddings": con.execute("SELECT COUNT(*) c FROM embeddings").fetchone()["c"],
            "deps": con.execute("SELECT COUNT(*) c FROM deps").fetchone()["c"],
            "assignments": con.execute("SELECT COUNT(*) c FROM assignments").fetchone()["c"],
        }
        errors = []
        if recorded != actual:
            errors.append("artifact contents or indexes differ from recorded digest")
        if expected_root is not None and actual != expected_root:
            errors.append("artifact does not match trusted expected root")
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            errors.append("SQLite structural integrity check failed")
        if con.execute("PRAGMA foreign_key_check").fetchone() is not None:
            errors.append("dangling artifact references")
        from .contracts import require_content_metadata
        try:
            require_content_metadata(con, manifest, counts)
        except PackError as error:
            errors.append(str(error))
        block_errors = set()
        chars = 0
        for row in con.execute("SELECT text,sha256,start_line,end_line,tokens FROM blocks"):
            chars += len(row['text'])
            if hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != row["sha256"]:
                block_errors.add("stored block hash does not match block text")
            if not _valid_block_span(row["text"], row["start_line"], row["end_line"]):
                block_errors.add("stored source span does not match block line count")
            if row['tokens'] != max(1, len(row['text'])//4):
                block_errors.add('stored block token estimate does not match block text')
        errors.extend(sorted(block_errors))
        available = max(1, (chars+2*(counts['blocks']-1))//4) if counts['blocks'] else 0
        if int(manifest['available_tokens']) != available:
            errors.append('artifact available_tokens does not match stored content')
        result = {
            "ok": not errors,
            "errors": errors,
            "verification_level": "contents_and_indexes_v8",
            "trusted_root_checked": expected_root is not None,
            "format_version": int(manifest["format_version"]),
            "mode": manifest.get("mode"),
            "embedding_model": manifest.get("embedding_model") or None,
            "recorded_root_sha256": recorded,
            "actual_root_sha256": actual,
            "counts": counts,
        }
    # FTS5 exposes its integrity-check as a transaction-local maintenance
    # command. It validates postings, segment pages, and document lengths that
    # SQLite's ordinary b-tree integrity check cannot see. The transaction is
    # always rolled back and the connection is opened only after the ordinary
    # read-only checks above have completed.
    try:
        _fts_integrity_check(path, source_parity=not result["errors"])
    except sqlite3.DatabaseError as exc:
        result["ok"] = False
        result["errors"].append(f"FTS5 integrity check failed: {exc}")
    return result


def _fts_integrity_check(path: str | Path, *, source_parity: bool = True) -> None:
    # The FTS5 maintenance command is a transaction-local write, so it needs
    # a writable connection.  Route it through the same hardened initializer as
    # update code: the connection remains writable for this one rollback-only
    # check, while extension loading, trusted-schema execution, value/SQL
    # limits, and defensive mode are still applied before the artifact is read.
    con = connect(path, readonly=False)
    try:
        con.execute("BEGIN")
        con.execute("INSERT INTO lexical(lexical) VALUES('integrity-check')")
        if source_parity:
            _fts_source_parity_check(con)
        con.execute("ROLLBACK")
    finally:
        con.close()


def _fts_source_parity_check(con: sqlite3.Connection) -> None:
    """Compare indexed postings with fields derived from authoritative blocks.

    FTS5's maintenance integrity check proves that its segment tree is
    self-consistent. It does not prove that a separately edited tree still
    represents the normalized fields the compiler intended to index. Build a
    temporary contentless index from the authoritative block rows and compare
    instance postings for set equality, together with source-derived document
    lengths and configuration. The temporary index disappears with the
    rollback-only verification transaction.
    """
    from .search import analyzed_text

    def source_path_root(value: str) -> str:
        return value.rsplit(".", 1)[0]

    # Keep derivation inside SQLite's VM so a large artifact does not make a
    # Python round trip for every block. These functions are registered only
    # on this rollback-only connection and are never read from artifact SQL.
    con.create_function("npk_analyzed_text", 1, analyzed_text, deterministic=True)
    con.create_function("npk_source_path_root", 1, source_path_root, deterministic=True)

    con.execute(
        "CREATE VIRTUAL TABLE temp.npk_expected_lexical USING fts5("
        "text, name, path, content='', "
        "tokenize=\"unicode61 remove_diacritics 2 tokenchars '_'\")"
    )
    con.execute(
        "INSERT INTO temp.npk_expected_lexical(rowid,text,name,path) "
        "SELECT b.id, npk_analyzed_text(b.text), "
        "npk_analyzed_text(coalesce(b.name,'')), "
        "npk_analyzed_text(npk_source_path_root(f.path)) "
        "FROM blocks b JOIN files f ON f.id=b.file_id"
    )
    con.execute(
        "CREATE VIRTUAL TABLE temp.npk_actual_fts_terms "
        "USING fts5vocab(main,lexical,'instance')"
    )
    con.execute(
        "CREATE VIRTUAL TABLE temp.npk_expected_fts_terms "
        "USING fts5vocab(temp,npk_expected_lexical,'instance')"
    )
    actual_count = con.execute(
        "SELECT COUNT(*) FROM temp.npk_actual_fts_terms"
    ).fetchone()[0]
    expected_count = con.execute(
        "SELECT COUNT(*) FROM temp.npk_expected_fts_terms"
    ).fetchone()[0]
    # An FTS5 instance row is unique for a term occurrence (term, document,
    # column, offset). Count equality plus one-way set inclusion therefore
    # proves equality without materializing the same EXCEPT result twice.
    if actual_count != expected_count or con.execute(
        "SELECT term,doc,col,offset FROM temp.npk_actual_fts_terms "
        "EXCEPT SELECT term,doc,col,offset FROM temp.npk_expected_fts_terms LIMIT 1"
    ).fetchone() is not None:
        raise sqlite3.DatabaseError(
            "FTS5 postings do not match source-derived lexical fields"
        )
    for table in ("lexical_docsize", "lexical_config"):
        expected_table = f"npk_expected_lexical_{table.removeprefix('lexical_')}"
        columns = "id,sz" if table == "lexical_docsize" else "k,v"
        for left_schema, left, right_schema, right in (
            ("main", table, "temp", expected_table),
            ("temp", expected_table, "main", table),
        ):
            if con.execute(
                f"SELECT {columns} FROM {left_schema}.{left} "
                f"EXCEPT SELECT {columns} FROM {right_schema}.{right} LIMIT 1"
            ).fetchone() is not None:
                raise sqlite3.DatabaseError(
                    "FTS5 document-length or configuration metadata does not "
                    "match source-derived lexical fields"
                )


def _valid_block_span(text: str, start: int, end: int) -> bool:
    """Check internal line geometry, not correspondence to external source."""
    return (type(start) is int and type(end) is int and 1 <= start <= end
            and text.count("\n") + 1 == end - start + 1)


def load_blocks(con: sqlite3.Connection, ids: Optional[List[int]] = None) -> List[Block]:
    sql = (
        "SELECT b.id, b.file_id, f.path, b.ordinal, b.kind, b.name, "
        "       b.start_line, b.end_line, b.tokens, b.text "
        "FROM blocks b JOIN files f ON f.id = b.file_id"
    )
    params: tuple = ()
    if ids is not None:
        if not ids:
            return []
        sql += f" WHERE b.id IN ({','.join('?' * len(ids))})"
        params = tuple(ids)
    sql += " ORDER BY f.path, b.ordinal"
    return [Block(**dict(r)) for r in con.execute(sql, params)]


def pack_stats(path: str | Path) -> Dict[str, Any]:
    with open_pack(path) as con:
        manifest = read_manifest(con)
        require_supported(manifest)
        total_tokens = con.execute("SELECT COALESCE(SUM(tokens),0) t FROM blocks").fetchone()["t"]
        return {
            "path": str(path),
            "size_bytes": Path(path).stat().st_size,
            "format_version": int(manifest["format_version"]),
            "mode": manifest.get("mode"),
            "files": int(manifest.get("file_count", 0)),
            "blocks": int(manifest.get("block_count", 0)),
            "relations": con.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"],
            "total_block_tokens": total_tokens,
            "embedding_model": manifest.get("embedding_model") or None,
            "embedding_status": manifest.get("embedding_status","unknown"),
            "encoder_identity": json.loads(manifest.get("encoder_identity") or "null"),
            "created_utc": manifest.get("created_utc"),
            "updated_utc": manifest.get("updated_utc"),
        }

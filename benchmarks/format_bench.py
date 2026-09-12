"""Container-format comparison for the .npk artifact.

The brief asks for the container to be chosen on evidence rather than novelty, so
this measures four candidates on the operations that actually matter for a
compile-once/query-cheaply artifact:

``sqlite``      one SQLite file (WAL off, single-file portability)
``zip``         ZIP container with per-file entries + a JSON index member
``directory``   directory bundle, one file per record + JSON index
``hybrid``      SQLite for indexes/metadata + a sidecar blob file for content

Measured:

* initial compile
* incremental single-file update (the common edit)
* 1% and 10% repository change
* random-access read latency (fetch one record by key)
* lexical query latency where the container supports it
* on-disk size
* corruption recovery (truncate the artifact, can we still read anything?)

No LLM is involved anywhere in this module.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import tempfile
import time
from typing import Any, Callable, Dict, List, Sequence, Tuple
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = REPO_ROOT / ".venv" / "Lib" / "site-packages"


def collect_corpus(max_files: int = 400, packages: Sequence[str] = ("torch", "transformers", "numpy")) -> List[Tuple[str, bytes]]:
    """Real third-party Python source, as (relative_path, bytes)."""
    out: List[Tuple[str, bytes]] = []
    for pkg in packages:
        root = SITE_PACKAGES / pkg
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                if not (500 < path.stat().st_size < 200_000):
                    continue
                out.append((path.relative_to(SITE_PACKAGES).as_posix(), path.read_bytes()))
            except OSError:
                continue
            if len(out) >= max_files:
                return out
    return out


# ---------------------------------------------------------------------------
# Candidate implementations
# ---------------------------------------------------------------------------

class Container:
    name = "base"
    supports_lexical = False

    def __init__(self, path: Path):
        self.path = path

    def build(self, records: Sequence[Tuple[str, bytes]]) -> None: ...
    def update(self, records: Sequence[Tuple[str, bytes]]) -> None: ...
    def read_one(self, key: str) -> bytes: ...
    def size_bytes(self) -> int:
        if self.path.is_dir():
            return sum(p.stat().st_size for p in self.path.rglob("*") if p.is_file())
        return self.path.stat().st_size if self.path.exists() else 0


class SqliteContainer(Container):
    name = "sqlite"
    supports_lexical = True

    def build(self, records):
        if self.path.exists():
            self.path.unlink()
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("CREATE TABLE files(path TEXT PRIMARY KEY, data BLOB, size INT)")
        con.execute("CREATE VIRTUAL TABLE lex USING fts5(path UNINDEXED, content, tokenize='unicode61')")
        con.executemany("INSERT INTO files VALUES(?,?,?)",
                        [(p, d, len(d)) for p, d in records])
        con.executemany("INSERT INTO lex VALUES(?,?)",
                        [(p, d.decode("utf-8", "ignore")) for p, d in records])
        con.commit(); con.close()

    def update(self, records):
        con = sqlite3.connect(self.path)
        for p, d in records:
            con.execute("INSERT INTO files VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET data=excluded.data, size=excluded.size",
                        (p, d, len(d)))
            con.execute("DELETE FROM lex WHERE path=?", (p,))
            con.execute("INSERT INTO lex VALUES(?,?)", (p, d.decode("utf-8", "ignore")))
        con.commit(); con.close()

    def read_one(self, key):
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        row = con.execute("SELECT data FROM files WHERE path=?", (key,)).fetchone()
        con.close()
        return row[0] if row else b""

    def lexical(self, term: str, limit: int = 10):
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        rows = con.execute("SELECT path FROM lex WHERE lex MATCH ? LIMIT ?", (term, limit)).fetchall()
        con.close()
        return rows


class ZipContainer(Container):
    name = "zip"

    def build(self, records):
        if self.path.exists():
            self.path.unlink()
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p, d in records:
                z.writestr(f"src/{p}", d)
            z.writestr("index.json", json.dumps({p: len(d) for p, d in records}))

    def update(self, records):
        # ZIP has no in-place update: the whole archive must be rewritten.
        existing: Dict[str, bytes] = {}
        with zipfile.ZipFile(self.path, "r") as z:
            for n in z.namelist():
                if n.startswith("src/"):
                    existing[n[4:]] = z.read(n)
        for p, d in records:
            existing[p] = d
        self.build(list(existing.items()))

    def read_one(self, key):
        with zipfile.ZipFile(self.path, "r") as z:
            return z.read(f"src/{key}")


class DirectoryContainer(Container):
    name = "directory"

    def build(self, records):
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        (self.path / "src").mkdir(parents=True, exist_ok=True)
        for p, d in records:
            target = self.path / "src" / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(d)
        (self.path / "index.json").write_text(json.dumps({p: len(d) for p, d in records}))

    def update(self, records):
        for p, d in records:
            target = self.path / "src" / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(d)

    def read_one(self, key):
        return (self.path / "src" / key).read_bytes()


class HybridContainer(Container):
    """SQLite index + append-only sidecar blob file."""

    name = "hybrid"
    supports_lexical = True

    @property
    def blob_path(self) -> Path:
        return self.path.with_suffix(".blob")

    def build(self, records):
        for p in (self.path, self.blob_path):
            if p.exists():
                p.unlink()
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("CREATE TABLE files(path TEXT PRIMARY KEY, offset INT, length INT)")
        con.execute("CREATE VIRTUAL TABLE lex USING fts5(path UNINDEXED, content, tokenize='unicode61')")
        offset = 0
        with self.blob_path.open("wb") as fh:
            for p, d in records:
                fh.write(d)
                con.execute("INSERT INTO files VALUES(?,?,?)", (p, offset, len(d)))
                con.execute("INSERT INTO lex VALUES(?,?)", (p, d.decode("utf-8", "ignore")))
                offset += len(d)
        con.commit(); con.close()

    def update(self, records):
        con = sqlite3.connect(self.path)
        offset = self.blob_path.stat().st_size
        with self.blob_path.open("ab") as fh:
            for p, d in records:
                fh.write(d)
                con.execute("INSERT INTO files VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET offset=excluded.offset, length=excluded.length",
                            (p, offset, len(d)))
                con.execute("DELETE FROM lex WHERE path=?", (p,))
                con.execute("INSERT INTO lex VALUES(?,?)", (p, d.decode("utf-8", "ignore")))
                offset += len(d)
        con.commit(); con.close()

    def read_one(self, key):
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        row = con.execute("SELECT offset,length FROM files WHERE path=?", (key,)).fetchone()
        con.close()
        if not row:
            return b""
        with self.blob_path.open("rb") as fh:
            fh.seek(row[0])
            return fh.read(row[1])

    def lexical(self, term: str, limit: int = 10):
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        rows = con.execute("SELECT path FROM lex WHERE lex MATCH ? LIMIT ?", (term, limit)).fetchall()
        con.close()
        return rows

    def size_bytes(self):
        return (self.path.stat().st_size if self.path.exists() else 0) + \
               (self.blob_path.stat().st_size if self.blob_path.exists() else 0)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _time(fn: Callable[[], Any], repeats: int = 1) -> float:
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def _mutate(records: Sequence[Tuple[str, bytes]], fraction: float) -> List[Tuple[str, bytes]]:
    n = max(1, int(len(records) * fraction))
    return [(p, d + b"\n# incremental edit marker\n") for p, d in records[:n]]


def bench_container(cls, records, workdir: Path) -> Dict[str, Any]:
    path = workdir / (f"pack_{cls.name}" if cls is DirectoryContainer else f"pack_{cls.name}.npk")
    c = cls(path)

    build_ms = _time(lambda: c.build(records))
    size = c.size_bytes()

    one = _mutate(records, 0.0001)
    upd1_ms = _time(lambda: c.update(one))
    upd1pct_ms = _time(lambda: c.update(_mutate(records, 0.01)))
    upd10pct_ms = _time(lambda: c.update(_mutate(records, 0.10)))

    key = records[len(records) // 2][0]
    read_ms = _time(lambda: c.read_one(key), repeats=20)

    lex_ms = None
    if getattr(c, "supports_lexical", False):
        lex_ms = _time(lambda: c.lexical("import"), repeats=10)

    # Corruption recovery: truncate the artifact to 60% and see what survives.
    survived = None
    try:
        target = path if not path.is_dir() else (path / "index.json")
        raw = target.read_bytes()
        backup = raw
        target.write_bytes(raw[: int(len(raw) * 0.6)])
        try:
            c.read_one(key)
            survived = "partial read OK"
        except Exception as exc:
            survived = f"read failed ({type(exc).__name__})"
        target.write_bytes(backup)
    except Exception as exc:
        survived = f"n/a ({type(exc).__name__})"

    return {
        "container": cls.name,
        "build_ms": round(build_ms, 1),
        "update_1_file_ms": round(upd1_ms, 2),
        "update_1pct_ms": round(upd1pct_ms, 1),
        "update_10pct_ms": round(upd10pct_ms, 1),
        "random_read_ms": round(read_ms, 3),
        "lexical_query_ms": round(lex_ms, 3) if lex_ms is not None else None,
        "size_mb": round(size / 1e6, 2),
        "corruption_behaviour": survived,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-files", type=int, default=400)
    ap.add_argument("--out", default="experiments/results/format-bench.json")
    args = ap.parse_args(argv)

    records = collect_corpus(args.max_files)
    total_mb = sum(len(d) for _p, d in records) / 1e6
    print(f"corpus: {len(records)} real source files, {total_mb:.1f} MB")

    rows = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        wd = Path(td)
        for cls in (SqliteContainer, ZipContainer, DirectoryContainer, HybridContainer):
            row = bench_container(cls, records, wd)
            rows.append(row)
            print(f"  {row['container']:10s} build={row['build_ms']:8.1f}ms "
                  f"upd1={row['update_1_file_ms']:8.2f}ms read={row['random_read_ms']:6.3f}ms "
                  f"size={row['size_mb']:6.2f}MB", flush=True)

    summary = {"corpus_files": len(records), "corpus_mb": round(total_mb, 2), "rows": rows}
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n================= CONTAINER FORMAT COMPARISON =================")
    hdr = f"{'container':11s}{'build ms':>10s}{'upd 1 file':>12s}{'upd 1%':>9s}{'upd 10%':>10s}{'read ms':>9s}{'lex ms':>8s}{'MB':>7s}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        lex = f"{r['lexical_query_ms']:.2f}" if r["lexical_query_ms"] is not None else "-"
        print(f"{r['container']:11s}{r['build_ms']:10.1f}{r['update_1_file_ms']:12.2f}"
              f"{r['update_1pct_ms']:9.1f}{r['update_10pct_ms']:10.1f}"
              f"{r['random_read_ms']:9.3f}{lex:>8s}{r['size_mb']:7.2f}")
    print("\ncorruption behaviour (artifact truncated to 60%):")
    for r in rows:
        print(f"  {r['container']:11s} {r['corruption_behaviour']}")
    print(f"\nartifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

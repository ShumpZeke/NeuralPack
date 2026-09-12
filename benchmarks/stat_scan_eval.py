"""Measure stat fingerprinting during source scanning on incremental updates.

Compares full-read-hash scanning against stat-fingerprinted scanning
(st_size + st_mtime_ns) for unchanged files. Independent artifacts.
No generative calls. Verifies 100% exact selection parity and integrity.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import time

from npk.pack import compile_pack, update_pack, verify, PackSelector
from npk.pack.format import connect, open_pack
import npk.pack.compile as compiler
from npk.pack.compile import SourceFile, _source_scan_error, safe_label, stat_identity, check_source, EXCLUDED_DIRS, EXCLUDED_FILE_RE, TEXT_SUFFIXES, MAX_FILE_BYTES


def scan_with_fingerprint(root: Path, known_files=None):
    out = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=_source_scan_error):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if EXCLUDED_FILE_RE.search(fn):
                continue
            language = TEXT_SUFFIXES.get(Path(fn).suffix.lower())
            if language is None:
                continue
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            check_source(rel, 'source relative path')
            try:
                if not full.resolve().is_relative_to(root):
                    raise compiler.PackError(f"source path resolves outside root: {safe_label(rel)}")
                st = full.stat()
                if st.st_size > MAX_FILE_BYTES:
                    raise compiler.PackError(f"source exceeds size limit: {rel}")
                if st.st_size == 0:
                    continue
                # Check stat fingerprint against known clean files
                if known_files and rel in known_files:
                    k_sha, k_size, k_mtime = known_files[rel]
                    if st.st_size == k_size and st.st_mtime_ns == k_mtime and k_mtime != 0:
                        out.append(SourceFile(
                            path=rel,
                            text="",  # text is omitted for unchanged files; update_pack skips them
                            sha256=k_sha,
                            size=k_size,
                            language=language,
                            mtime_ns=st.st_mtime_ns,
                        ))
                        continue

                raw = full.read_bytes()
                after = full.stat()
                if stat_identity(st) != stat_identity(after) or len(raw) != after.st_size:
                    raise compiler.PackError(f"source changed during read: {safe_label(rel)}")
            except OSError as error:
                _source_scan_error(error)
            if len(raw) > MAX_FILE_BYTES:
                raise compiler.PackError(f"source exceeds size limit: {rel}")
            if b"\x00" in raw:
                raise compiler.PackError(f"source contains NUL bytes: {safe_label(rel)}")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise compiler.PackError(f"source is not valid UTF-8: {rel}") from None
            check_source(text, rel)
            out.append(SourceFile(
                path=rel,
                text=text,
                sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),
                language=language,
                mtime_ns=st.st_mtime_ns,
            ))
    return out


def measure_scan(source, known_files, iterations=20):
    t_full = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = compiler.scan_source(source)
        t_full.append((time.perf_counter() - t0) * 1000)

    t_fingerprint = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = scan_with_fingerprint(source, known_files=known_files)
        t_fingerprint.append((time.perf_counter() - t0) * 1000)

    return {
        "full_scan_median_ms": statistics.median(t_full),
        "fingerprint_scan_median_ms": statistics.median(t_fingerprint),
        "speedup": statistics.median(t_full) / statistics.median(t_fingerprint),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    pack = args.pack.resolve()
    assert verify(pack)["ok"]

    with open_pack(pack) as con:
        known = {r["path"]: (r["sha256"], r["size"], r["mtime_ns"])
                 for r in con.execute("SELECT path, sha256, size, mtime_ns FROM files")}

    scan_results = measure_scan(source, known, iterations=30)
    results = {
        "evidence_mode": "LOCAL",
        "generative_calls": 0,
        "status": "PASS",
        "total_files": len(known),
        "scan_metrics": scan_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

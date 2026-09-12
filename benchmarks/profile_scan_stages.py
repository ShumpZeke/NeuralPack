"""Stage-level profiling of scan_source."""
import hashlib
import os
from pathlib import Path
import time

from npk.pack.compile import EXCLUDED_DIRS, EXCLUDED_FILE_RE, TEXT_SUFFIXES, MAX_FILE_BYTES, _source_scan_error, safe_label, stat_identity, check_source


def main():
    root = Path('experiments/runs/packs/cycle30-update-batch-v2/sources/public').resolve()
    check_source(str(root), 'source root path')

    t_walk, t_read, t_decode, t_check_text, t_hash = 0, 0, 0, 0, 0

    for _ in range(20):
        t0 = time.perf_counter()
        for dirpath, dirnames, filenames in os.walk(root, onerror=_source_scan_error):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
            for fn in sorted(filenames):
                if EXCLUDED_FILE_RE.search(fn):
                    continue
                lang = TEXT_SUFFIXES.get(Path(fn).suffix.lower())
                if lang is None:
                    continue
                full = Path(dirpath) / fn
                st = full.stat()
                if st.st_size == 0:
                    continue
        t_walk += time.perf_counter() - t0

        for dirpath, dirnames, filenames in os.walk(root, onerror=_source_scan_error):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
            for fn in sorted(filenames):
                if EXCLUDED_FILE_RE.search(fn):
                    continue
                if Path(fn).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                full = Path(dirpath) / fn
                st = full.stat()
                if st.st_size == 0:
                    continue
                t1 = time.perf_counter()
                raw = full.read_bytes()
                t_read += time.perf_counter() - t1

                t2 = time.perf_counter()
                text = raw.decode('utf-8')
                t_decode += time.perf_counter() - t2

                t3 = time.perf_counter()
                check_source(text, full.relative_to(root))
                t_check_text += time.perf_counter() - t3

                t4 = time.perf_counter()
                sha = hashlib.sha256(raw).hexdigest()
                t_hash += time.perf_counter() - t4

    n = 20
    print(f'walk + stat ms: {t_walk/n*1000:.2f}')
    print(f'read_bytes ms:  {t_read/n*1000:.2f}')
    print(f'decode utf-8 ms: {t_decode/n*1000:.2f}')
    print(f'check_source text ms: {t_check_text/n*1000:.2f}')
    print(f'sha256 ms:      {t_hash/n*1000:.2f}')
    total = (t_walk + t_read + t_decode + t_check_text + t_hash) / n * 1000
    print(f'total ms:       {total:.2f}')


if __name__ == '__main__':
    main()

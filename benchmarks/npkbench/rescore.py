"""Score a finished run's selections against another gold target, offline.

    python -m benchmarks.npkbench.rescore RUN --split dev-fast:docs

Selection never sees gold, so the spans a run stored can be scored against a
target it was not run with, e.g. a later, corrected docs gold. Only rows of the
run's primary target are rescored (arm names without ``@``/``~``); tasks that
are not in the requested split are dropped. The result is written as a
separate run directory ``RUN/rescore-<split>-<version>/`` (rows, config,
summary), so ``report --compare`` works on it and the original rows are never
modified. Ranking metrics (tokens-to-find) need full rankings and are not
rescored.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import List

from . import data, metrics, report


def rescore(run: Path, split: str) -> Path:
    tasks = {t.instance_id: t for t in data.split(split)}
    label = f"rescore-{split.replace(':', '-')}-" + (data.DOCS_VERSION if split.endswith(":docs")
                                                      else data.BENCH_VERSION)
    out = run / label
    out.mkdir(exist_ok=True)
    rows: List[dict] = []
    for row in report._read(run / "rows.jsonl"):
        if "@" in row["arm"] or "~" in row["arm"] or row["instance_id"] not in tasks:
            continue
        new = dict(row)  # every metric key is recomputed below
        new.update(metrics.score(tasks[row["instance_id"]], [tuple(s) for s in row["spans"]]))
        rows.append(new)
    with gzip.open(out / "rows.jsonl.gz", "wt") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    config = {"rescored_from": str(run), "split": split, "tasks": len({r["instance_id"] for r in rows}),
              "tasks_in_split": len(tasks), "docs_version": data.DOCS_VERSION,
              "bench_version": data.BENCH_VERSION}
    (out / "config.json").write_text(json.dumps(config, indent=1))
    (out / "summary.json").write_text(json.dumps(report.summarize(out), indent=1, sort_keys=True))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--split", required=True, help="e.g. dev-fast:docs")
    args = parser.parse_args(argv)
    out = rescore(args.run, args.split)
    print(out)
    print(report.render(report.summarize(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

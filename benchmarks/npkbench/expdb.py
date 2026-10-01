"""Machine-readable experiment history: experiments/npkbench/EXPERIMENTS.jsonl.

    python -m benchmarks.npkbench.expdb render   # regenerate EXPERIMENTS.md

One JSON object per experiment, append-only; a later record with the same
``id`` supersedes earlier ones (for status updates). Required fields:
id, date, title, hypothesis, status (running|kept|rejected|inconclusive),
reason. Optional: expected, branch, commit, files_changed, bench_version,
baseline_run, run, results, tradeoffs, followups.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "experiments" / "npkbench" / "EXPERIMENTS.jsonl"
MD = ROOT / "experiments" / "npkbench" / "EXPERIMENTS.md"
REQUIRED = ("id", "date", "title", "hypothesis", "status", "reason")
STATUSES = ("running", "kept", "rejected", "inconclusive")


def records() -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    if DB.exists():
        for line in DB.read_text().splitlines():
            if line.strip():
                item = json.loads(line)
                latest[item["id"]] = item
    return sorted(latest.values(), key=lambda r: r["id"])


def append(record: Dict[str, Any]) -> None:
    missing = [k for k in REQUIRED if k not in record]
    if missing or record["status"] not in STATUSES:
        raise ValueError(f"invalid experiment record: missing={missing} status={record.get('status')}")
    DB.parent.mkdir(parents=True, exist_ok=True)
    with DB.open("a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    render()


def render() -> None:
    out = ["# NPK-Bench experiment history", "",
           "Generated from `EXPERIMENTS.jsonl` by `python -m benchmarks.npkbench.expdb render`.",
           "Do not edit by hand.", "",
           "| ID | Date | Title | Status | Reason |", "|---|---|---|---|---|"]
    for r in records():
        reason = r["reason"].replace("|", "/").replace("\n", " ")
        out.append(f"| {r['id']} | {r['date']} | {r['title']} | **{r['status']}** | {reason} |")
    for r in records():
        out += ["", f"## {r['id']} — {r['title']}", "",
                f"- **Status:** {r['status']}", f"- **Hypothesis:** {r['hypothesis']}"]
        for key in ("expected", "baseline_run", "run", "commit", "bench_version"):
            if r.get(key):
                out.append(f"- **{key.replace('_', ' ').capitalize()}:** {r[key]}")
        if r.get("files_changed"):
            out.append("- **Files changed:** " + ", ".join(f"`{f}`" for f in r["files_changed"]))
        if r.get("results"):
            out += ["- **Results:**", "", "```json", json.dumps(r["results"], indent=1), "```", ""]
        if r.get("tradeoffs"):
            out.append(f"- **Tradeoffs:** {r['tradeoffs']}")
        out.append(f"- **Decision:** {r['reason']}")
        if r.get("followups"):
            out.append("- **Follow-ups:** " + "; ".join(r["followups"]))
    MD.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["render"]:
        render()
    else:
        print(json.dumps(records(), indent=1))

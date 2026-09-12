"""Create an auditable Obsidian checkpoint without copying models/caches or secrets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", required=True, help="Concrete action/result to append")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    git = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True)
    record = {"utc": now.isoformat(), "note": args.note, "git_status": git.stdout.splitlines(), "files": []}
    allowed = ("npk", "benchmarks", "research", "docs", "tests", "scripts")
    for name in allowed:
        for path in sorted((ROOT / name).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix not in (".py", ".md", ".json"):
                continue
            data = path.read_bytes()
            record["files"].append({"path": path.relative_to(ROOT).as_posix(), "bytes": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest()})
    journal = ROOT / "Neural Pack" / "Journal"
    journal.mkdir(parents=True, exist_ok=True)
    with (journal / "actions.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (journal / f"{now.date()}.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n## {now.strftime('%H:%M:%S')} UTC checkpoint\n\n{args.note}\n\n"
                     f"Recorded hashes of {len(record['files'])} source/research/test files in `actions.jsonl`. "
                     "This is an action/artifact audit, not a transcript of private reasoning.\n")
    print(json.dumps({"utc": record["utc"], "recorded_files": len(record["files"])}))


if __name__ == "__main__":
    main()

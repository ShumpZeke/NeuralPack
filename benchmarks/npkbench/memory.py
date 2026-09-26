"""Conversation-memory workload: LongMemEval-S chat histories as NPK corpora.

Each question comes with its own ~120K-token history of ~50 dated chat
sessions. A history is materialized once as ``sessions/<date>_<id>.md`` files
(a ``#`` session header, then one ``##`` heading per turn carrying role and
timestamp), compiled by the unmodified product compiler, and queried with the
question text. Gold is the line span of every turn LongMemEval marks as
evidence (``has_answer``); for questions whose evidence is marked only at the
session level, the whole answer session is gold. Abstention questions
(``*_abs``) have no retrievable answer and are excluded.

Scores reuse NPK-Bench metrics: ``hunk_recall`` = evidence-turn recall,
``file_recall`` = answer-session recall.

Source: https://huggingface.co/datasets/xiaowu0162/longmemeval (MIT),
pinned by revision and SHA-256. Nothing from it is committed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .data import HOME, Hunk, Task, _stable_hash

SOURCE = ("xiaowu0162/longmemeval", "2ec2a557f339b6c0369619b1ed5793734cc87533", "longmemeval_s",
          "08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894")
ROOT = HOME / "memory"
TREES = ROOT / "trees"
INDEX = ROOT / "index-v1.json"
#: Data-level layout variants used to test representation hypotheses before
#: changing the compiler. ``turn``: one section per turn (default).
#: ``para``: turns longer than PARA_CHARS also get one ``###`` section per
#: paragraph, so the unchanged markdown splitter emits paragraph blocks.
LAYOUTS = ("turn", "para")
PARA_CHARS = 1200


def download() -> Path:
    import urllib.request

    repo, revision, name, digest = SOURCE
    target = HOME / "datasets" / f"{name}-{digest[:12]}.json"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{name}"
        tmp = target.with_suffix(".tmp")
        h = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=600) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 20):
                h.update(chunk)
                out.write(chunk)
        if h.hexdigest() != digest:
            tmp.unlink()
            raise RuntimeError("LongMemEval download does not match the pinned digest")
        tmp.replace(target)
    return target


def _slug(date: str) -> str:
    # "2023/05/20 (Sat) 02:21" -> "2023-05-20_0221"
    m = re.match(r"(\d{4})/(\d{2})/(\d{2}) \(\w+\) (\d{2}):(\d{2})", date)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}_{m.group(4)}{m.group(5)}" if m else "undated"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _trees(layout: str) -> Path:
    return TREES if layout == "turn" else ROOT / f"trees-{layout}"


def _materialize(item: Dict, layout: str = "turn") -> Dict:
    """Write one history; return gold spans and metadata. Deterministic."""
    qid = item["question_id"]
    base = _trees(layout) / qid / "sessions"
    base.mkdir(parents=True, exist_ok=True)
    gold_turns: List[Tuple[str, int, int]] = []
    answer_files: List[Tuple[str, int]] = []
    answer_ids = set(item["answer_session_ids"])
    for index, (sid, date, turns) in enumerate(zip(item["haystack_session_ids"],
                                                    item["haystack_dates"],
                                                    item["haystack_sessions"])):
        rel = f"sessions/{_slug(date)}_{index:03d}_{re.sub(r'[^A-Za-z0-9_-]', '_', sid)}.md"
        lines = [f"# Session {sid} · {date}", ""]
        for number, turn in enumerate(turns):
            lines.append(f"## {turn['role']} · turn {number} · {date}")
            start = len(lines) + 1
            content = turn["content"].replace("\r\n", "\n").replace("\r", "\n")
            body = content.split("\n")
            if layout == "para" and len(content) > PARA_CHARS:
                part = 0
                for index_line, line in enumerate(body):
                    starts_paragraph = index_line == 0 or (not body[index_line - 1].strip() and line.strip())
                    if starts_paragraph and index_line > 0:
                        part += 1
                        lines.append(f"### {turn['role']} · turn {number} · part {part}")
                    lines.append(line)
            else:
                lines.extend(body)
            end = len(lines)
            lines.append("")
            if turn.get("has_answer"):
                gold_turns.append((rel, start - 1, end))  # heading line through body
        (_trees(layout) / qid / rel).write_text("\n".join(lines) + "\n", encoding="utf-8")
        if sid in answer_ids:
            answer_files.append((rel, len(lines)))
    return {"question_id": qid, "question_type": item["question_type"], "question": item["question"],
            "question_date": item["question_date"], "answer": str(item["answer"]),
            "gold_turns": gold_turns, "answer_files": answer_files}


def build_index(layout: str = "turn") -> List[Dict]:
    path = INDEX if layout == "turn" else ROOT / f"index-v1-{layout}.json"
    if path.exists():
        return json.loads(path.read_text())
    items = json.loads(download().read_text())
    index = [dict(_materialize(item, layout), layout=layout) for item in items]
    ROOT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index))
    return index


def _task(entry: Dict) -> Task:
    if entry["gold_turns"]:
        hunks = [Hunk(p, tuple(range(lo, hi + 1)), ()) for p, lo, hi in entry["gold_turns"]]
    else:
        hunks = [Hunk(p, tuple(range(1, n + 1)), ()) for p, n in entry["answer_files"]]
    layout = entry.get("layout", "turn")
    suffix = "" if layout == "turn" else f"@{layout}"
    return Task(instance_id=entry["question_id"] + suffix, repo=f"longmemeval/{entry['question_type']}",
                base_commit="", query=entry["question"], hunks=hunks,
                created_at=entry["question_date"], source="longmemeval_s")


def tree(task: Task) -> Path:
    qid, _, layout = task.instance_id.partition("@")
    return _trees(layout or "turn") / qid


def split(name: str) -> List[Task]:
    """``memory-dev``: 100 questions stratified by type; ``memory-heldout``: the rest.

    ``<split>@<layout>`` selects a data-level layout variant (same questions).
    """
    name, _, layout = name.partition("@")
    entries = [e for e in build_index(layout or "turn") if not e["question_id"].endswith("_abs")]
    by_type: Dict[str, List[Dict]] = {}
    for entry in entries:
        by_type.setdefault(entry["question_type"], []).append(entry)
    dev: List[Dict] = []
    for qtype, items in sorted(by_type.items()):
        items.sort(key=lambda e: _stable_hash("memory-dev:" + e["question_id"]))
        dev.extend(items[:max(4, round(100 * len(items) / len(entries)))])
    dev_ids = {e["question_id"] for e in dev}
    if name == "memory-dev":
        chosen = dev
    elif name == "memory-heldout":
        chosen = [e for e in entries if e["question_id"] not in dev_ids]
    else:
        raise ValueError(f"unknown memory split {name!r}")
    return [_task(e) for e in sorted(chosen, key=lambda e: e["question_id"])]

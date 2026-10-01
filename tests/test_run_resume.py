"""An interrupted benchmark run resumes from its journal, and only when that is safe.

A VM restart or a kill must not discard hours of finished tasks, but a resumed run must give
the rows an uninterrupted run would have given: nothing that determines them may have changed,
a torn journal tail must be ignored, and tasks are never counted twice.
"""
import gzip
import importlib.util
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from benchmarks.npkbench import run

REPO = Path(__file__).resolve().parents[1]
TASKS = 20


def entry(iid, errors=None, t=1.0):
    return {"instance_id": iid, "t": t, "result": {
        "instance_id": iid, "rows": [{"instance_id": iid}], "ranks": [], "builds": [],
        "errors": errors or []}}


def write_journal(path, entries, tail=b""):
    path.write_bytes(b"".join(run.journal_line(e) for e in entries) + tail)


CONFIG = {"split": "s", "arms": ["a"], "budgets": [1024], "tasks": 2, "task_ids_sha256": "x",
          "repos": "", "limit": 0, "targets": ["fix"], "ephemeral_packs": False, "load": [],
          "environment": {"python": "3.12.1", "sqlite": "3.45", "platform": "p", "cpus": 4,
                          "bench_version": "1", "git_commit": "abc", "git_dirty": False},
          "started_unix": 1.0, "source_digest": "d", "compiler_fingerprints": {"a": "f"}}


def changed(**updates):
    config = json.loads(json.dumps(CONFIG))
    for key, value in updates.items():
        if key.startswith("environment."):
            config["environment"][key.split(".", 1)[1]] = value
        else:
            config[key] = value
    return config


def test_config_ignores_only_clock_resume_log_and_commit():
    same = changed(started_unix=99.0, resumes=[{"tasks_done": 3}], **{
        "environment.git_commit": "def", "environment.git_dirty": True})
    assert run.config_mismatch(CONFIG, same) is None
    for key, value in (("arms", ["a", "b"]), ("budgets", [2048]), ("split", "t"), ("limit", 5),
                       ("source_digest", "other"), ("task_ids_sha256", "y"), ("load", ["m"]),
                       ("ephemeral_packs", True), ("targets", ["fix", "tests"]),
                       ("compiler_fingerprints", {"a": "g"})):
        assert run.config_mismatch(CONFIG, changed(**{key: value})) == key
    for sub, value in (("python", "3.13.0"), ("sqlite", "3.46"), ("cpus", 2), ("platform", "q"),
                       ("bench_version", "2")):
        assert run.config_mismatch(CONFIG, changed(**{f"environment.{sub}": value})) == f"environment.{sub}"


def test_journal_reading_stops_at_a_torn_tail(tmp_path):
    path = tmp_path / "journal.jsonl"
    wanted = {"t1", "t2", "t3", "t4", "t5"}
    for tail in (b'{"instance_id": "t4", "t": 2.0, "res', b"\x00\x00\xff\xfe garbage", b"\n", b"[1, 2]\n",
                 b'{"instance_id": "t4", "result": {"instance_id": "other", "rows": [], "ranks": [], '
                 b'"builds": [], "errors": []}}\n'):
        write_journal(path, [entry("t1"), entry("t2"), entry("t3")], tail=tail)
        done = run.read_journal(path, wanted)
        assert sorted(done) == ["t1", "t2", "t3"], tail
    # A well-formed entry after the torn line is not trusted either.
    write_journal(path, [entry("t1")], tail=b"torn\n" + run.journal_line(entry("t2")))
    assert sorted(run.read_journal(path, wanted)) == ["t1"]


def test_journal_reading_keeps_first_duplicate_and_skips_unknown_and_error_tasks(tmp_path):
    path = tmp_path / "journal.jsonl"
    first = entry("t1", t=1.0)
    second = entry("t1", t=2.0)
    write_journal(path, [first, entry("zz"), entry("t2", errors=[{"error": "OSError: disk full"}]),
                         second, entry("t3")])
    done = run.read_journal(path, {"t1", "t2", "t3"})
    assert sorted(done) == ["t1", "t3"]  # t2 recorded an error: it is run again
    assert done["t1"]["t"] == 1.0
    assert run.read_journal(tmp_path / "missing.jsonl", {"t1"}) == {}


def test_rewriting_the_journal_drops_the_tail_and_leaves_no_temporary(tmp_path):
    path = tmp_path / "journal.jsonl"
    write_journal(path, [entry("t1"), entry("t2")], tail=b'{"instance_id": "t3", "res')
    kept = list(run.read_journal(path, {"t1", "t2", "t3"}).values())
    run.rewrite_journal(path, kept)
    assert path.read_bytes() == b"".join(run.journal_line(e) for e in kept)
    assert [p.name for p in tmp_path.iterdir()] == ["journal.jsonl"]


def test_resume_state_requires_a_journal_and_matching_config(tmp_path):
    partial = tmp_path / "run.partial"
    partial.mkdir()
    ids = {"t1", "t2"}
    done, old, why = run.resume_state(partial, CONFIG, ids)
    assert old is None and "config.json" in why
    (partial / "config.json").write_text(json.dumps(CONFIG))
    done, old, why = run.resume_state(partial, CONFIG, ids)
    assert old is None and "journal" in why  # written by a harness without journals
    write_journal(partial / "journal.jsonl", [entry("t1")])
    done, old, why = run.resume_state(partial, changed(source_digest="edited"), ids)
    assert old is None and done == {} and why.startswith("source_digest")
    done, old, why = run.resume_state(partial, changed(started_unix=5.0), ids)
    assert old == CONFIG and sorted(done) == ["t1"] and why == ""


def test_source_digest_follows_the_code_that_produces_rows(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "npk" / "pack" / "__pycache__").mkdir(parents=True)
    (root / "benchmarks" / "npkbench" / "prototypes").mkdir(parents=True)
    product = root / "npk" / "pack" / "select.py"
    product.write_text("x = 1\n")
    (root / "benchmarks" / "npkbench" / "arms.py").write_text("y = 1\n")
    proto = root / "benchmarks" / "npkbench" / "prototypes" / "proto.py"
    proto.write_text("z = 1\n")
    base = run.source_digest(root, [])
    assert run.source_digest(root, []) == base
    (root / "npk" / "pack" / "__pycache__" / "select.cpython-312.pyc").write_bytes(b"cache")
    assert run.source_digest(root, []) == base  # bytecode caches are not code
    proto.write_text("z = 2\n")
    assert run.source_digest(root, []) == base  # an arm module the run does not load is not either
    product.write_text("x = 2\n")
    edited = run.source_digest(root, [])
    assert edited != base
    product.write_text("x = 1\n")
    assert run.source_digest(root, []) == base
    (root / "benchmarks" / "npkbench" / "arms.py").write_text("y = 2\n")
    assert run.source_digest(root, []) != base
    (root / "benchmarks" / "npkbench" / "arms.py").write_text("y = 1\n")
    assert run.source_digest(root, ["json"]) != base  # a module named by --load joins the digest
    # A helper that a loaded arm module imported joins it too, once it is loaded.
    helper = root / "benchmarks" / "npkbench" / "prototypes" / "helper.py"
    helper.write_text("h = 1\n")
    spec = importlib.util.spec_from_file_location("resume_test_helper", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert run.source_digest(root, []) == base
    monkeypatch.setitem(sys.modules, "resume_test_helper", module)
    with_helper = run.source_digest(root, [])
    assert with_helper != base
    helper.write_text("h = 2\n")
    assert run.source_digest(root, []) != with_helper


CHILD = textwrap.dedent('''
    import os, sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from benchmarks.npkbench import arms as arms_mod, data, packs, run

    root, calls, n, out = Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    packs.ROOT = root

    class Task:
        def __init__(self, i):
            self.instance_id = "t%02d" % i
            self.repo = "o/r"

    class Arm:
        compile_options = None

    offset = int(os.environ.get("TASK_OFFSET", "0"))
    data.split = lambda name: [Task(i + offset) for i in range(n)]
    arms_mod.get = lambda name: Arm()
    packs.compiler_fingerprint = lambda options: "fp"

    def fake_job(args):
        task = args[0]
        with calls.open("a") as fh:
            fh.write(task.instance_id + "\\n")
        time.sleep(0.3)
        row = {"instance_id": task.instance_id, "repo": "o/r", "arm": "a", "budget": 1024, "tokens": 10,
               "latency_ms": 1.0, "status": "selected", "n_blocks": 1, "hunk_recall": 1.0,
               "file_recall": 1.0, "all_found": 1.0, "line_recall": 1.0, "spans": []}
        return {"instance_id": task.instance_id, "rows": [row], "ranks": [], "builds": [], "errors": []}

    run._job = fake_job
    raise SystemExit(run.main(["--split", "fake", "--arms", "a", "--budgets", "1024", "--workers", "2",
                               "--out", out, *sys.argv[6:]]))
''')


class Scenario:
    def __init__(self, tmp_path):
        self.root = tmp_path / "repo"
        (self.root / "npk").mkdir(parents=True)
        (self.root / "npk" / "mod.py").write_text("VALUE = 1\n")
        (self.root / "benchmarks" / "npkbench").mkdir(parents=True)
        self.script = tmp_path / "child.py"
        self.script.write_text(CHILD)
        self.calls = tmp_path / "calls.txt"
        self.out = tmp_path / "out" / "run"
        self.out.parent.mkdir()
        self.partial = self.out.with_name("run.partial")

    def command(self, *extra):
        return [sys.executable, str(self.script), str(REPO), str(self.root), str(self.calls), str(TASKS),
                str(self.out), *extra]

    def finish(self, *extra, env=None):
        done = subprocess.run(self.command(*extra), capture_output=True, text=True, cwd=REPO, timeout=120,
                              env={**os.environ, **(env or {})})
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    def kill_after_journaled(self, tasks=3, *extra):
        proc = subprocess.Popen(self.command(*extra), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=REPO, start_new_session=True)
        journal = self.partial / run.JOURNAL
        deadline = time.time() + 60
        try:
            while time.time() < deadline:
                if journal.exists() and journal.read_bytes().count(b"\n") >= tasks:
                    break
                assert proc.poll() is None, "the run ended before it could be interrupted"
                time.sleep(0.02)
            else:
                pytest.fail("the run journaled nothing")
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        return set(run.read_journal(journal, {f"t{i:02d}" for i in range(TASKS)}))

    def called(self):
        counts = {}
        for line in self.calls.read_text().split():
            counts[line] = counts.get(line, 0) + 1
        return counts

    def result_rows(self):
        text = gzip.decompress((self.out / "rows.jsonl.gz").read_bytes()).decode()
        return [json.loads(line) for line in text.splitlines()]


def test_killed_run_resumes_and_matches_an_uninterrupted_run(tmp_path):
    interrupted = Scenario(tmp_path / "interrupted")
    finished_before = interrupted.kill_after_journaled(3)
    assert 3 <= len(finished_before) < TASKS
    assert not interrupted.out.exists() and interrupted.partial.exists()
    # The process died in the middle of writing a journal line.
    with (interrupted.partial / run.JOURNAL).open("ab") as fh:
        fh.write(b'{"instance_id": "t19", "t": 1.0, "result": {"instance_id": "t1\x00\xff')
    stdout = interrupted.finish()
    assert f"resuming run: {len(finished_before)}/{TASKS} tasks already done" in stdout
    counts = interrupted.called()
    assert sorted(counts) == [f"t{i:02d}" for i in range(TASKS)]
    assert all(counts[iid] == 1 for iid in finished_before)  # finished tasks are not run again
    # Only tasks that were running (or finishing) when it was killed can have been run twice.
    repeated = {iid for iid, count in counts.items() if count > 1}
    assert max(counts.values()) <= 2 and len(repeated) <= 6
    rows = interrupted.result_rows()
    assert sorted(r["instance_id"] for r in rows) == [f"t{i:02d}" for i in range(TASKS)]
    summary = json.loads((interrupted.out / "summary.json").read_text())
    assert summary["tasks"] == TASKS and summary["resumes"] == 1 and summary["errors"] == 0
    config = json.loads((interrupted.out / "config.json").read_text())
    assert config["resumes"][0]["tasks_done"] == len(finished_before)
    assert not (interrupted.out / run.JOURNAL).exists()
    assert not interrupted.partial.exists()

    straight = Scenario(tmp_path / "straight")
    straight.finish()
    assert "resumes" not in json.loads((straight.out / "summary.json").read_text())
    key = lambda r: r["instance_id"]
    assert sorted(rows, key=key) == sorted(straight.result_rows(), key=key)


def test_a_run_interrupted_twice_resumes_twice(tmp_path):
    scenario = Scenario(tmp_path)
    first = scenario.kill_after_journaled(3)
    with (scenario.partial / run.JOURNAL).open("ab") as fh:
        fh.write(b'{"instance_id": "t18", "t": 1.0, "resu')
    second = scenario.kill_after_journaled(len(first) + 3)  # appends to the journal the first attempt left
    assert first < second < {f"t{i:02d}" for i in range(TASKS)}
    stdout = scenario.finish()
    assert f"resuming run: {len(second)}/{TASKS} tasks already done (2 interruption(s))" in stdout
    counts = scenario.called()
    assert all(counts[iid] == 1 for iid in first)
    assert all(counts[iid] <= 2 for iid in counts)
    assert sorted(r["instance_id"] for r in scenario.result_rows()) == [f"t{i:02d}" for i in range(TASKS)]
    config = json.loads((scenario.out / "config.json").read_text())
    assert [r["tasks_done"] for r in config["resumes"]] == [len(first), len(second)]
    carried = [r["active_s_before"] for r in config["resumes"]]
    assert 0.25 <= carried[0] < carried[1]  # each finished task took 0.3 s of work
    summary = json.loads((scenario.out / "summary.json").read_text())
    assert summary["resumes"] == 2 and summary["elapsed_s"] > carried[1]


@pytest.mark.parametrize("change", ["source", "fresh", "tasks"])
def test_a_changed_run_does_not_resume(tmp_path, change):
    scenario = Scenario(tmp_path)
    finished_before = scenario.kill_after_journaled(3)
    extra, env = (), None
    if change == "source":
        (scenario.root / "npk" / "mod.py").write_text("VALUE = 2\n")
        reason = "source_digest differs"
    elif change == "tasks":
        env = {"TASK_OFFSET": "100"}  # as many tasks, other instances
        reason = "task_ids_sha256 differs"
    else:
        extra = ("--fresh",)
        reason = "--fresh"
    stdout = scenario.finish(*extra, env=env)
    assert f"discarding the interrupted attempt of run: {reason}" in stdout
    assert "resuming" not in stdout
    counts = scenario.called()
    assert all(counts[iid] == (1 if change == "tasks" else 2) for iid in finished_before)
    assert "resumes" not in json.loads((scenario.out / "summary.json").read_text())
    expected = [f"t{i + (100 if change == 'tasks' else 0):02d}" for i in range(TASKS)]
    assert sorted(r["instance_id"] for r in scenario.result_rows()) == expected

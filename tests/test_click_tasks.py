"""New workload oracles must run reproducibly without inherited environment."""
import json
from pathlib import Path

import pytest

pytest.importorskip("click")
from benchmarks.click_tasks import dataset, ENV_NAMES, payload_env, multiple_env


def test_click_oracles_match_the_frozen_prospective_dataset(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.setenv(name,"inherited-distractor")
    frozen=json.loads((Path(__file__).resolve().parents[1]/"experiments/results/cycle10-click-tasks.json").read_text())
    assert json.loads(json.dumps(dataset()))==frozen["dataset"]
    assert json.loads(json.dumps(dataset()))==frozen["dataset"]
    import os
    assert all(os.environ[name]=="inherited-distractor" for name in ENV_NAMES)


def test_false_flag_payload_is_a_string_and_unpaired_env_word_is_dropped():
    # Surprises reproduced while verifying the evaluator, before retrieval.
    assert payload_env()["false_text"]==[0,"False"]
    assert multiple_env()["odd"]==[0,[["red",1]]]

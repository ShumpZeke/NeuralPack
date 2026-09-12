"""Permanent executable counterexamples used by the frozen cycle-14 workload."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
import pytest
from benchmarks.stdlib_tasks import TASKS


@pytest.mark.parametrize('task', TASKS, ids=lambda t: t.id)
def test_frozen_stdlib_behavior(task):
    if sys.version_info[:3] != (3,12,10):
        pytest.skip('workload oracle is pinned to CPython 3.12.10')
    path = Path(__file__).resolve().parents[1]/'experiments/results/cycle14-stdlib-tasks.json'
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == path.with_suffix('.sha256').read_text().strip()
    frozen = next(t for t in json.loads(raw)['tasks'] if t['id'] == task.id)
    with patch('socket.socket.connect', side_effect=AssertionError('oracle attempted network')):
        assert task.oracle() == frozen['answer']

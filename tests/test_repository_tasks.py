"""Negative controls for source-grounded executable benchmark answers."""
import pytest

urllib3 = pytest.importorskip("urllib3")


def test_real_repository_oracles_are_executable_and_versioned():
    from benchmarks.repository_tasks import dataset
    data = dataset()
    tasks = {t["id"]:t for t in data["tasks"]}
    assert data["version"] == urllib3.__version__
    assert len(tasks) == 12
    assert tasks["disabled_vs_zero"]["answer"] == {"disabled":"ReadTimeoutError", "zero":"MaxRetryError"}
    assert tasks["eligible_but_exhausted"]["answer"] == {"eligible":True, "increment_outcome":"MaxRetryError"}
    assert tasks["zero_delay_header"]["answer"] == {"zero_header":[2.0], "positive_header":[3]}
    assert tasks["redirect_header_scope"]["answer"]["cross_host"] == ["accept"]
    assert data["source_manifest"]
    for task in tasks.values():
        assert task["required"] and task["answer"]
        assert all(0 < r["span"][0] <= r["span"][1] for r in task["required"])

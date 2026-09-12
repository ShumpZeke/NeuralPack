"""Synthetic report plumbing; these fixtures are not answer-quality evidence."""
from copy import deepcopy

import pytest

from benchmarks.prospective_report import pareto, summarize


def trial():
    rows=[]
    for method in ("bm25_windows","hybrid_members"):
        for budget in (20,40):
            for task in ("one","two"):
                rows.append({"task":task,"method":method,"budget":budget,
                             "request_sha256":f"{method}-{budget}-{task}","evidence_mode":"LIVE",
                             "transport_success":True,"api_attempts_this_run":1,
                             "task_success":True,"parse_error":False,"content":'{"value":7}',
                             "selected_tokens":budget,"selection_ms":1.0,"latency_ms":100,
                             "usage":{"prompt_tokens":budget+10,"completion_tokens":4}})
    return {"plan_sha256":"synthetic","answer_attempts_in_ledger":8,"generative_optimization_calls":0,
            "plan":{"dataset":{"tasks":[{"id":t,"answer":{"value":7}} for t in ("one","two")]},
                    "settings":{},"corpus_tokens":100,"available_tokens":110,"observations":deepcopy(rows)},
            "rows":rows}


def test_curve_uses_one_cohort_across_all_methods_and_budgets():
    data=trial()
    row=data["rows"][-1]
    row.update(transport_success=False,task_success=None,content=None,error_type="TimeoutError",usage=None)
    report=summarize(data)
    assert report["common_completed_tasks"]==["one"]
    assert all(p["cohort_tasks"]==1 for p in report["common_cohort_curves"])
    large=next(a for a in report["arms"] if a["method"]=="hybrid_members" and a["budget"]==40)
    assert large["planned"]==2 and large["completed"]==1 and large["transport_errors"]==1
    assert large["observed_successes_per_planned"]==.5
    assert [p["completed_pairs"] for p in report["paired_same_budget"]]==[2,1]


def test_pairs_never_mix_budgets_and_replay_usage_is_not_double_counted():
    data=trial()
    for row in data["rows"]:
        if row["method"]=="bm25_windows" and row["budget"]==20:
            row.update(task_success=False,content='{"value":6}')
    # One identical request reused across two method observations.
    data["rows"][6]["request_sha256"]=data["rows"][2]["request_sha256"]
    data["rows"][6].update(evidence_mode="REPLAY",api_attempts_this_run=0)
    report=summarize(data)
    assert [(p["wins"],p["losses"],p["ties"]) for p in report["paired_same_budget"]]==[(2,0,0),(0,0,2)]
    assert report["unique_request_usage"]["prompt_tokens"]["requests_reporting"]==7
    assert report["unique_request_usage"]["prompt_tokens"]["reported_total"]==270


def test_missing_usage_or_answers_cannot_create_a_cheap_frontier_point():
    data=trial()
    data["rows"][0]["usage"]=None
    report=summarize(data)
    point=report["common_cohort_curves"][0]
    assert point["mean_input_tokens"] is None
    assert point not in report["empirical_input_quality_frontier"]
    for row in data["rows"]:
        row.update(transport_success=False,task_success=None,content=None,evidence_mode="PENDING",usage=None)
        row.pop("transport_success")
    report=summarize(data)
    assert report["common_completed_tasks"]==[] and report["empirical_input_quality_frontier"]==[]
    assert all(a["success_rate_completed"] is None for a in report["arms"])
    assert report["unique_request_usage"]["prompt_tokens"]["reported_total"] is None


def test_omitted_observation_and_favorable_grade_edit_are_rejected():
    data=trial();data["rows"].pop()
    with pytest.raises(ValueError,match="frozen observations"):
        summarize(data)
    data=trial();data["rows"][0]["content"]='{"value":6}'
    with pytest.raises(ValueError,match="stored grade"):
        summarize(data)


def test_pareto_requires_a_strict_improvement_and_keeps_equal_points():
    points=[{"mean_input_tokens":tokens,"success_rate":score} for tokens,score in
            ((100,.5),(200,.5),(200,.75),(200,.75),(300,.6),(None,1),(1,None))]
    assert pareto(points)==[points[0],points[2],points[3]]


def test_wrong_output_keys_remain_failures_but_are_disclosed_as_protocol_errors():
    data=trial();data["rows"][0].update(content='{"other":7}',task_success=False)
    report=summarize(data)
    arm=next(a for a in report["arms"] if a["method"]=="bm25_windows" and a["budget"]==20)
    assert arm["strict_json_successes"]==1 and arm["top_level_key_errors"]==1 and arm["parse_errors"]==0

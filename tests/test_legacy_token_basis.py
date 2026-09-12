"""Estimator metadata must describe the arithmetic actually used."""
import json
import pytest
from npk.planner import ContextExecutionPlanner
from npk.runtime import NeuralPackClient
from npk.telemetry import analyze_traces


def test_planner_names_the_actual_token_estimator():
    _, plan = ContextExecutionPlanner().plan_and_optimize([{'role':'user','content':'X'*38}])
    assert plan.metadata['original_tokens'] == 10
    assert plan.metadata['token_basis'] == 'planner_chars_div3_8_estimate'


@pytest.mark.parametrize('mode',['optimized','shadow'])
def test_client_and_trace_estimator_identity_agree(tmp_path, mode):
    trace = tmp_path/'trace.jsonl'
    client = NeuralPackClient(provider='mock',default_model='unpriced',mode=mode,trace_path=str(trace))
    client.chat_completion([{'role':'user','content':'X'*38}])
    row = json.loads(trace.read_text())
    assert row['original_tokens'] == 10
    assert row['token_basis'] == 'planner_chars_div3_8_estimate'
    assert analyze_traces(str(trace))['total_tokens_avoided'] == 0


def test_old_mislabeled_estimator_is_rejected(tmp_path):
    trace = tmp_path/'trace.jsonl'
    client = NeuralPackClient(provider='mock',default_model='unpriced',trace_path=str(trace))
    client.chat_completion([{'role':'user','content':'X'*38}])
    row = json.loads(trace.read_text()); row['token_basis'] = 'planner_chars_div4_estimate'
    trace.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError):analyze_traces(str(trace))

"""Even a correctly graded answer must remain bound to every frozen observation."""
from copy import deepcopy
import pytest
from benchmarks.modern_seed_report import audit_observations
from benchmarks.repository_eval import grade_answer


def trial():
    observations = [{'task': 'one', 'method': method, 'budget': 100, 'request_sha256': 'same', 'status': 'SELECTED'}
                    for method in ('bm25', 'challenger')]
    plan = {'dataset': {'tasks': [{'id': 'one', 'answer': {'a': 1}}]}, 'observations': observations}
    result = {'transport_success': True, 'content': '{"a": 0}', 'usage': {'prompt_tokens': 99},
              'request_sha256': 'same', 'evidence_mode': 'LIVE', 'api_attempts_this_run': 1}
    ledger = {'same': {'state': 'DONE', 'result': result}}
    rows = [{**obs, **deepcopy(result), **grade_answer(result['content'], {'a': 1})} for obs in observations]
    rows[1].update(evidence_mode='REPLAY', api_attempts_this_run=0)
    return plan, rows, ledger


def test_complete_rows_and_replayed_observations_are_accepted():
    assert audit_observations(*trial()) == 2


@pytest.mark.parametrize('attack', ['drop', 'duplicate', 'method', 'budget', 'usage', 'answer'])
def test_report_rejects_observation_or_answer_forgery(attack):
    plan, rows, ledger = trial()
    if attack == 'drop': rows.pop()
    elif attack == 'duplicate': rows[1] = deepcopy(rows[0])
    elif attack == 'method': rows[0]['method'] = 'champion'
    elif attack == 'budget': rows[0]['budget'] = 1000
    elif attack == 'usage': rows[0]['usage']['prompt_tokens'] = 1
    elif attack == 'answer':
        rows[0]['content'] = '{"a": 1}'
        rows[0].update(grade_answer(rows[0]['content'], {'a': 1}))
    rejected = False
    try:
        audit_observations(plan, rows, ledger)
    except (AssertionError, ValueError):
        rejected = True
    assert rejected, f'report accepted {attack}'

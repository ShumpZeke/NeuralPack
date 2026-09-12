"""Target ablations must hold their question, evidence and input cap fixed."""
from copy import deepcopy
import pytest
from benchmarks.target_controls_report import compare


def example():
    return {'task':'synthetic-case','question':'What happened?','budget':100,
            'context_sha256':'synthetic-digest','transport_success':True,'task_success':False}


def rejected(call):
    try:call()
    except ValueError:return True
    return False


@pytest.mark.parametrize('field,value', [('question','Changed question'),('budget',200),('context_sha256','changed-source')])
def test_changed_inputs_cannot_be_counted_as_target_configuration_gains(field,value):
    base=example();changed={**base,field:value,'task_success':True}
    assert rejected(lambda:compare([base],[changed],identical_context=True))


def test_missing_answers_cannot_be_reported_as_losses_or_gains():
    base=example();missing={**base,'transport_success':False,'task_success':None}
    assert compare([base],[missing],identical_context=True)=={'wins':[],'losses':[],'ties':[],'missing':['synthetic-case']}


@pytest.mark.parametrize('candidate', [[],[example(),example()]])
def test_duplicate_or_unmatched_controls_fail(candidate):
    with pytest.raises(ValueError):compare([example()],deepcopy(candidate),identical_context=True)

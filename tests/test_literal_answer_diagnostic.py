"""Format diagnostics cannot execute, repair or silently overwrite answers."""
import pytest
from benchmarks.literal_answer_diagnostic import inspect_values
from benchmarks.repository_eval import grade_answer


def test_correct_python_values_do_not_change_strict_json_failure():
    text="{'count': 2, 'expired': True}";expected={'count':2,'expired':True}
    assert inspect_values(text,expected)=={'form':'Python literal','values_match':True}
    assert grade_answer(text,expected)['task_success'] is False
    assert inspect_values("{'count': True, 'expired': True}",expected)['values_match'] is False


@pytest.mark.parametrize('text',[
    "{'count': 1, 'count': 2}",
    "{'count': __import__('os').system('arbitrary-command')}",
    "{'count': 2}; print('extra')",
    "{'count': 2, 'extra': null}",
    "{'count': 1e999}",
    "{'count': (2,)}",
])
def test_ambiguous_or_executable_output_is_unresolved(text):
    assert inspect_values(text,{'count':2})=={'form':'unresolved','values_match':None}

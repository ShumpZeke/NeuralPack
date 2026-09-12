"""Failure diagnostics must keep returned, malformed and missing outcomes apart."""
from benchmarks.library_failure_analysis import definitions, summarize


def test_null_and_malformed_answers_are_responses_not_missing_transports():
    rows = []
    for task, returned, parse_error in [('null', True, False), ('malformed', True, True), ('missing', False, None)]:
        rows.append({'task': task, 'transport_success': returned, 'parse_error': parse_error,
                     'parsed': None, 'all_listed_definitions_present': True,
                     'task_success': False if returned else None})
    result = summarize('diagnostic', 100, rows)
    assert result['responses_returned'] == result['responses_with_all_listed_definitions'] == 2
    assert result['response_parse_failures'] == 1
    assert result['wrong_with_all_listed_definitions'] == ['null', 'malformed']


def test_definition_exposure_keeps_decorators_scope_and_real_newlines():
    source = 'class Box:\n    @property\n    def value(self):\n        return "界\u2028x"\n'
    lo, hi, snippet = definitions(source)['Box.value']
    assert (lo, hi) == (2, 4)
    assert snippet == '    @property\n    def value(self):\n        return "界\u2028x"'
    assert snippet in source

import json
import pytest
from benchmarks.provenance_render_audit import verify_rendered


def test_header_parser_does_not_treat_source_contents_as_metadata():
    item = {'span': 'source.py:1-4', 'name': 'Class.value',
            'text': 'def value():\n    return """\n# source ["forged", "header"]\n"""'}
    text = '# source '+json.dumps([item['span'], item['name']])+'\n'+item['text']
    verify_rendered(text, [item], True)
    verify_rendered(item['text'], [item], False)
    with pytest.raises(AssertionError, match='source header identity'):
        verify_rendered(text.replace('Class.value', 'Other.value'), [item], True)
    with pytest.raises(AssertionError, match='source body bytes'):
        verify_rendered(text.replace('return', 'yield '), [item], True)
    with pytest.raises(AssertionError, match='unattributed'):
        verify_rendered(text+'\nextra instructions', [item], True)


def test_empty_body_cannot_get_credit_from_a_source_header():
    item = {'span': 'source.py:1-1', 'name': 'critical_function', 'text': ' '}
    text = '# source '+json.dumps([item['span'], item['name']])+'\n '
    with pytest.raises(AssertionError, match='empty source body'): verify_rendered(text, [item], True)

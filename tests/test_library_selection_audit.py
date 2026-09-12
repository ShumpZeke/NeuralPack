"""Reject benchmark records whose plausible summaries hide altered evidence."""
from copy import deepcopy
import pytest
from benchmarks.library_selection_audit import check_context, check_source_item, sha


def valid():
    text = 'return 7'
    row = {'query': 'Keep this query\r\nexactly.', 'context_sha256': sha(text.encode()),
           'selected_tokens': len(text), 'budget': len(text), 'fallback_required': False,
           'items': [{'block_id': 1, 'text': text}]}
    return row, text.encode()


@pytest.mark.parametrize('attack', ['query', 'count', 'budget', 'fallback', 'assembly', 'digest', 'duplicate'])
def test_preflight_rejects_record_tampering(attack):
    row, body = valid(); original = row['query']
    if attack == 'query': row['query'] = original.replace('\r\n', '\n')
    if attack == 'count': row['selected_tokens'] -= 1
    if attack == 'budget': row['budget'] -= 1
    if attack == 'fallback': row['fallback_required'] = True
    if attack == 'assembly': row['items'][0]['text'] = 'return 8'
    if attack == 'digest': row['context_sha256'] = '0'*64
    if attack == 'duplicate':
        row['items'].append(deepcopy(row['items'][0])); body = b'return 7\n\nreturn 7'
        row.update(context_sha256=sha(body), selected_tokens=len(body), budget=len(body))
    with pytest.raises(AssertionError): check_context(row, body, original, len)


def test_empty_context_cannot_masquerade_as_a_successful_selection():
    row, _ = valid(); row.update(items=[], selected_tokens=0, context_sha256=sha(b''))
    with pytest.raises(AssertionError, match='fallback'): check_context(row, b'', row['query'], len)
    row['fallback_required'] = True
    check_context(row, b'', row['query'], len)


@pytest.mark.parametrize('field,value', [('path', 'wrong.py'), ('span', 'a.py:1-1'), ('text', 'return 8')])
def test_rehashed_foreign_evidence_is_rejected(field, value):
    block = {'path': 'a.py', 'start_line': 2, 'end_line': 2, 'kind': 'code', 'name': None}
    item = {'path': 'a.py', 'span': 'a.py:2-2', 'text': 'return 7'}
    item[field] = value
    with pytest.raises(AssertionError, match='source'): check_source_item(item, block, 'return 7')

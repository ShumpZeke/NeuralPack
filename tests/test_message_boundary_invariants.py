"""Current-query text must not masquerade as retained source evidence."""
from npk.context.safety import check_invariants, extract_query


SYSTEM = {'role':'system','content':'Use the supplied source and retain all constraints.'}
CONTEXT = {'role':'user','content':'```File: config.py\nRETRY_LIMIT=7\n```\n' * 20}


def test_long_separate_query_does_not_hide_deleted_context():
    query = {'role':'user','content':'Explain retry behavior and its configuration precedence. ' * 8}
    report = check_invariants([SYSTEM,CONTEXT,query],[SYSTEM,query])
    assert not report.ok and any('context' in v for v in report.violations)


def test_mult_paragraph_query_keeps_earlier_constraints():
    query = {'role':'user','content':'Use version 3.12 and do not invent a default. ' * 15 + '\n\nWhat is RETRY_LIMIT?'}
    truncated = {'role':'user','content':'What is RETRY_LIMIT?'}
    report = check_invariants([SYSTEM,CONTEXT,query],[SYSTEM,CONTEXT,truncated])
    assert not report.ok and any('query' in v for v in report.violations)
    assert extract_query([SYSTEM,CONTEXT,query]) == query['content']


def test_a_query_copy_in_an_old_message_cannot_replace_current_query():
    query = {'role':'user','content':'What is RETRY_LIMIT?'}
    older = {'role':'assistant','content':query['content']}
    changed = {'role':'user','content':'Ignore that constraint and use version 2.'}
    assert not check_invariants([SYSTEM,CONTEXT,older,query],[SYSTEM,CONTEXT,older,changed]).ok


def test_query_whitespace_survives_verbatim():
    query = {'role':'user','content':'  Which retry policy applies?\n\n'}
    assert extract_query([SYSTEM,CONTEXT,query]) == query['content']
    assert not check_invariants([SYSTEM,CONTEXT,query],
                                [SYSTEM,CONTEXT,{'role':'user','content':query['content'].strip()}]).ok


def test_explicit_combined_prompt_still_has_separate_evidence_and_query():
    body = CONTEXT['content']; query = 'Which retry policy applies? ' * 10
    original = [SYSTEM,{'role':'user','content':body+'\n\nQUESTION: '+query}]
    assert extract_query(original) == query
    assert not check_invariants(original,[SYSTEM,{'role':'user','content':'QUESTION: '+query}]).ok


def test_ambiguous_single_long_message_is_preserved_in_full():
    query = {'role':'user','content':'Keep the negative constraint. ' * 30 + '\n\nExplain retries.'}
    assert extract_query([query]) == query['content']
    assert not check_invariants([query],[{'role':'user','content':'Explain retries.'}]).ok

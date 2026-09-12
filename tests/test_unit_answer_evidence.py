"""The live-plan gate must bind exact source, span labels and token accounting."""
from copy import deepcopy
import hashlib
import pytest
from benchmarks.evidence_diagnostics import Piece,render
from benchmarks.unit_answer_plan import reconstruct,tokens


def fixture():
    source={'rules.rst':['Retry ordinary work.','Never retry payment.']}
    piece=Piece('rules.rst',1,2,'\n'.join(source['rules.rst']));context=render([piece],True)
    row={'pieces':[{'path':piece.path,'start':1,'end':2,'span':piece.span}],
         'context_sha256':hashlib.sha256(context.encode()).hexdigest(),'selected_tokens':tokens(context),'budget':100,'status':'selected'}
    return row,source,context


@pytest.mark.parametrize('change',['source','span','tokens'])
def test_live_gate_rejects_changed_evidence(change):
    row,source,context=fixture();assert reconstruct(row,source)[1]==context
    if change=='source':source['rules.rst'][1]='Retry payment.'
    elif change=='span':row['pieces'][0]['span']='rules.rst:1-1'
    else:row['selected_tokens']-=1
    try:reconstruct(row,source)
    except ValueError:pass
    else:assert False,'Changed evidence reached the live request plan'


def test_empty_context_cannot_claim_selection_success():
    row={'pieces':[],'context_sha256':hashlib.sha256(b'').hexdigest(),'selected_tokens':0,'budget':100,'status':'selected'}
    with pytest.raises(ValueError):reconstruct(row,{})
    row['status']='fallback_required';assert reconstruct(row,{})==([],'')

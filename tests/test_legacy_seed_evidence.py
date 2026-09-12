"""LOCAL diagnostic tampering checks, no encoder or answer model needed."""
from copy import deepcopy
import hashlib
import pytest
from benchmarks.legacy_seed_audit import audit


def evidence():
    inputs = {'tasks':[{'id':'synthetic','cohort':'fixture','required':[{'path':'a.py','span':[1,1]}]}],
              'budgets':[8],'blocks':[{'path':'a.py','start':1,'end':1,'text':'retry=7'}]}
    rows = [{'arm':arm,'mode':mode,'task':'synthetic','budget':8,'selected_indices':[0],
             'selected_tokens':1,'available_tokens':1,'corpus_tokens':1,'reported_tokens':1,'seed_failed':False,
             'within_budget':True,'context_sha256':hashlib.sha256(b'retry=7').hexdigest(),
             'required_span_fraction':1.0,'all_required_spans':True,'eligible_required_span_fraction':1.0,'cohort':'fixture'}
            for arm in ('before','after') for mode in ('default','lexical','embedding')]
    return inputs,rows


def test_complete_local_grid_is_reconstructed():
    assert audit(*evidence()) == 6


@pytest.mark.parametrize('attack',['drop','duplicate','text','indices','tokens','coverage','empty'])
def test_local_selection_report_rejects_tampering(attack):
    inputs,rows = deepcopy(evidence())
    if attack=='drop':rows.pop()
    elif attack=='duplicate':rows.append(deepcopy(rows[0]))
    elif attack=='text':inputs['blocks'][0]['text']='forged'
    elif attack=='indices':rows[0]['selected_indices']=[99]
    elif attack=='tokens':rows[0]['selected_tokens']=0
    elif attack=='coverage':rows[0]['required_span_fraction']=0.5
    elif attack=='empty':rows[0]['seed_failed']=True
    rejected = False
    try: audit(inputs,rows)
    except ValueError: rejected = True
    assert rejected, 'tampered LOCAL evidence was accepted'

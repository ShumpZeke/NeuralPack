"""Corpus additions must be judged on paired completed questions, including harms."""
from copy import deepcopy
import pytest
from benchmarks.modern_seed_report import corpus_comparisons


def trial():
    rows=[]
    for task,left,right in [('win',False,True),('loss',True,False),('tie',True,True),('missing',None,True)]:
        for corpus,success in [('original',left),('manuals',right)]:
            rows.append({'corpus':corpus,'cohort':'known','method':'bm25','budget':100,'task':task,
                         'transport_success':success is not None,'task_success':success,
                         'request_sha256':task if task=='tie' else task+corpus})
    return rows


def test_paired_corpus_results_keep_losses_missing_and_shared_requests():
    result=corpus_comparisons(trial(),'original')[0]
    assert result['wins']==['win'] and result['losses']==['loss']
    assert result['ties']==['tie'] and result['missing']==['missing']
    assert result['identical_requests']==['tie']


@pytest.mark.parametrize('attack',['duplicate','drop','method','budget','baseline'])
def test_incompatible_corpus_comparisons_cannot_pass(attack):
    rows=trial();baseline='original'
    if attack=='duplicate':rows.append(deepcopy(rows[0]))
    elif attack=='drop':rows.pop()
    elif attack=='method':rows[0]['method']='different'
    elif attack=='budget':rows[0]['budget']=200
    else:baseline='absent'
    with pytest.raises(ValueError):corpus_comparisons(rows,baseline)

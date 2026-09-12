"""Diagnostic pair counts must not turn unavailable answers into a win."""
from benchmarks.diagnostic_report import pairs


def test_missing_pair_and_a_different_budget_cannot_inflate_rendering_wins():
    rows=[]
    for task,left,right in [('one',True,False),('two',False,True),('three',True,None)]:
        for method,value in [('labeled',left),('plain',right)]:
            rows.append({'task':task,'method':method,'budget':20,'task_success':value,
                         'transport_success':value is not None})
    rows.append({'task':'two','method':'labeled','budget':80,'task_success':True,'transport_success':True})
    result=pairs(rows,'labeled','plain',20)
    assert result['wins']==['one'] and result['losses']==['two']
    assert result['completed_pairs']==2 and result['missing']==['three']
    assert result['planned_pairs']==3 and not result['ties']

"""A namespace mismatch or forged provenance cannot become a retrieval score."""
from copy import deepcopy
import hashlib
import pytest
from benchmarks.identifier_report import canonical_tasks,regrade


@pytest.fixture
def inputs(tmp_path):
    source=tmp_path/'source';path=source/'src/pkg/a.py';path.parent.mkdir(parents=True)
    text='def target():\n    return 7';path.write_text(text,encoding='utf-8')
    manifest=[{'path':'src/pkg/a.py','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]
    task={'id':'one','required':[{'path':'a.py','symbol':'target','span':[1,2]}]}
    row={'task':'one','method':'bm25','budget':100,'selected_tokens':len(text)//4,'context':text,
         'context_sha256':hashlib.sha256(text.encode()).hexdigest(),
         'evidence':[{'path':'src/pkg/a.py','span':'src/pkg/a.py:1-2','block_id':1}],
         'all_required_spans':False,'required_span_fraction':0}
    report={'status':'COMPLETE','tasks':[task],'source_manifest':manifest,'methods':['bm25'],'budgets':[100],
            'rows':[dict(deepcopy(row),policy=policy) for policy in ('windows','members')]}
    return source,report


def test_explicit_namespace_regrades_saved_selections_without_changing_them(inputs):
    source,report=inputs;before=deepcopy(report)
    result=regrade(report,source,'src/pkg/')
    assert report==before
    assert all(r['all_required_spans'] for r in result['rows'])
    assert result['coverage_correction']['changed_rows']==2
    assert [r['context'] for r in result['rows']]==[r['context'] for r in report['rows']]


@pytest.mark.parametrize('problem',['missing_namespace','wrong_span','missing_row','duplicate_row','forged_context','false_tokens','escaped_source'])
def test_invalid_grounding_or_provenance_is_rejected(inputs,problem):
    source,report=inputs
    if problem=='missing_namespace':report['tasks'][0]['required'][0]['path']='not_here.py'
    elif problem=='wrong_span':report['tasks'][0]['required'][0]['span']=[1,1]
    elif problem=='missing_row':report['rows'].pop()
    elif problem=='duplicate_row':report['rows'].append(deepcopy(report['rows'][0]))
    elif problem=='forged_context':
        row=report['rows'][0];row['context']='forged source'
        row['context_sha256']=hashlib.sha256(row['context'].encode()).hexdigest()
    elif problem=='false_tokens':report['rows'][0]['selected_tokens']=1
    else:report['source_manifest'][0]['path']='../../outside.py'
    with pytest.raises(ValueError):regrade(report,source,'src/pkg/')

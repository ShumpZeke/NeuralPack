"""The evidence audit must reject invented wins and misattributed snippets."""
import pytest
from benchmarks.seed_metadata_report import check_row,check_source_coverage,sha


def example():
    text='return 7';body=text.encode()
    block={'path':'lib/a.py','span':'lib/a.py:1-1','text':text,'kind':'function','name':'get'}
    task={'task_id':'a','query':'`get`','path':'lib/a.py','span':'lib/a.py:1-1','needles':['return 7']}
    item={**block,'block_id':1,'tokens':len(text),'channels':['lexical']}
    row={'query':task['query'],'budget':20,'arm':'literal','context_sha256':sha(body),
         'selected_tokens':len(text),'fallback':False,'risk_band':'uncalibrated:high',
         'seed_calls':[{'limit':160,'ids':[1]}],'items':[item],
         'hits':{'a':True},'candidate_pool_hits':{'a':True}}
    return row,body,{1:block},[task]


def test_audit_accepts_literal_provenance():
    row,body,blocks,tasks=example()
    assert check_row(row,body,blocks,tasks,len)==1


@pytest.mark.parametrize('mutation',['count','budget','source','pool','hit','fallback','duplicate','seed','uncalibrated'])
def test_audit_rejects_corrupted_or_invented_evidence(mutation):
    row,body,blocks,tasks=example()
    if mutation=='count':row['selected_tokens']-=1
    if mutation=='budget':row['budget']=2
    if mutation=='source':row['items'][0]['span']='lib/other.py:1-1'
    if mutation=='pool':row['candidate_pool_hits']['a']=False
    if mutation=='hit':row['hits']['a']=False
    if mutation=='fallback':row['fallback']=True
    if mutation=='duplicate':row['seed_calls'][0]['ids']=[1,1]
    if mutation=='seed':row['seed_calls'][0]['ids']=[]
    if mutation=='uncalibrated':row['risk_band']='95% safe'
    with pytest.raises(AssertionError):check_row(row,body,blocks,tasks,len)


def test_empty_context_cannot_receive_a_retention_win():
    row,body,blocks,tasks=example()
    row.update(items=[],context_sha256=sha(b''),selected_tokens=0,fallback=True)
    with pytest.raises(AssertionError,match='selected hit'):check_row(row,b'',blocks,tasks,len)
    row['hits']['a']=False
    assert check_row(row,b'',blocks,tasks,len)==0


def test_compiler_cannot_claim_available_source_that_has_no_selectable_block():
    source={'a.py':'import config\n\nreturn config.value'}
    blocks={1:{'path':'a.py','span':'a.py:1-1'}}
    with pytest.raises(AssertionError,match='absent'):check_source_coverage(blocks,source)
    blocks[2]={'path':'a.py','span':'a.py:3-3'}
    assert check_source_coverage(blocks,source)['nonblank_lines']==2

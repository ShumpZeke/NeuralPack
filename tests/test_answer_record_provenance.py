"""Synthetic record contracts: no model or network is used by these tests."""
from copy import deepcopy
import json
import pytest
from benchmarks.answer_records import counts,import_replays,sha,validate_origin,validate_response
from benchmarks.prospective_eval import request_key,write_json


def rejects_value_error(call):
    try:call()
    except ValueError:return True
    return False


def parent_trial(root,success=True):
    parent=root/'parent';parent.mkdir();(parent/'responses').mkdir()
    child=root/'child';child.mkdir();(child/'contexts').mkdir()
    context='Synthetic example source.';question='What is the example value?'
    digest=sha(context.encode());(child/'contexts'/(digest+'.txt')).write_text(context)
    settings={'model':'synthetic/model','system_prompt':'JSON only','max_output_tokens':32,'temperature':0}
    key=request_key(settings,question,context)
    plan={'settings':settings,'requests':{key:{'question':question,'context_sha256':digest}}}
    result={'evidence_mode':'LIVE','api_attempts_this_run':1,'request_sha256':key,
            'question':question,'context_sha256':digest,'transport_success':success,'content':None}
    if success:
        usage={'prompt_tokens':20,'completion_tokens':5}
        result.update(content='{"example":1}',usage=usage,raw_response={
            'choices':[{'message':{'content':'{"example":1}'}}],'usage':usage})
    else:result['http_status']=503
    write_json(parent/'plan.json',plan);(parent/'plan.sha256').write_text(sha((parent/'plan.json').read_bytes()))
    write_json(parent/'responses'/(key+'.json'),result)
    write_json(parent/'ledger.json',{key:{'state':'DONE','result':result}})
    return parent,child,plan,key


@pytest.mark.parametrize('success',[True,False])
def test_exact_parent_attempts_are_reused_without_new_api_calls(tmp_path,monkeypatch,success):
    parent,child,plan,key=parent_trial(tmp_path,success)
    def denied(*a,**kw):raise AssertionError('Replay used network')
    monkeypatch.setattr('urllib.request.urlopen',denied)
    summary=import_replays(parent,child,plan)
    ledger=json.loads((child/'ledger.json').read_text());record=ledger[key]['result']
    validate_origin(child,record);validate_response(record)
    assert summary['replayed_records']==1 and summary['pending_new_requests']==0
    assert counts(ledger)['attempts']==0 and counts(ledger)['replayed_records']==1
    assert record['transport_success']==success
    assert record['evidence_mode']=='REPLAY' and record['api_attempts_this_run']==0


@pytest.mark.parametrize('attack',['answer','usage','origin','plan','context'])
def test_replay_tampering_is_detected(tmp_path,attack):
    parent,child,plan,key=parent_trial(tmp_path);import_replays(parent,child,plan)
    result=json.loads((child/'ledger.json').read_text())[key]['result']
    if attack=='answer':result['content']='{"example":2}'
    elif attack=='usage':result['usage']['prompt_tokens']=1
    elif attack=='origin':result['replay_origin']['record_sha256']='../'+'a'*61
    elif attack=='plan':
        path=child/'replay-origins'/(result['replay_origin']['plan_sha256']+'.json');path.write_text('{}')
    else:next((child/'contexts').glob('*.txt')).write_text('Changed source')
    assert rejects_value_error(lambda:validate_origin(child,result))


@pytest.mark.parametrize('attack',['pending','settings','ledger','parent_hash'])
def test_replay_import_rejects_uncertain_or_mismatched_parent(tmp_path,attack):
    parent,child,plan,key=parent_trial(tmp_path)
    ledger=json.loads((parent/'ledger.json').read_text())
    if attack=='pending':ledger[key]['state']='STARTED'
    elif attack=='settings':plan=deepcopy(plan);plan['settings']['temperature']=1
    elif attack=='ledger':ledger[key]['result']['content']='{"example":2}'
    else:(parent/'plan.sha256').write_text('0'*64)
    write_json(parent/'ledger.json',ledger)
    with pytest.raises(ValueError):import_replays(parent,child,plan)


@pytest.mark.parametrize('mode,calls',[('LIVE',0),('REPLAY',1),('LIVE',True),('unknown',0)])
def test_call_accounting_rejects_mode_disagreement(mode,calls):
    ledger={'example':{'state':'DONE','result':{'evidence_mode':mode,'api_attempts_this_run':calls,'transport_success':True}}}
    with pytest.raises(ValueError):counts(ledger)


@pytest.mark.parametrize('attack',['negative','boolean','missing','changed_summary'])
def test_raw_provider_usage_is_the_token_count_authority(tmp_path,attack):
    parent,child,plan,key=parent_trial(tmp_path)
    result=json.loads((parent/'responses'/(key+'.json')).read_text())
    if attack=='negative':result['raw_response']['usage']['prompt_tokens']=-1
    elif attack=='boolean':result['raw_response']['usage']['completion_tokens']=True
    elif attack=='missing':del result['raw_response']['usage']['completion_tokens']
    else:result['usage']['prompt_tokens']=1
    assert rejects_value_error(lambda:validate_response(result))


@pytest.mark.parametrize('attack', ['float_count', 'boolean_count', 'nested_boolean'])
def test_reported_usage_cannot_coerce_raw_json_types(tmp_path, attack):
    parent, _, _, key = parent_trial(tmp_path)
    result = json.loads((parent/'responses'/(key+'.json')).read_text())
    if attack == 'float_count': result['usage']['prompt_tokens'] = 20.0
    elif attack == 'boolean_count':
        result['raw_response']['usage']['completion_tokens'] = 1
        result['usage']['completion_tokens'] = True
    else:
        result['raw_response']['usage']['details'] = {'cached_tokens': 0}
        result['usage']['details'] = {'cached_tokens': False}
    assert rejects_value_error(lambda: validate_response(result)), 'Typed usage substitution accepted'


@pytest.mark.parametrize('attack', ['float_usage', 'boolean_outcome', 'boolean_attempts'])
def test_replay_identity_preserves_json_types(tmp_path, attack):
    parent, child, plan, key = parent_trial(tmp_path); import_replays(parent, child, plan)
    result = json.loads((child/'ledger.json').read_text())[key]['result']
    if attack == 'float_usage': result['usage']['prompt_tokens'] = 20.0
    elif attack == 'boolean_outcome': result['transport_success'] = 1
    else: result['api_attempts_this_run'] = False
    assert rejects_value_error(lambda: validate_origin(child, result)), 'Typed replay substitution accepted'


def test_replay_import_rejects_type_change_between_parent_ledger_and_response(tmp_path):
    parent, child, plan, key = parent_trial(tmp_path)
    ledger = json.loads((parent/'ledger.json').read_text())
    ledger[key]['result']['usage']['prompt_tokens'] = 20.0
    write_json(parent/'ledger.json', ledger)
    assert rejects_value_error(lambda: import_replays(parent, child, plan)), 'Typed parent ledger mismatch accepted'

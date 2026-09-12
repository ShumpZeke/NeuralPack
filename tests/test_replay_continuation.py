"""Reusing already-replayed answers keeps original evidence, including failures."""
import json
from copy import deepcopy
import pytest
from benchmarks.answer_records import counts,import_replays,validate_origin,sha
from benchmarks.prospective_eval import write_json
from benchmarks.replay_continuation import import_completed
from test_answer_record_provenance import parent_trial,rejects_value_error


def generations(tmp_path,success):
    parent,child,plan,key=parent_trial(tmp_path,success);import_replays(parent,child,plan)
    write_json(child/'plan.json',plan);(child/'plan.sha256').write_text(sha((child/'plan.json').read_bytes()))
    later=tmp_path/'later';later.mkdir();(later/'contexts').mkdir()
    for p in (child/'contexts').iterdir():(later/'contexts'/p.name).write_bytes(p.read_bytes())
    return parent,child,later,plan,key


@pytest.mark.parametrize('success',[True,False])
def test_inherited_replay_preserves_live_origin_and_zero_new_calls(tmp_path,monkeypatch,success):
    parent,child,later,plan,key=generations(tmp_path,success)
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Replay used network')))
    before=json.loads((child/'ledger.json').read_text())[key]['result']
    summary=import_completed(child,later,plan);ledger=json.loads((later/'ledger.json').read_text())
    assert ledger[key]['result']==before and summary['inherited_replays']==1 and summary['pending_new_requests']==0
    assert counts(ledger)['attempts']==0 and counts(ledger)['replayed_answers']==int(success)
    validate_origin(later,ledger[key]['result'])
    original=(parent/'responses'/(key+'.json')).read_bytes()
    assert (later/'replay-origins'/(sha(original)+'.json')).read_bytes()==original
    intermediate=(child/'responses'/(key+'.json')).read_bytes()
    assert (later/'replay-lineage'/(sha(intermediate)+'.json')).read_bytes()==intermediate


@pytest.mark.parametrize('attack',['ancestor_answer','ancestor_plan','intermediate_response','destination_context','pending_parent','settings'])
def test_inherited_tampering_is_rejected_before_a_new_ledger(tmp_path,attack):
    parent,child,later,plan,key=generations(tmp_path,True)
    record=json.loads((child/'ledger.json').read_text())[key]['result'];origin=record['replay_origin']
    if attack=='ancestor_answer':(child/'replay-origins'/(origin['record_sha256']+'.json')).write_text('{}')
    elif attack=='ancestor_plan':(child/'replay-origins'/(origin['plan_sha256']+'.json')).write_text('{}')
    elif attack=='intermediate_response':(child/'responses'/(key+'.json')).write_text('{}')
    elif attack=='destination_context':next((later/'contexts').iterdir()).write_text('different')
    elif attack=='pending_parent':
        ledger=json.loads((child/'ledger.json').read_text());ledger[key]['state']='STARTED';write_json(child/'ledger.json',ledger)
    else:plan=deepcopy(plan);plan['settings']['temperature']=1
    assert rejects_value_error(lambda:import_completed(child,later,plan))
    assert not (later/'ledger.json').exists(), 'Invalid inherited evidence was committed as completed'


def test_direct_live_import_also_preserves_identity(tmp_path):
    parent,child,plan,key=parent_trial(tmp_path)
    summary=import_completed(parent,child,plan);result=json.loads((child/'ledger.json').read_text())[key]['result']
    assert summary['inherited_replays']==0 and summary['replayed_records']==1
    validate_origin(child,result)

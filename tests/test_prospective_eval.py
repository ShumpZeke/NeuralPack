"""Freeze, replay, interruption, and request-accounting checks use no network."""
import json
from types import SimpleNamespace

import pytest

from benchmarks import prospective_eval as module


@pytest.fixture
def plan(tmp_path):
    settings={"model":"synthetic/model","max_output_tokens":40,"reasoning_effort":None,
              "system_prompt":"Synthetic rules","timeout_seconds":180}
    context="source evidence";question="question"
    context_hash=module.digest(context.encode())
    (tmp_path/"contexts").mkdir()
    (tmp_path/"contexts"/(context_hash+".txt")).write_text(context)
    key=module.request_key(settings,question,context)
    data={"settings":settings,"requests":{key:{"question":question,"context_sha256":context_hash}},
          "dataset":{"tasks":[{"id":"one","answer":{"value":7}}]},
          "observations":[{"task":"one","method":method,"budget":20,"request_sha256":key,"context_sha256":context_hash}
                          for method in ("baseline","candidate")]}
    module.write_json(tmp_path/"plan.json",data)
    (tmp_path/"plan.sha256").write_text(module.digest((tmp_path/"plan.json").read_bytes()))
    return tmp_path,key,context_hash


def args(root,live=True):
    return SimpleNamespace(output=str(root),live=live,workers=2,max_requests=0)


def completed(key):
    return {"request_sha256":key,"evidence_mode":"LIVE","api_attempts_this_run":1,
            "transport_success":True,"content":'{"value":7}'}


def test_template_flags_and_sampling_are_sent_and_change_request_identity(tmp_path,monkeypatch):
    import io
    from benchmarks.repository_eval import live_answer
    calls=[]
    def answer(request,**kwargs):
        calls.append(json.loads(request.data));return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
    monkeypatch.setattr('urllib.request.urlopen',answer)
    monkeypatch.setattr('npk.providers.nvidia._load_env_key',lambda:'synthetic-not-a-credential')
    base={'model':'synthetic/model','system_prompt':'original system','reasoning_effort':None,'max_output_tokens':40}
    for options in ({},{'temperature':1.0,'top_p':0.95,'chat_template_kwargs':{'enable_thinking':False}},
                    {'temperature':1.0,'top_p':0.95,'chat_template_kwargs':{'enable_thinking':True}},
                    {'temperature':1.0,'top_p':0.95,'chat_template_kwargs':{'enable_thinking':True,'low_effort':True}}):
        settings={**base,**options};key=module.request_key(settings,'original query','original source')
        result=live_answer(question='original query',context='original source',cache=tmp_path,live=True,**settings)
        assert result['request_sha256']==key
    assert len(calls)==4 and calls[1]['chat_template_kwargs']=={'enable_thinking':False}
    assert calls[3]['chat_template_kwargs']=={'enable_thinking':True,'low_effort':True}
    assert calls[3]['messages']==calls[0]['messages']
    assert calls[1]['temperature']==1.0 and calls[1]['top_p']==0.95
    assert calls[1]['messages']==calls[0]['messages']


@pytest.mark.parametrize('options',[
    {'temperature':True},{'temperature':float('nan')},{'top_p':0},
    {'chat_template_kwargs':{'enable_thinking':'false'}},{'chat_template_kwargs':{'unknown':False}},
    {'chat_template_kwargs':{'low_effort':1}}, {'chat_template_kwargs':{'low_effort':'true'}},
])
def test_invalid_new_options_cannot_dispatch_a_request(tmp_path,monkeypatch,options):
    from benchmarks.repository_eval import live_answer
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:pytest.fail('invalid configuration reached transport'))
    with pytest.raises(ValueError):live_answer('synthetic/model','q','c',tmp_path,live=True,**options)


def test_one_request_can_supply_two_observations_without_double_billing(plan,monkeypatch):
    root,key,_=plan;calls=[]
    def answer(**kwargs): calls.append(kwargs);return completed(key)
    monkeypatch.setattr(module,"live_answer",answer)
    module.execute(args(root));module.execute(args(root))
    result=json.loads((root/"results.json").read_text())
    assert len(calls)==1
    assert result["answer_attempts_in_ledger"]==1
    assert result["new_answer_attempts_this_execution"]==0
    assert [r["evidence_mode"] for r in result["rows"]]==["LIVE","REPLAY"]
    assert all(r["task_success"] for r in result["rows"])


def test_utf8_plan_survives_a_windows_locale_default(plan, monkeypatch):
    from pathlib import Path
    root, old_key, context_hash = plan
    data = module._read_json(root/'plan.json')
    question = 'Why does 猫.txt become empty?'
    key = module.request_key(data['settings'], question, 'source evidence')
    data['requests'] = {key: {'question': question, 'context_sha256': context_hash}}
    for row in data['observations']: row['request_sha256'] = key
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    (root/'plan.json').write_bytes(raw)
    (root/'plan.sha256').write_text(module.digest(raw), encoding='ascii')
    original = Path.read_text
    def windows_read(path, encoding=None, errors=None):
        return original(path, encoding=encoding or 'cp1252', errors=errors)
    monkeypatch.setattr(Path, 'read_text', windows_read)
    assert module._read_json(root/'plan.json') == data
    dispatched = []
    def answer(**kw):
        dispatched.append(kw['question'])
        return completed(module.request_key(data['settings'], kw['question'], kw['context']))
    monkeypatch.setattr(module, 'live_answer', answer)
    module.execute(args(root))
    assert dispatched == [question]
    assert module._read_json(root/'ledger.json')[key]['state'] == 'DONE'


@pytest.mark.parametrize('interrupt', [False, True])
def test_executor_spaces_dispatch_before_recording_a_new_attempt(plan, monkeypatch, interrupt):
    from benchmarks.request_pacing import RequestPacer
    root, _, context_hash = plan
    data = json.loads((root/'plan.json').read_text()); data['requests'] = {}; data['observations'] = []
    for index in range(3):
        question = f'synthetic question {index}'
        key = module.request_key(data['settings'], question, 'source evidence')
        data['requests'][key] = {'question': question, 'context_sha256': context_hash}
        data['observations'].append({'task': 'one', 'method': str(index), 'budget': 20, 'request_sha256': key})
    module.write_json(root/'plan.json', data)
    (root/'plan.sha256').write_text(module.digest((root/'plan.json').read_bytes()))
    now = [0.0]; starts = []
    def sleep(seconds):
        ledger = json.loads((root/'ledger.json').read_text())
        assert all(r['state'] == 'DONE' for r in ledger.values()), 'spacing created a false uncertain attempt'
        if interrupt: raise KeyboardInterrupt
        now[0] += seconds
    monkeypatch.setattr(module, 'RequestPacer', lambda interval, workers:
                        RequestPacer(interval, workers, clock=lambda: now[0], sleep=sleep))
    def answer(**kw):
        starts.append(now[0]); now[0] += 0.1
        return completed(module.request_key(data['settings'], kw['question'], kw['context']))
    monkeypatch.setattr(module, 'live_answer', answer)
    options = args(root); options.workers = 1; options.min_request_interval = 3
    if interrupt:
        with pytest.raises(KeyboardInterrupt): module.execute(options)
        assert starts == [0]
        assert len(json.loads((root/'ledger.json').read_text())) == 1
    else:
        module.execute(options)
        assert starts == [0, 3, 6]


def test_rate_limit_hint_is_recorded_without_retrying_the_request(tmp_path, monkeypatch):
    import io
    from email.message import Message
    from urllib.error import HTTPError
    from benchmarks.repository_eval import live_answer
    headers = Message(); headers['Retry-After'] = '7'; calls = []
    def limited(*args, **kwargs):
        calls.append(1)
        raise HTTPError('https://example.invalid/synthetic', 429, 'synthetic limit', headers, io.BytesIO(b'synthetic error'))
    monkeypatch.setattr('urllib.request.urlopen', limited)
    monkeypatch.setattr('npk.providers.nvidia._load_env_key', lambda: 'synthetic-not-a-credential')
    result = live_answer('synthetic/model', 'synthetic question', 'synthetic source', tmp_path, live=True)
    assert result['retry_after_seconds'] == 7 and result['http_status'] == 429
    assert not result['transport_success'] and len(calls) == 1


def test_replay_miss_does_not_prevent_a_later_authorized_live_attempt(plan,monkeypatch):
    root,key,_=plan
    monkeypatch.setattr(module,"live_answer",lambda **kw:completed(key) if kw["live"] else {
        "evidence_mode":"REPLAY_MISS","api_attempts_this_run":0,"content":None})
    module.execute(args(root,live=False))
    module.execute(args(root,live=True))
    result=json.loads((root/"results.json").read_text())
    assert result["answer_attempts_in_ledger"]==1 and all(r["task_success"] for r in result["rows"])


def test_unknown_inflight_request_cannot_be_silently_reissued(plan,monkeypatch):
    root,key,_=plan
    module.write_json(root/"ledger.json",{key:{"state":"STARTED"}})
    monkeypatch.setattr(module,"live_answer",lambda **kw:pytest.fail("reissued uncertain request"))
    with pytest.raises(RuntimeError,match="unknown outcome"):
        module.execute(args(root))


def test_cache_recovers_a_completed_but_uncheckpointed_answer(plan,monkeypatch):
    root,key,_=plan
    module.write_json(root/"ledger.json",{key:{"state":"STARTED"}})
    (root/"responses").mkdir();module.write_json(root/"responses"/(key+".json"),completed(key))
    monkeypatch.setattr(module,"live_answer",lambda **kw:pytest.fail("unnecessary request"))
    module.execute(args(root))
    result=json.loads((root/"results.json").read_text())
    assert result["answer_attempts_in_ledger"]==1 and result["new_answer_attempts_this_execution"]==0


def test_changed_context_fails_before_any_request_is_recorded(plan,monkeypatch):
    root,_,context_hash=plan
    (root/"contexts"/(context_hash+".txt")).write_text("tampered")
    monkeypatch.setattr(module,"live_answer",lambda **kw:pytest.fail("request with tampered source"))
    with pytest.raises(RuntimeError,match="context changed"):
        module.execute(args(root))
    assert not (root/"ledger.json").exists()


def test_frozen_identity_matches_the_actual_answer_payload(plan,monkeypatch):
    import io
    from benchmarks.repository_eval import live_answer
    root,key,_=plan
    data=json.loads((root/"plan.json").read_text())
    monkeypatch.setattr("npk.providers.nvidia._load_env_key",lambda:"synthetic-not-a-credential")
    monkeypatch.setattr("urllib.request.urlopen",lambda *a,**k:io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}'))
    result=live_answer(question="question",context="source evidence",cache=root,live=True,**data["settings"])
    assert result["request_sha256"]==key
    original_stamp=result["execution_code_sha256"]
    replay=live_answer(question="question",context="source evidence",cache=root,live=False,
                       execution_code_sha256={"synthetic":"a different reporting revision"},**data["settings"])
    assert replay["execution_code_sha256"]==original_stamp


def test_repeated_transport_failures_pause_without_abandoning_or_resubmitting(plan,monkeypatch):
    root,_,context_hash=plan
    data=json.loads((root/"plan.json").read_text());data["requests"]={};data["observations"]=[]
    for index in range(6):
        question=f"question {index}";key=module.request_key(data["settings"],question,"source evidence")
        data["requests"][key]={"question":question,"context_sha256":context_hash}
        data["observations"].append({"task":"one","method":f"method{index}","budget":20,"request_sha256":key})
    module.write_json(root/"plan.json",data)
    (root/"plan.sha256").write_text(module.digest((root/"plan.json").read_bytes()))
    calls=[]
    def fail(**kw):
        calls.append(kw["question"])
        key=module.request_key(data["settings"],kw["question"],kw["context"])
        return {**completed(key),"transport_success":False,"content":None,"error_type":"TimeoutError"}
    monkeypatch.setattr(module,"live_answer",fail)
    module.execute(args(root))
    assert len(calls)==4
    ledger=json.loads((root/"ledger.json").read_text())
    assert len(ledger)==4 and all(r["state"]=="DONE" for r in ledger.values())
    with pytest.raises(RuntimeError,match="paused after transport"):
        module.execute(args(root))
    assert len(calls)==4
    report_args=args(root,live=False);report_args.report_only=True
    module.execute(report_args)
    report=json.loads((root/"results.json").read_text())
    assert report["answer_attempts_in_ledger"]==4 and report["failure_pauses"]["active"]
    assert sum(r["evidence_mode"]=="PENDING" for r in report["rows"])==2
    resume=args(root);resume.resume_after_failures=True
    module.execute(resume)
    assert len(calls)==6 and len(set(calls))==6


@pytest.mark.parametrize('workers',[1,2])
def test_one_rate_limit_pauses_even_when_its_batch_also_succeeds(plan,monkeypatch,workers):
    root,_,context_hash=plan
    data=json.loads((root/'plan.json').read_text());data['requests']={};data['observations']=[]
    for index in range(5):
        question=f'question {index}';key=module.request_key(data['settings'],question,'source evidence')
        data['requests'][key]={'question':question,'context_sha256':context_hash}
        data['observations'].append({'task':'one','method':str(index),'budget':20,'request_sha256':key})
    module.write_json(root/'plan.json',data);(root/'plan.sha256').write_text(module.digest((root/'plan.json').read_bytes()))
    calls=[]
    def answer(**kw):
        calls.append(kw['question']);key=module.request_key(data['settings'],kw['question'],kw['context'])
        return {**completed(key),'transport_success':False,'content':None,'http_status':429} if kw['question']=='question 0' else completed(key)
    monkeypatch.setattr(module,'live_answer',answer)
    settings=args(root);settings.workers=workers;module.execute(settings)
    assert len(calls)==workers, 'One rate-limit response must prevent the next batch'
    ledger=json.loads((root/'ledger.json').read_text())
    assert len(ledger)==workers and all(r['state']=='DONE' for r in ledger.values())
    assert json.loads((root/'failure-pauses.json').read_text())['active']
    settings.resume_after_failures=True;module.execute(settings)
    assert len(calls)==5 and len(set(calls))==5


def test_answer_followup_preserves_selection_but_cannot_reuse_other_settings_response(plan,tmp_path):
    root,old_key,_=plan
    data=json.loads((root/"plan.json").read_text())
    data["dataset"]["tasks"][0]["question"]="question";data["limitations"]=[]
    module.write_json(root/"plan.json",data)
    (root/"plan.sha256").write_text(module.digest((root/"plan.json").read_bytes()))
    target=tmp_path/"followup"
    module.followup(SimpleNamespace(from_run=str(root),output=str(target),reasoning_effort="none",
                                    max_output_tokens=80,timeout=90))
    revised=json.loads((target/"plan.json").read_text())
    assert revised["dataset"]==data["dataset"]
    assert set(revised["requests"])!={old_key} and len(revised["requests"])==1
    for before,after in zip(data["observations"],revised["observations"]):
        assert {k:v for k,v in before.items() if k!="request_sha256"}=={k:v for k,v in after.items() if k!="request_sha256"}

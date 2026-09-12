"""The live answer evaluator must reject wrong answers and account for headers."""
from types import SimpleNamespace
import pytest

from benchmarks.repository_eval import budgeted_context, grade_answer, live_answer, source_coverage
from npk.pack.compile import estimate_tokens
from benchmarks.repository_report import fence_normalized_answer, summarize


def evidence(path="source.py",start=1,end=3,text="return 7"):
    return SimpleNamespace(path=path,span=f"{path}:{start}-{end}",text=text)


def test_grading_is_exact_and_distinguishes_boolean_numeric_values():
    expected={"eligible":True,"seconds":2.0}
    assert grade_answer('{"seconds":2,"eligible":true}',expected)["task_success"]
    for answer in ('{"eligible":1,"seconds":2}', '{"eligible":true,"seconds":3}',
                   '{"eligible":true,"seconds":2,"extra":0}', '{}',
                   '```json\n{"eligible":true,"seconds":2}\n```'):
        assert not grade_answer(answer,expected)["task_success"]


@pytest.mark.parametrize('answer',[
    '{"value":99,"value":7}',
    '{"nested":{"value":99,"value":7},"value":7}',
    '{"value":99,"\\u0076alue":7}',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
])
def test_ambiguous_keys_and_non_json_constants_cannot_pass_strict_grading(answer):
    expected={'value':7,'nested':{'value':7}} if 'nested' in answer else {'value':7}
    grade=grade_answer(answer,expected)
    assert grade['parse_error'] and not grade['task_success'],'ambiguous or non-JSON answer accepted'


def test_span_coverage_needs_complete_span_in_correct_file():
    required=[{"path":"source.py","span":[1,6]}]
    assert not source_coverage([evidence(end=3)],required)["all_required_spans"]
    assert not source_coverage([evidence(path="wrong.py",end=6)],required)["all_required_spans"]
    assert source_coverage([evidence(end=3),evidence(start=4,end=6)],required)["all_required_spans"]
    assert source_coverage([],[])["required_span_fraction"] is None


def test_rendered_header_budget_can_reject_block_that_raw_text_would_fit():
    block=evidence(path="long_path"*20,text="tiny")
    kept,text=budgeted_context([block],20)
    assert not kept and not text
    kept,text=budgeted_context([block,evidence()],20)
    assert len(kept)==1 and kept[0].path=="source.py"
    assert estimate_tokens(text)<=20


def test_replay_miss_never_sends_a_request(tmp_path,monkeypatch):
    def denied(*args,**kwargs):
        raise AssertionError("replay attempted a network call")
    monkeypatch.setattr("urllib.request.urlopen",denied)
    result=live_answer("synthetic/model","question","source",tmp_path,live=False)
    assert result["evidence_mode"]=="REPLAY_MISS"
    assert result["api_attempts_this_run"]==0


def test_answer_generation_settings_change_cache_identity(tmp_path,monkeypatch):
    import io,json
    requests=[]
    def answer(request,**kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices":[{"message":{"content":"{}"}}]}).encode())
    monkeypatch.setattr("npk.providers.nvidia._load_env_key",lambda:"synthetic-not-a-credential")
    monkeypatch.setattr("urllib.request.urlopen",answer)
    first=live_answer("synthetic/model","q","source",tmp_path,live=True,max_output_tokens=2048,reasoning_effort="none")
    same=live_answer("synthetic/model","q","source",tmp_path,live=True,max_output_tokens=2048,reasoning_effort="none")
    assert same["evidence_mode"]=="REPLAY" and len(requests)==1
    different=live_answer("synthetic/model","q","source",tmp_path,live=True,max_output_tokens=2048,reasoning_effort="high")
    cap=live_answer("synthetic/model","q","source",tmp_path,live=True,max_output_tokens=384,reasoning_effort="none")
    assert len({first["request_sha256"],different["request_sha256"],cap["request_sha256"]})==3
    assert requests[0]["reasoning_effort"]=="none" and requests[0]["max_tokens"]==2048


def test_repository_system_prompt_and_timeout_are_explicit(tmp_path,monkeypatch):
    import io,json
    calls=[]
    def answer(request,**kwargs):
        calls.append((json.loads(request.data),kwargs))
        return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
    monkeypatch.setattr("npk.providers.nvidia._load_env_key",lambda:"synthetic-not-a-credential")
    monkeypatch.setattr("urllib.request.urlopen",answer)
    first=live_answer("synthetic/model","q","source",tmp_path,live=True,system_prompt="Click rules",timeout_seconds=180)
    second=live_answer("synthetic/model","q","source",tmp_path,live=True,system_prompt="Other rules",timeout_seconds=180)
    assert first["request_sha256"]!=second["request_sha256"]
    assert calls[0][0]["messages"][0]=={"role":"system","content":"Click rules"}
    assert calls[0][1]["timeout"]==180


def test_transport_errors_are_recorded_and_never_store_an_echoed_credential(tmp_path,monkeypatch):
    import io,urllib.error
    credential="synthetic-credential-to-hide"
    monkeypatch.setattr("npk.providers.nvidia._load_env_key",lambda:credential)
    def denied(*args,**kwargs):
        raise urllib.error.HTTPError("https://example.invalid",400,"bad",{},io.BytesIO(credential.encode()))
    monkeypatch.setattr("urllib.request.urlopen",denied)
    result=live_answer("synthetic/model","q","source",tmp_path,live=True)
    assert not result["transport_success"] and result["http_status"]==400
    assert credential not in str(result) and result["error_detail"]=="[redacted]"
    def reset(*args,**kwargs): raise ConnectionResetError("synthetic reset")
    monkeypatch.setattr("urllib.request.urlopen",reset)
    result=live_answer("synthetic/model","another question","source",tmp_path,live=True)
    assert not result["transport_success"] and result["error_type"]=="ConnectionResetError"


def test_fence_diagnostic_does_not_cherry_pick_json_from_prose():
    assert fence_normalized_answer('```json\n{"a":1}\n```')=='{"a":1}'
    content='Wrong answer: {"a":2}. Alternative: {"a":1}'
    assert fence_normalized_answer(content)==content
    assert not grade_answer(fence_normalized_answer(content),{"a":1})["task_success"]


def test_report_separates_missing_api_answers_from_wrong_answers():
    row={"task":"test","arm":"bm25_windows","evidence_mode":"REPLAY_MISS"}
    report=summarize({"dataset":{"tasks":[{"id":"test","answer":{}}]},"rows":[row],
                      "generative_optimization_calls":0,"live_api_attempts":0,"summaries":[]})
    arm=report["arms"][0]
    assert arm["completed_answers"]==0 and arm["missing_or_transport_errors"]==1
    assert arm["reported_input_tokens_total"] is None
    assert report["tasks"][0]["fence_normalized_success"]["bm25_windows"] is None


def test_live_counterexample_is_not_rewarded_for_using_plausible_class_names():
    expected={"disabled":"ReadTimeoutError","zero":"MaxRetryError"}
    # Actual member-chunk answer in the first frozen urllib3 NIM run.
    answer='{"disabled":"MaxRetryError","zero":"MaxRetryError"}'
    assert not grade_answer(answer,expected)["task_success"]
    assert grade_answer('{"disabled":"ReadTimeoutError","zero":"MaxRetryError"}',expected)["task_success"]

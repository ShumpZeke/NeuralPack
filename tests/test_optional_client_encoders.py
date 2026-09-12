"""Client encoder opt-in contracts; synthetic ranks are plumbing evidence only."""
import json
import subprocess
import sys

import pytest

from npk.context.embedding import get_backend
from npk.context.info_gain import InformationGainSelector
from npk.context.retrieval import CodeContextRetriever
from npk.planner import ContextExecutionPlanner
from npk.runtime import NeuralPackClient


BLOCKS = [{'name': f'part{i}.py', 'text': text, 'content': text} for i, text in enumerate(
    ['alpha = 1', 'bravo = 2', 'charlie = 3'])]
CONTEXT = '\n\n'.join(f'```File: {b["name"]}\n{b["text"]}\n```' for b in BLOCKS)
MESSAGES = [{'role': 'system', 'content': 'Retain original source and identify missing evidence.'},
            {'role': 'user', 'content': CONTEXT * 2},
            {'role': 'user', 'content': 'zzunique_missing_phrase'}]


def invoke(layer, tmp_path, enabled=None):
    if layer == 'selector':
        opts = {} if enabled is None else {'enable_escalation': enabled}
        return InformationGainSelector(**opts).select(BLOCKS, MESSAGES[-1]['content'], {}, 100)
    if layer == 'retriever':
        opts = {} if enabled is None else {'enable_escalation': enabled}
        return CodeContextRetriever(**opts).retrieve_relevant_context(CONTEXT, MESSAGES[-1]['content'])
    opts = {} if enabled is None else {'use_local_embeddings': enabled}
    if layer == 'planner':
        return ContextExecutionPlanner(**opts).plan_and_optimize(MESSAGES)
    return NeuralPackClient(provider='mock', default_model='unpriced-example',
                            trace_path=str(tmp_path/'trace.jsonl'), **opts).chat_completion(MESSAGES)


@pytest.mark.parametrize('layer', ['selector', 'retriever', 'planner', 'client'])
def test_default_client_does_not_probe_an_encoder(layer, tmp_path, monkeypatch):
    calls = []
    def score(texts, query):
        calls.append((texts, query))
        return None
    monkeypatch.setattr(get_backend(), 'score_blocks', score)
    monkeypatch.setenv('NPK_ENABLE_EMBEDDINGS', '1')
    invoke(layer, tmp_path)
    assert not calls, 'default deterministic path probed a neural encoder'


@pytest.mark.parametrize('layer', ['selector', 'retriever', 'planner', 'client'])
def test_explicit_client_encoder_is_wired_and_isolated(layer, tmp_path, monkeypatch):
    calls = []
    def score(texts, query):
        calls.append((texts, query))
        return [0.9 if 'bravo' in t else 0.1 for t in texts]
    monkeypatch.setattr(get_backend(), 'score_blocks', score)
    invoke(layer, tmp_path, True)
    assert calls and all(query == MESSAGES[-1]['content'] for _, query in calls)
    calls.clear()
    invoke(layer, tmp_path, False)
    assert not calls


def test_explicit_encoder_changes_seeds_and_missing_encoder_preserves_failure(monkeypatch):
    monkeypatch.setattr(get_backend(), 'score_blocks', lambda texts, query: [0.1, 0.9, 0.1])
    selector = InformationGainSelector(enable_escalation=True)
    out = selector.select(BLOCKS, 'zzunique_missing_phrase', {}, 3)
    assert out.kept_indices == [1] and out.stats['escalated']
    monkeypatch.setattr(get_backend(), 'score_blocks', lambda texts, query: None)
    out = selector.select(BLOCKS, 'zzunique_missing_phrase', {}, 3)
    assert not out.kept_indices and out.seed_failed


def test_default_client_in_fresh_process_needs_no_neural_packages(tmp_path):
    script = '''import importlib.abc,json,sys,socket
attempts=[]
class RejectNeural(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','transformers','sentence_transformers'}:
   attempts.append(fullname);raise ImportError('neural import attempted')
sys.meta_path.insert(0,RejectNeural())
def denied(*a,**k): raise AssertionError('network attempted')
socket.socket.connect=denied
from npk.runtime import NeuralPackClient
client=NeuralPackClient(provider='mock',default_model='unpriced',trace_path=sys.argv[1])
messages=json.loads(sys.argv[2]);client.chat_completion(messages)
assert not attempts, 'neural import attempted: '+repr(attempts)
assert not any(n in sys.modules for n in ('torch','transformers','sentence_transformers'))
print('ok')'''
    proc = subprocess.run([sys.executable, '-c', script, str(tmp_path/'trace.jsonl'), json.dumps(MESSAGES)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == 'ok'

"""Reconstruct profiled message bytes and compare every captured dispatch digest.

Reconstructed messages are REPLAY evidence, not retrospectively invented raw
target responses. This command makes no encoder or target-model calls.
"""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from npk.planner import ContextExecutionPlanner
from npk.context.analyzer import estimate_tokens


def main():
    repo=Path(__file__).resolve().parents[1]
    profile=json.loads((repo/'experiments/results/cycle17-client-profile.json').read_text())
    root=repo/'experiments/runs/packs/cycle17-client-profile-v1'
    output=repo/'experiments/results/cycle17-dispatch-reconstruction.json'
    if output.exists():raise ValueError('new reconstruction output required')
    assert profile['candidate_source_sha256']=={p.relative_to(repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo/'npk').rglob('*.py')}
    recorded=[r for run in profile['runs'] for r in run['rows']];rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('reconstruction attempted network')):
        for item in json.loads((root/'inputs.json').read_text()):
            context=(root/item['file']).read_text(encoding='utf-8')
            messages=[{'role':'system','content':'Use supplied source and explicitly identify missing evidence.'},
                      {'role':'user','content':context},
                      {'role':'user','content':'How are inherited defaults overridden by section-specific options?'}]
            actual,_=ContextExecutionPlanner(target_model='unpriced-example').plan_and_optimize(messages,quality_threshold=.95,provider='mock')
            digest=hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest()
            tokens=sum(estimate_tokens(m['content']) for m in actual)
            matching=[r for r in recorded if r['target']==item['target']]
            assert len(matching)==24 and all(r['messages_sha256']==digest and r['selected_tokens']==tokens for r in matching)
            path=root/f'reconstructed-dispatch-{item["target"]}.json'
            path.write_text(json.dumps(actual,indent=2),encoding='utf-8')
            rows.append({'target':item['target'],'captured_dispatches_matched':len(matching),
                         'messages_sha256':digest,'selected_tokens':tokens,
                         'reconstructed_file':str(path.relative_to(repo)),
                         'reconstructed_file_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    output.write_text(json.dumps({'evidence_mode':'REPLAY','processing_mode':'LOCAL','new_api_calls':0,
        'profile_sha256':hashlib.sha256((repo/'experiments/results/cycle17-client-profile.json').read_bytes()).hexdigest(),
        'rows':rows,'limits':['Deterministically reconstructed bytes match recorded SHA-256; source records are not authenticated to a third party',
                             'Not raw answer evidence and not an answer-quality evaluation']},indent=2),encoding='utf-8')
    print({'captured_dispatches_matched':sum(r['captured_dispatches_matched'] for r in rows),'new_api_calls':0})


if __name__=='__main__':main()

"""Declare a different target-answer configuration on unchanged frozen contexts.

This makes zero API calls. The target may reason inside its one answer request;
the compiler/runtime still makes zero generative optimization calls.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random

from benchmarks.prospective_eval import request_key
from benchmarks.repository_eval import answer_payload


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def prepare(a):
    from tokenizers import Tokenizer
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    if a.output.exists(): raise ValueError('Fresh target-profile plan required')
    parent_bytes = (a.parent/'plan.json').read_bytes(); parent = json.loads(parent_bytes)
    assert sha(parent_bytes) == (a.parent/'plan.sha256').read_text().strip()
    diagnostic = read(a.report); assert diagnostic['plan_sha256'] == sha(parent_bytes)
    captured = (a.parent/'report-ledgers'/(diagnostic['ledger_sha256']+'.json')).read_bytes()
    assert sha(captured) == diagnostic['ledger_sha256']
    assert all(v['state'] == 'DONE' for v in json.loads(captured).values())
    for name, info in parent['tokenizer_assets']['files'].items():
        assert sha((a.assets/name).read_bytes()) == info['sha256']
    codec = Tokenizer.from_file(str(a.assets/'tokenizer.json')); codec.no_padding(); codec.no_truncation()
    template = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True).from_string(
        (a.assets/'chat_template.jinja').read_text(encoding='utf-8'))
    settings = dict(parent['settings'])
    settings.update(chat_template_kwargs={'enable_thinking': True, 'low_effort': True}, max_output_tokens=8192)
    def count(context): return len(codec.encode(context, add_special_tokens=False).ids)
    def prompt_tokens(question, context):
        payload = answer_payload(settings['model'], question, context,
                                 **{k: v for k, v in settings.items() if k not in ('model', 'timeout_seconds')})
        return count(template.render(messages=payload['messages'], add_generation_prompt=True, **settings['chat_template_kwargs']))
    chosen = [dict(row) for row in parent['observations'] if
              row['method'] == 'none' or row['budget'] == 2048 and
              row['method'] in ('npk_bm25_60', 'crisp_native_nim_guarded')]
    assert len(chosen) == 3*len(parent['dataset']['tasks'])
    questions = {t['id']: t['question'] for t in parent['dataset']['tasks']}
    full_hash = next(row['context_sha256'] for row in parent['observations'] if row['method'] == 'full')
    full_bytes = (a.parent/'contexts'/(full_hash+'.txt')).read_bytes(); assert sha(full_bytes) == full_hash
    full = full_bytes.decode(); assert count(full) == parent['corpus_tokens']
    baselines = {tid: prompt_tokens(question, full) for tid, question in questions.items()}
    assert max(baselines.values())+settings['max_output_tokens'] < 1_000_000
    a.output.mkdir(parents=True); (a.output/'contexts').mkdir()
    random.Random(2917).shuffle(chosen); requests = {}
    for row in chosen:
        body = (a.parent/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert sha(body) == row['context_sha256']; context = body.decode(); question = questions[row['task']]
        assert count(context) == row['selected_tokens']
        key = request_key(settings, question, context)
        assert key != row['request_sha256']
        row['parent_request_sha256'] = row['request_sha256']; row['request_sha256'] = key
        row['selected_prompt_tokens'] = prompt_tokens(question, context)
        row['baseline_prompt_tokens'] = baselines[row['task']]
        (a.output/'contexts'/(row['context_sha256']+'.txt')).write_bytes(body)
        if row.get('status') != 'SELECTION_FAILED':
            requests.setdefault(key, {'question': question, 'context_sha256': row['context_sha256']})
    plan = dict(parent)
    plan.update(created_utc=datetime.now(timezone.utc).isoformat(), settings=settings,
                parent_plan_sha256=sha(parent_bytes), triggering_report_sha256=sha(a.report.read_bytes()),
                profile='target_low_effort_8192_on_identical_evidence', observations=chosen, requests=requests,
                execution_order='Seed 2917, shuffled fixed 2K BM25/native CRISP and no-context controls',
                profile_code_sha256=sha(Path(__file__).read_bytes()))
    plan['limitations'] = [*parent['limitations'],
        'Target-profile diagnostic chosen after errors with supplied implementation bodies were observed',
        'Same questions, source contexts and primary grading; no source selection or optimizer change',
        'Thinking/low-effort flags and output cap change together; this is a configuration comparison, not an isolated thinking effect',
        'One target request per question/context; no multi-call reasoning-budget wrapper',
        'The pinned template contains low_effort support; hosted framing still needs observed usage verification',
        'Original non-thinking plan and all of its failures remain unchanged and open']
    (a.output/'preparation-source.py').write_bytes(Path(__file__).read_bytes())
    (a.output/'parent-plan.json').write_bytes(parent_bytes)
    (a.output/'triggering-report.json').write_bytes(a.report.read_bytes())
    (a.output/'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    (a.output/'plan.sha256').write_text(sha((a.output/'plan.json').read_bytes()), encoding='ascii')
    print({'status': 'PREPARED', 'requests': len(requests), 'observations': len(chosen),
           'profile': plan['profile'], 'new_api_calls': 0}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'report', 'assets', 'output'): p.add_argument('--'+name, type=Path, required=True)
    prepare(p.parse_args())

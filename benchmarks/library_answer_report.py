"""Audit actual behavior answers, missing transports, and matched-budget pairs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

from benchmarks.answer_records import validate_response, validate_origin, counts
from benchmarks.prospective_eval import request_key
from benchmarks.repository_eval import grade_answer, answer_payload


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def report(a):
    if a.output.exists(): raise ValueError('Fresh answer report required')
    code = Path(__file__).read_bytes()
    sources = a.run/'report-sources'; sources.mkdir(exist_ok=True)
    (sources/(sha(code)+'.py')).write_bytes(code)
    raw = (a.run/'plan.json').read_bytes(); plan = json.loads(raw)
    assert sha(raw) == (a.run/'plan.sha256').read_text().strip()
    ledger_bytes = (a.run/'ledger.json').read_bytes()
    ledger = json.loads(ledger_bytes); settings = plan['settings']
    recovery = None
    if 'transport_recovery' in plan:
        from benchmarks.answer_recovery import validate_recovery
        recovery = validate_recovery(a.run)
        assert recovery['ledger_sha256'] == sha(ledger_bytes)
    assert set(ledger) <= set(plan['requests'])
    assert all(entry['state'] == 'DONE' for entry in ledger.values()), 'Uncertain live attempt'
    tasks = {t['id']: t for t in plan['dataset']['tasks']}
    from tokenizers import Tokenizer
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    for name, meta in plan['tokenizer_assets']['files'].items():
        assert sha((a.assets/name).read_bytes()) == meta['sha256']
    codec = Tokenizer.from_file(str(a.assets/'tokenizer.json')); codec.no_truncation(); codec.no_padding()
    template = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True).from_string(
        (a.assets/'chat_template.jinja').read_text(encoding='utf-8'))
    contexts = {}; prompt_counts = {}; results = {}
    for key, item in plan['requests'].items():
        digest = item['context_sha256']
        if digest not in contexts:
            body = (a.run/'contexts'/(digest+'.txt')).read_bytes(); assert sha(body) == digest
            contexts[digest] = body.decode()
        context = contexts[digest]
        assert request_key(settings, item['question'], context) == key
        payload = answer_payload(settings['model'], item['question'], context,
                                 **{k: v for k, v in settings.items() if k not in {'model', 'timeout_seconds'}})
        rendered = template.render(messages=payload['messages'], add_generation_prompt=True,
                                   **settings['chat_template_kwargs'])
        prompt_counts[key] = len(codec.encode(rendered, add_special_tokens=False))
        if key not in ledger: continue
        result = ledger[key]['result']
        assert read(a.run/'responses'/(key+'.json')) == result
        assert result['request_sha256'] == key and result['question'] == item['question']
        assert result['context_sha256'] == digest
        validate_origin(a.run, result); validate_response(result)
        results[key] = result
    rows = []; seen = set()
    for observation in plan['observations']:
        cell = observation['task'], observation['method'], observation['budget']
        assert cell not in seen; seen.add(cell)
        key = observation['request_sha256']; digest = observation['context_sha256']
        if digest not in contexts:
            body = (a.run/'contexts'/(digest+'.txt')).read_bytes(); assert sha(body) == digest
            contexts[digest] = body.decode()
        assert observation['selected_tokens'] == len(codec.encode(contexts[digest], add_special_tokens=False))
        if observation['budget'] is not None: assert observation['selected_tokens'] <= observation['budget']
        assert observation['corpus_tokens'] == observation['available_tokens'] == plan['corpus_tokens']
        if observation.get('status') != 'SELECTION_FAILED':
            assert observation['selected_prompt_tokens'] == prompt_counts[key]
        row = dict(observation)
        if observation.get('status') == 'SELECTION_FAILED':
            assert observation['seed_failed']
            row.update(evidence_mode='SELECTION_FAILED', task_success=False, transport_success=None)
        elif key not in results:
            row.update(evidence_mode='PENDING', task_success=None, transport_success=None)
        else:
            result = results[key]
            assert plan['requests'][key]['question'] == tasks[row['task']]['question']
            assert observation['selected_prompt_tokens'] == prompt_counts[key]
            grade = grade_answer(result.get('content'), tasks[row['task']]['answer']) if result['transport_success'] else {'task_success': None}
            row.update(evidence_mode=result['evidence_mode'], transport_success=result['transport_success'], **grade)
            row['api_latency_ms'] = result['latency_ms']; row['usage'] = result.get('usage')
            row['transport_error'] = result.get('http_status', result.get('error_type'))
            if result['transport_success']:
                row['prompt_token_delta'] = prompt_counts[key]-result['usage']['prompt_tokens']
                row['finish_reason'] = result['raw_response']['choices'][0].get('finish_reason')
        rows.append(row)
    grouped = defaultdict(list)
    for row in rows: grouped[row['method'], row['budget']].append(row)
    summaries = []
    for (method, budget), group in sorted(grouped.items(), key=lambda cell: (cell[0][0], cell[0][1] or 0)):
        assert len(group) == len(tasks)
        known = [r for r in group if r['task_success'] is not None]
        successes = sum(r['task_success'] is True for r in known)
        summaries.append({'method': method, 'budget': budget, 'planned_tasks': len(group),
                          'known_task_outcomes': len(known), 'successful_tasks': successes,
                          'pending_tasks': sum(r['evidence_mode'] == 'PENDING' for r in group),
                          'transport_failures': sum(r['transport_success'] is False for r in group),
                          'selection_failures': sum(r['evidence_mode'] == 'SELECTION_FAILED' for r in group),
                          'accuracy': successes/len(group) if len(known) == len(group) else None,
                          'success_fraction_bounds_from_missing': [successes/len(group), (successes+len(group)-len(known))/len(group)],
                          'mean_selected_tokens': statistics.mean(r['selected_tokens'] for r in group),
                          'mean_input_tokens_actual': statistics.mean(r['usage']['prompt_tokens'] for r in group if r.get('usage'))
                                if any(r.get('usage') for r in group) else None,
                          'dollar_cost': None, 'dollar_reason': 'No verified billing rate or local compute price'})
    pairs = []
    for (method, budget), group in grouped.items():
        if budget is None: continue
        for baseline in plan.get('comparison_baselines', ('npk_bm25_60', 'crisp_native_nim_guarded', 'none')):
            comparison = {r['task']: r for r in grouped[baseline, None if baseline == 'none' else budget]}
            wins = []; losses = []; ties = []; missing = []
            for row in group:
                other = comparison[row['task']]
                if row['task_success'] is None or other['task_success'] is None: missing.append(row['task'])
                elif row['task_success'] == other['task_success']: ties.append(row['task'])
                elif row['task_success']: wins.append(row['task'])
                else: losses.append(row['task'])
            pairs.append({'method': method, 'budget': budget, 'baseline': baseline,
                          'wins': wins, 'losses': losses, 'ties': ties, 'missing_pairs': missing})
    account = counts(ledger)
    deltas = Counter(r['prompt_token_delta'] for r in rows if 'prompt_token_delta' in r)
    unique_deltas = Counter(prompt_counts[key]-result['usage']['prompt_tokens']
                            for key, result in results.items() if result['transport_success'])
    complete = set(ledger) == set(plan['requests'])
    answers_complete = complete and all(r['transport_success'] for r in results.values())
    result = {'status': 'COMPLETE' if complete else 'CHECKPOINT', 'evidence_mode': account['evidence_mode'],
              'attempt_stage_complete': complete, 'answer_stage_complete': answers_complete,
              'transport_recovery': recovery,
              'plan_sha256': sha(raw), 'ledger_sha256': sha(ledger_bytes),
              'reporter_sha256': sha(code), 'generative_optimization_calls': 0,
              'accounting': account, 'rows': rows, 'summaries': summaries, 'pairs': pairs,
              'observational_prompt_deltas': dict(deltas),
              'unique_response_prompt_deltas': dict(unique_deltas),
              'limits': ['Partial or transport-missing arms have N/A accuracy and explicit bounds, not imputed passes',
                         'Answer JSON is graded against executed oracles, never by another model',
                         'One stochastic sample per unique payload; repeated contexts are shared observations',
                         'Known public-library tasks permit memorization; compare the no-context control',
                         '15 inspected tasks cannot establish broad independent validation',
                         'Matched budget caps are swept; actual selected means can differ',
                         'No break-even dollar claim without verified target and local compute prices']}
    # Long tokenizer audits must not bind old counts to a newer running ledger.
    assert (a.run/'ledger.json').read_bytes() == ledger_bytes, 'ledger changed during audit; wait for a quiescent batch'
    snapshots = a.run/'report-ledgers'; snapshots.mkdir(exist_ok=True)
    captured = snapshots/(sha(ledger_bytes)+'.json')
    if captured.exists(): assert captured.read_bytes() == ledger_bytes
    else: captured.write_bytes(ledger_bytes)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({'status': result['status'], 'accounting': account, 'unique_response_prompt_deltas': dict(unique_deltas)}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'assets', 'output'): p.add_argument('--'+name, type=Path, required=True)
    report(p.parse_args())

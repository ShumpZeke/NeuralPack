"""Economics from one frozen answer experiment, with no historical overlays.

Reads exact requests/responses and regrades every planned observation. Costs are
optional provider-scoped text quotes, not invoices or net savings. No models are
called, loaded or downloaded. Missing arms, local compute cost and break-even
remain N/A instead of borrowing measurements from a different experiment.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

from benchmarks.modern_seed_report import audit_observations
from benchmarks.prospective_eval import request_key, write_json
from npk.auditor import _json
from npk.cost import estimate_cost, get_pricing
from benchmarks.answer_records import counts, validate_origin, validate_response


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def report(run_dir, *, provider=None, allow_pending=False):
    root = Path(run_dir)
    plan = _json((root/'plan.json').read_text(encoding='utf-8'))
    results = _json((root/'results.json').read_text(encoding='utf-8'))
    ledger = _json((root/'ledger.json').read_text(encoding='utf-8'))
    if sha(root/'plan.json') != (root/'plan.sha256').read_text().strip() or results.get('plan_sha256') != sha(root/'plan.json') or results['plan'] != plan:
        raise ValueError('Frozen plan mismatch')
    if not ledger.keys() <= plan['requests'].keys() or (not allow_pending and ledger.keys() != plan['requests'].keys()):
        raise ValueError('Request ledger does not match plan')
    quotes = {}; pricing_sources = {}
    for key, entry in ledger.items():
        if entry.get('state') != 'DONE': raise ValueError('Uncertain request still in ledger')
        result = entry['result']; request = plan['requests'][key]
        if type(result.get('api_attempts_this_run')) is not int or result['api_attempts_this_run'] not in (0, 1):
            raise ValueError('Request must record whether an API attempt occurred')
        if type(result.get('transport_success')) is not bool:
            raise ValueError('Completed request needs an explicit transport outcome')
        context = root/'contexts'/(request['context_sha256']+'.txt')
        raw = _json((root/'responses'/(key+'.json')).read_text(encoding='utf-8'))
        if sha(context) != request['context_sha256'] or request_key(plan['settings'], request['question'], context.read_bytes().decode()) != key:
            raise ValueError('Request context or identity mismatch')
        if result != raw or result.get('request_sha256') != key:
            raise ValueError('Response ledger mismatch')
        validate_origin(root,result)
        validate_response(result)
        if result.get('transport_success'):
            response = result['raw_response']
            if response['choices'][0]['message']['content'] != result['content'] or response['usage'] != result['usage']:
                raise ValueError('Parsed response differs from raw provider response')
            usage = result['usage']; model = response.get('model')
            quoted = get_pricing(model, provider=provider)
            if quoted: pricing_sources[model] = {'source': quoted.source, 'verified_on': quoted.verified_on, 'scope': quoted.scope}
            quotes[key] = estimate_cost(model, usage['prompt_tokens'], usage['completion_tokens'],
                                        usage.get('prompt_tokens_details', {}).get('cached_tokens', 0), provider=provider)
    audit_observations(plan, results['rows'], ledger, allow_pending)
    groups = defaultdict(list)
    for row in results['rows']:
        groups[(row.get('corpus'), row.get('cohort'), row['method'], row.get('budget'))].append(row)
    arms = []
    for (corpus, cohort, method, budget), rows in groups.items():
        completed = [r for r in rows if r.get('transport_success')]
        arm_quotes = [quotes[r['request_sha256']] for r in completed]
        arms.append({'corpus': corpus, 'cohort': cohort, 'method': method, 'budget': budget,
                     'planned': len(rows), 'completed': len(completed), 'passed': sum(r['task_success'] for r in completed),
                     'unique_requests': len({r['request_sha256'] for r in rows}),
                     'mean_reported_input_tokens': statistics.mean(r['usage']['prompt_tokens'] for r in completed) if completed else None,
                     'completed_prompt_quote_sum_usd': sum(arm_quotes) if arm_quotes and all(q is not None for q in arm_quotes) else None,
                     'per_task_context': [{k: r.get(k) for k in ('task', 'available_tokens', 'corpus_tokens', 'selected_tokens', 'baseline_prompt_tokens_estimate')} for r in rows]})
    observations = [e['result'] for e in ledger.values()]
    accounting = counts(ledger,allowed_modes=('LIVE','LOCAL','MOCK','REPLAY'))
    completed = [r for r in observations if r.get('transport_success')]
    all_quotes = list(quotes.values())
    modes = dict(Counter(r['evidence_mode'] for r in observations))
    return {'plan_sha256': sha(root/'plan.json'), 'reporter_sha256': sha(Path(__file__)),
            'evidence_mode': 'REPLAY', 'report_processing': 'LOCAL', 'new_api_calls': 0,
            'source_evidence_modes': modes, 'optimization_calls_by_this_report': 0,
            'live_attempts_in_ledger': accounting['attempts'],
            'replayed_records': accounting['replayed_records'],
            'unique_responses': len(completed), 'transport_failures': len(observations)-len(completed),
            'pending_unique_requests': sorted(plan['requests'].keys()-ledger.keys()),
            'reported_input_tokens_completed': sum(r['usage']['prompt_tokens'] for r in completed),
            'reported_output_tokens_completed': sum(r['usage']['completion_tokens'] for r in completed),
            'metric': 'exact JSON fixture pass counts' if any(m not in ('LIVE', 'LOCAL', 'REPLAY') for m in modes) else 'exact JSON task pass counts',
            'quote_provider_assumption': provider, 'pricing_sources': pricing_sources,
            'completed_unique_text_quote_usd': sum(all_quotes) if all_quotes and all(q is not None for q in all_quotes) else None,
            'actual_billed_usd': None, 'net_savings_usd': None, 'local_compute_usd': None, 'break_even_requests': None,
            'arms': arms,
            'limits': ['Cross-run answers require explicit byte-verified REPLAY origins; they are not new API observations',
                       'Quotes are hypothetical standard text fees for the supplied provider; returned model IDs must match exactly',
                       'Shared responses are not independent replications; per-arm quotes cannot be summed as experiment billing',
                       'Failed-call billing, local compute prices and net end-to-end savings are unmeasured',
                       'Available corpus counts are declared frozen-plan metadata; selected text is hash-checked',
                       'No missing full-context or remote-preprocessor arm is invented',
                       'Hashes and log consistency do not authenticate execution or establish sealed evaluation']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--quote-provider', default=None, help='Explicit provider assumption for optional text quotes')
    p.add_argument('--allow-pending', action='store_true')
    a = p.parse_args(); result = report(a.run, provider=a.quote_provider, allow_pending=a.allow_pending)
    write_json(a.output, result)
    print({'live_attempts': result['live_attempts_in_ledger'], 'responses': result['unique_responses'],
           'text_quote_usd': result['completed_unique_text_quote_usd'], 'net_savings_usd': result['net_savings_usd']})


if __name__ == '__main__': main()

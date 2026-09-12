"""One new attempt for known HTTP failures; never resample an existing answer.

This is evaluation tooling, not part of NeuralPack's optimizer. The parent
attempts are archived verbatim. Eligibility depends only on transport outcome.
"""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path

from npk.auditor import _json
from benchmarks.answer_records import counts, sha, validate_origin, validate_response, json_identical
from benchmarks.prospective_eval import request_key, write_json


def read(path):
    return _json(path.read_bytes().decode('utf-8'))


def stage_observations(plan):
    return [r for r in plan['observations'] if r['budget'] == 2048 or r['method'] == 'none']


def retry_eligible(result):
    return (result.get('transport_success') is False
            and type(result.get('http_status')) is int
            and result['http_status'] in (429, 503)
            and result.get('content') is None and result.get('usage') is None
            and result.get('raw_response') is None)


def require_payload(root, plan, key, result):
    request = plan['requests'][key]
    digest = request['context_sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid context digest')
    body = (root/'contexts'/(digest+'.txt')).read_bytes()
    if sha(body) != digest or request_key(plan['settings'], request['question'], body.decode()) != key:
        raise ValueError('Frozen payload changed')
    if (result.get('request_sha256') != key or result.get('question') != request['question']
            or result.get('context_sha256') != digest):
        raise ValueError('Attempt does not match its frozen payload')
    validate_response(result)


def projected_plan(parent):
    if 'transport_recovery' in parent:
        raise ValueError('Recovery chains need a separate explicit policy')
    plan = deepcopy(parent)
    plan['observations'] = stage_observations(parent)
    keys = {r['request_sha256'] for r in plan['observations'] if r.get('status') != 'SELECTION_FAILED'}
    if not keys or not keys <= parent['requests'].keys():
        raise ValueError('Stage has no valid requests')
    plan['requests'] = {k: v for k, v in parent['requests'].items() if k in keys}
    plan['execution_order'] = 'Frozen parent stage one order; reuse answers, retry only known HTTP 429/503 failures once'
    return plan


def require_parent_ledger(plan, ledger):
    if set(ledger) != set(plan['requests']) or any(r.get('state') != 'DONE' for r in ledger.values()):
        raise ValueError('Parent must have a terminal attempt for every stage request and no others')
    counts(ledger, allowed_modes=('LIVE',))


def blob(root, digest):
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid origin digest')
    raw = (root/'replay-origins'/(digest+'.json')).read_bytes()
    if sha(raw) != digest:
        raise ValueError('Archived origin changed')
    return raw


def require_parent_record(root, plan, key, original, entry):
    if not json_identical(original, entry['result']):
        raise ValueError('Parent response and ledger differ')
    require_payload(root, plan, key, original)
    if not original['transport_success'] and not retry_eligible(original):
        raise ValueError('Unknown or unsupported parent failure cannot be retried')


def replay(original, record_sha, plan_sha):
    return {**original, 'evidence_mode': 'REPLAY', 'api_attempts_this_run': 0,
            'replay_origin': {'record_sha256': record_sha, 'plan_sha256': plan_sha}}


def validate_recovery(root):
    """Validate immutable lineage, selection and all current attempt records."""
    root = Path(root)
    raw = (root/'plan.json').read_bytes()
    if sha(raw) != (root/'plan.sha256').read_text().strip():
        raise ValueError('Recovery plan changed')
    plan = _json(raw.decode()); meta = plan['transport_recovery']
    if type(meta['version']) is not int or meta['version'] != 1 or not json_identical(meta['eligible_http_statuses'], [429, 503]):
        raise ValueError('Unsupported recovery policy')
    parent = _json(blob(root, meta['parent_plan_sha256']).decode())
    parent_ledger = _json(blob(root, meta['parent_ledger_sha256']).decode())
    expected = projected_plan(parent)
    expected['created_utc'] = plan['created_utc']
    expected['transport_recovery'] = meta
    if not json_identical(plan, expected):
        raise ValueError('Recovery changed the frozen questions, selection or settings')
    require_parent_ledger(plan, parent_ledger)
    if set(meta['parent_records']) != set(parent_ledger):
        raise ValueError('Missing parent attempt lineage')
    originals = {}
    for key, digest in meta['parent_records'].items():
        original = _json(blob(root, digest).decode())
        require_parent_record(root, plan, key, original, parent_ledger[key])
        originals[key] = original
    retry_keys = [k for k in plan['requests'] if retry_eligible(originals[k])]
    if meta['retry_keys'] != retry_keys:
        raise ValueError('Retry eligibility must follow transport outcome only')
    ledger_raw = (root/'ledger.json').read_bytes(); ledger = _json(ledger_raw.decode())
    if not set(ledger) <= set(plan['requests']) or any(e.get('state') != 'DONE' for e in ledger.values()):
        raise ValueError('Uncertain or foreign recovery attempt')
    required_replays = set(plan['requests'])-set(retry_keys)
    if not required_replays <= set(ledger):
        raise ValueError('An existing answer was removed from replay')
    if {p.stem for p in (root/'responses').glob('*.json')} != set(ledger):
        raise ValueError('Orphan response: inspect before any new attempt')
    for key, entry in ledger.items():
        result = entry['result']
        if not json_identical(read(root/'responses'/(key+'.json')), result):
            raise ValueError('Recovery response and ledger differ')
        require_payload(root, plan, key, result)
        if key in required_replays:
            if not json_identical(result, replay(originals[key], meta['parent_records'][key], meta['parent_plan_sha256'])):
                raise ValueError('Original answer was changed or resampled')
            validate_origin(root, result)
        elif result.get('evidence_mode') != 'LIVE':
            raise ValueError('A retry must be a new explicit LIVE attempt')
    account = counts(ledger)
    if (root/'ledger.json').read_bytes() != ledger_raw:
        raise ValueError('Recovery ledger changed during preflight')
    return {'parent_plan_sha256': meta['parent_plan_sha256'],
            'parent_ledger_sha256': meta['parent_ledger_sha256'], 'ledger_sha256': sha(ledger_raw),
            'original_attempts': len(parent_ledger), 'original_answers': len(required_replays),
            'original_transport_failures': len(retry_keys), 'retry_eligible_payloads': len(retry_keys),
            'retry_attempts': account['attempts'], 'recovered_answers': account['live_answers'],
            'retry_transport_errors': account['live_transport_errors'],
            'cumulative_api_attempts': len(parent_ledger)+account['attempts'],
            'pending_retry_attempts': len(plan['requests'])-len(ledger),
            'unanswered_payloads': len(retry_keys)-account['live_answers']}


def require_bounded_execution(args):
    if (args.workers != 1 or not 1 <= args.max_requests <= 10
            or getattr(args, 'min_request_interval', 0) < 15
            or not 1 <= getattr(args, 'stop_after_errors', 4) <= 3):
        raise ValueError('Recovery needs one worker, 1-10 requests, >=15s pacing and <=3 errors')


def prepare(parent, destination, *, expected_plan, expected_ledger):
    """Archive a quiescent parent and freeze one transport-only recovery stage."""
    parent = Path(parent); root = Path(destination)
    if root.exists():
        raise ValueError('Recovery requires a fresh destination')
    parent_raw = (parent/'plan.json').read_bytes(); ledger_raw = (parent/'ledger.json').read_bytes()
    if sha(parent_raw) != expected_plan or expected_plan != (parent/'plan.sha256').read_text().strip():
        raise ValueError('Parent plan differs from the expected snapshot')
    if sha(ledger_raw) != expected_ledger:
        raise ValueError('Parent ledger differs from the expected snapshot')
    plan = projected_plan(_json(parent_raw.decode())); ledger = _json(ledger_raw.decode())
    require_parent_ledger(plan, ledger)
    records = {}; bodies = {}; contexts = {}
    for key, entry in ledger.items():
        raw = (parent/'responses'/(key+'.json')).read_bytes(); original = _json(raw.decode())
        require_parent_record(parent, plan, key, original, entry)
        records[key] = sha(raw); bodies[sha(raw)] = raw
    for row in plan['observations']:
        digest = row['context_sha256']; body = (parent/'contexts'/(digest+'.txt')).read_bytes()
        if sha(body) != digest:
            raise ValueError('Parent context changed')
        contexts[digest] = body
    plan['created_utc'] = datetime.now(timezone.utc).isoformat()
    plan['transport_recovery'] = {'version': 1, 'parent_plan_sha256': expected_plan,
        'parent_ledger_sha256': expected_ledger, 'parent_records': records,
        'eligible_http_statuses': [429, 503],
        'retry_keys': [k for k in plan['requests'] if retry_eligible(ledger[k]['result'])]}
    root.mkdir(parents=True)
    for directory in ('replay-origins', 'contexts', 'responses'):
        (root/directory).mkdir()
    bodies.update({expected_plan: parent_raw, expected_ledger: ledger_raw})
    for digest, body in bodies.items(): (root/'replay-origins'/(digest+'.json')).write_bytes(body)
    for digest, body in contexts.items(): (root/'contexts'/(digest+'.txt')).write_bytes(body)
    imported = {}
    for key, entry in ledger.items():
        if not entry['result']['transport_success']: continue
        result = replay(entry['result'], records[key], expected_plan)
        write_json(root/'responses'/(key+'.json'), result)
        imported[key] = {'state': 'DONE', 'result': result}
    write_json(root/'plan.json', plan)
    (root/'plan.sha256').write_text(sha((root/'plan.json').read_bytes()))
    write_json(root/'ledger.json', imported)
    if (parent/'ledger.json').read_bytes() != ledger_raw or (parent/'plan.json').read_bytes() != parent_raw:
        raise ValueError('Parent changed during recovery preparation')
    return validate_recovery(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-plan', required=True)
    parser.add_argument('--expected-ledger', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.parent, args.output, expected_plan=args.expected_plan,
                             expected_ledger=args.expected_ledger)), flush=True)

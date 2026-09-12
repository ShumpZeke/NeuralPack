"""Provenance and accounting for LIVE records and explicit cross-run replays."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from npk.auditor import _json


def sha(body): return hashlib.sha256(body).hexdigest()


def json_identical(left, right):
    """Compare serialized audit data without Python's bool/int/float coercion."""
    try:
        return (json.dumps(left, sort_keys=True, allow_nan=False)
                == json.dumps(right, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError):
        raise ValueError('Audit identity requires finite JSON data') from None


def validate_origin(root, result):
    """A derived replay must reconstruct exactly from an archived parent record."""
    if result.get('evidence_mode') != 'REPLAY': return
    origin=result.get('replay_origin')
    if not isinstance(origin,dict) or set(origin)!={'record_sha256','plan_sha256'}:
        raise ValueError('Replay needs an explicit record and plan origin')
    if any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v)
           for v in origin.values()):
        raise ValueError('Invalid replay origin digest')
    original_raw=(Path(root)/'replay-origins'/(origin['record_sha256']+'.json')).read_bytes()
    plan_raw=(Path(root)/'replay-origins'/(origin['plan_sha256']+'.json')).read_bytes()
    if sha(original_raw)!=origin['record_sha256'] or sha(plan_raw)!=origin['plan_sha256']:
        raise ValueError('Replay origin bytes changed')
    original=_json(original_raw.decode());plan=_json(plan_raw.decode())
    # A single archived LIVE origin is sufficient here; replay chains are not
    # silently flattened into alleged new model observations.
    if original.get('evidence_mode')!='LIVE' or type(original.get('api_attempts_this_run')) is not int or original['api_attempts_this_run']!=1:
        raise ValueError('Replay origin must be a recorded LIVE attempt')
    expected={**original,'evidence_mode':'REPLAY','api_attempts_this_run':0,'replay_origin':origin}
    if not json_identical(result,expected):
        raise ValueError('Replay differs from its original record')
    request=plan.get('requests',{}).get(original['request_sha256'])
    if request is None or request['question']!=original['question'] or request['context_sha256']!=original['context_sha256']:
        raise ValueError('Replay origin does not belong to its declared parent plan')
    from benchmarks.prospective_eval import request_key
    context=(Path(root)/'contexts'/(request['context_sha256']+'.txt')).read_bytes()
    if sha(context)!=request['context_sha256'] or request_key(plan['settings'],request['question'],context.decode())!=original['request_sha256']:
        raise ValueError('Replay origin payload does not match its recorded request')


def validate_response(result):
    """Reported answer and usage must equal the raw provider response."""
    if type(result.get('transport_success')) is not bool:raise ValueError('Explicit transport outcome required')
    if not result['transport_success']:return
    raw=result.get('raw_response',{});usage=raw.get('usage')
    if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):
        raise ValueError('Raw provider usage needs nonnegative integer token counts')
    choices=raw.get('choices')
    if not isinstance(choices,list) or not choices or not json_identical(result.get('content'),choices[0].get('message',{}).get('content')):
        raise ValueError('Reported content differs from raw response')
    if not json_identical(result.get('usage'),usage):raise ValueError('Reported usage differs from raw response')


def counts(ledger, *, allowed_modes=('LIVE','REPLAY')):
    rows=[]
    for entry in ledger.values():
        if entry.get('state')!='DONE':raise ValueError('Uncertain request cannot enter completed accounting')
        row=entry['result'];mode=row.get('evidence_mode');calls=row.get('api_attempts_this_run')
        if mode not in allowed_modes or type(calls) is not int or calls!=(1 if mode=='LIVE' else 0):
            raise ValueError('Evidence mode and API-attempt count disagree')
        if type(row.get('transport_success')) is not bool:raise ValueError('Explicit transport outcome required')
        rows.append(row)
    modes=dict(Counter(r['evidence_mode'] for r in rows))
    live=[r for r in rows if r['evidence_mode']=='LIVE'];replay=[r for r in rows if r['evidence_mode']=='REPLAY']
    return {'evidence_mode':'+'.join(m for m in ('LIVE','LOCAL','MOCK','REPLAY') if m in modes) or 'PENDING',
            'source_evidence_modes':modes,'unique_evidence_records':len(rows),'attempts':len(live),
            'live_answers':sum(r['transport_success'] for r in live),'replayed_records':len(replay),
            'replayed_answers':sum(r['transport_success'] for r in replay),
            'live_transport_errors':dict(Counter(str(r.get('http_status') or r.get('error_type')) for r in live if not r['transport_success'])),
            'replayed_transport_errors':dict(Counter(str(r.get('http_status') or r.get('error_type')) for r in replay if not r['transport_success']))}


def import_replays(parent, destination, plan):
    """Copy exact matching completed parent requests, including recorded failures."""
    parent=Path(parent);destination=Path(destination)
    if (destination/'ledger.json').exists():raise ValueError('Replay import must precede new execution')
    parent_raw=(parent/'plan.json').read_bytes();parent_sha=sha(parent_raw)
    if parent_sha!=(parent/'plan.sha256').read_text().strip():raise ValueError('Parent plan changed')
    parent_plan=_json(parent_raw.decode());ledger=_json((parent/'ledger.json').read_text())
    if not json_identical(plan['settings'],parent_plan['settings']):raise ValueError('Replay settings differ from parent model configuration')
    # Do not import a changing ledger or accidentally submit an uncertain parent
    # request again. Complete the parent run before freezing this reuse step.
    if set(ledger)!=set(parent_plan['requests']) or any(e.get('state')!='DONE' for e in ledger.values()):
        raise ValueError('Parent run must have a terminal outcome for every request')
    origins=destination/'replay-origins';origins.mkdir()
    cache=destination/'responses';cache.mkdir()
    (origins/(parent_sha+'.json')).write_bytes(parent_raw)
    imported={}
    for key,request in plan['requests'].items():
        if key not in ledger:continue
        if not json_identical(request,parent_plan['requests'][key]):raise ValueError('Shared request hash has different inputs')
        raw=(parent/'responses'/(key+'.json')).read_bytes();original=_json(raw.decode())
        if not json_identical(original,ledger[key]['result']):raise ValueError('Parent response and ledger differ')
        context=(destination/'contexts'/(request['context_sha256']+'.txt')).read_bytes()
        from benchmarks.prospective_eval import request_key
        if sha(context)!=request['context_sha256'] or request_key(plan['settings'],request['question'],context.decode())!=key:
            raise ValueError('Replay request bytes or payload identity differ')
        origin={'record_sha256':sha(raw),'plan_sha256':parent_sha}
        (origins/(origin['record_sha256']+'.json')).write_bytes(raw)
        result={**original,'evidence_mode':'REPLAY','api_attempts_this_run':0,'replay_origin':origin}
        validate_origin(destination,result)
        validate_response(result)
        (cache/(key+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        imported[key]={'state':'DONE','result':result}
    counts(imported)
    (destination/'ledger.json').write_text(json.dumps(imported,indent=2),encoding='utf-8')
    return {'parent_plan_sha256':parent_sha,'replayed_records':len(imported),
            'pending_new_requests':len(plan['requests'])-len(imported)}

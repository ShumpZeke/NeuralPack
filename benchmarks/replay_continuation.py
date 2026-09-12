"""Continue verified answer evidence while retaining its original LIVE provenance."""
from pathlib import Path
from benchmarks.answer_records import counts,sha,validate_origin,validate_response
from benchmarks.prospective_eval import request_key,write_json
from npk.auditor import _json


def import_completed(parent,destination,plan):
    parent=Path(parent);destination=Path(destination)
    if (destination/'ledger.json').exists():raise ValueError('Import must precede new execution')
    parent_raw=(parent/'plan.json').read_bytes();parent_sha=sha(parent_raw)
    if parent_sha!=(parent/'plan.sha256').read_text().strip():raise ValueError('Parent plan changed')
    parent_plan=_json(parent_raw.decode());ledger=_json((parent/'ledger.json').read_text(encoding='utf-8'))
    if plan['settings']!=parent_plan['settings']:raise ValueError('Parent settings differ')
    if set(ledger)!=set(parent_plan['requests']) or any(e.get('state')!='DONE' for e in ledger.values()):
        raise ValueError('Parent requests must all be terminal')
    counts(ledger)
    imported={};origins={};lineage={parent_sha:parent_raw};rows=[]
    for key,request in plan['requests'].items():
        if key not in ledger:continue
        if request!=parent_plan['requests'][key]:raise ValueError('Shared request differs')
        raw=(parent/'responses'/(key+'.json')).read_bytes();result=_json(raw.decode())
        if result!=ledger[key]['result'] or result.get('request_sha256')!=key or result.get('question')!=request['question'] or result.get('context_sha256')!=request['context_sha256']:
            raise ValueError('Parent response identity differs')
        context=(destination/'contexts'/(request['context_sha256']+'.txt')).read_bytes()
        if sha(context)!=request['context_sha256'] or request_key(plan['settings'],request['question'],context.decode())!=key:
            raise ValueError('Destination request bytes differ')
        validate_origin(parent,result);validate_response(result)
        inherited=result['evidence_mode']=='REPLAY'
        if inherited:
            origin=result['replay_origin'];replayed=dict(result)
            for digest in origin.values():origins[digest]=(parent/'replay-origins'/(digest+'.json')).read_bytes()
        else:
            origin={'record_sha256':sha(raw),'plan_sha256':parent_sha}
            origins[sha(raw)]=raw;origins[parent_sha]=parent_raw
            replayed={**result,'evidence_mode':'REPLAY','api_attempts_this_run':0,'replay_origin':origin}
        lineage[sha(raw)]=raw
        rows.append({'request_sha256':key,'parent_record_sha256':sha(raw),'parent_plan_sha256':parent_sha,
                     'inherited_replay':inherited,'original_live_origin':origin})
        imported[key]={'state':'DONE','result':replayed}
    counts(imported)
    for folder,contents in (('replay-origins',origins),('replay-lineage',lineage)):
        root=destination/folder;root.mkdir()
        for digest,body in contents.items():
            assert sha(body)==digest;(root/(digest+'.json')).write_bytes(body)
    cache=destination/'responses';cache.mkdir()
    for key,entry in imported.items():
        validate_origin(destination,entry['result']);validate_response(entry['result'])
        write_json(cache/(key+'.json'),entry['result'])
    summary={'parent_plan_sha256':parent_sha,'replayed_records':len(imported),
             'inherited_replays':sum(r['inherited_replay'] for r in rows),'pending_new_requests':len(plan['requests'])-len(imported),
             'lineage':rows,'note':'Original LIVE record and plan are preserved; intermediate parent bytes are retained separately, never counted as new calls'}
    write_json(destination/'replay-import.json',summary);write_json(destination/'ledger.json',imported)
    return summary

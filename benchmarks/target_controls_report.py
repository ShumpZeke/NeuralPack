"""Audit known-task target controls without promoting privileged retrieval."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import statistics
from benchmarks.answer_records import counts
from benchmarks.economics import report as audit_run
from benchmarks.prospective_eval import write_json


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def mean(values):return statistics.mean(values) if values else None


def compare(left,right,*,identical_context):
    """Require matching questions/caps; never turn missing responses into failures."""
    a={r['task']:r for r in left};b={r['task']:r for r in right}
    if len(a)!=len(left) or len(b)!=len(right) or set(a)!=set(b):
        raise ValueError('Unmatched or duplicate diagnostic tasks')
    pairs={'wins':[],'losses':[],'ties':[],'missing':[]}
    for task,candidate in b.items():
        baseline=a[task]
        if baseline['question']!=candidate['question'] or baseline['budget']!=candidate['budget']:
            raise ValueError('Diagnostic questions or caps changed')
        if identical_context and baseline['context_sha256']!=candidate['context_sha256']:
            raise ValueError('Target configuration comparison changed its evidence')
        if not baseline.get('transport_success') or not candidate.get('transport_success'):kind='missing'
        elif baseline['task_success']==candidate['task_success']:kind='ties'
        elif candidate['task_success']:kind='wins'
        else:kind='losses'
        pairs[kind].append(task)
    return pairs


def build(root,allow_pending=False):
    audits={};data={};plans={};accounting={};groups={};all_arms=[]
    preflight=read(root/'preflight.json')
    for name in ('direct','reasoning'):
        run=root/name;audits[name]=audit_run(run,allow_pending=allow_pending)
        data[name]=read(run/'results.json');plans[name]=read(run/'plan.json')
        ledger=read(run/'ledger.json');accounting[name]=counts(ledger)
        declared=next(p for p in preflight['plans'] if p['configuration']==name)
        if sha((run/'plan.json').read_bytes())!=declared['plan_sha256']:
            raise ValueError('Diagnostic preflight plan changed')
        questions={t['id']:t['question'] for t in plans[name]['dataset']['tasks']}
        enriched=[]
        for raw in data[name]['rows']:
            row={**raw,'question':questions[raw['task']]};enriched.append(row)
            if row['method']=='privileged_source':
                pieces=[]
                for e in row['evidence']:
                    path=(root/'source'/e['path']).resolve()
                    if not path.is_relative_to((root/'source').resolve()):raise ValueError('Source escaped archive')
                    body=path.read_bytes()
                    if sha(body)!=e['source_sha256'] or sha(body)!=preflight['source_sha256'][e['path']]:
                        raise ValueError('Privileged source changed')
                    match=re.fullmatch(re.escape(e['path'])+r':(\d+)-(\d+)',e['span'])
                    if not match:raise ValueError('Invalid source span')
                    first,last=map(int,match.groups());lines=body.decode().replace('\r\n','\n').replace('\r','\n').split('\n')
                    if not 1<=first<=last<=len(lines):raise ValueError('Source span outside file')
                    pieces.append('\n'.join(lines[first-1:last]))
                context='\n\n'.join(pieces)
                if sha(context.encode())!=row['context_sha256'] or not 0<max(1,len(context)//4)==row['selected_tokens']<=row['budget']:
                    raise ValueError('Privileged context differs from its exact source or budget')
        groups[name]={method:[r for r in enriched if r['method']==method] for method in ('none','bm25','privileged_source')}
        for method,rows in groups[name].items():
            done=[r for r in rows if r.get('transport_success')]
            all_arms.append({'configuration':name,'method':method,'planned':len(rows),'completed':len(done),
                             'passed':sum(r['task_success'] for r in done),
                             'parse_errors':sum(r['parse_error'] for r in done),
                             'valid_json_wrong_answer':sum(not r['parse_error'] and not r['task_success'] for r in done),
                             'mean_input_tokens':mean([r['usage']['prompt_tokens'] for r in done]),
                             'mean_output_tokens':mean([r['usage']['completion_tokens'] for r in done]),
                             'mean_target_ms':mean([r['latency_ms'] for r in done]),
                             'finish_reasons':dict(Counter(r['raw_response']['choices'][0].get('finish_reason') for r in done)),
                             'reasoning_field_present':sum(bool(r['raw_response']['choices'][0]['message'].get('reasoning_content')) for r in done)})
    expected=deepcopy(plans['direct']['settings'])
    expected.update(chat_template_kwargs={'enable_thinking':True},max_output_tokens=16384,timeout_seconds=180)
    if expected!=plans['reasoning']['settings'] or plans['direct']['dataset']!=plans['reasoning']['dataset']:
        raise ValueError('Unplanned target configuration or task change')
    config_pairs={method:compare(groups['direct'][method],groups['reasoning'][method],identical_context=True) for method in groups['direct']}
    source_pairs={name:compare(groups[name]['bm25'],groups[name]['privileged_source'],identical_context=False) for name in groups}
    return {'status':'PARTIAL' if any(a['pending_unique_requests'] for a in audits.values()) else 'COMPLETE',
            'evidence_mode':'LIVE+REPLAY','reporter_sha256':sha(Path(__file__).read_bytes()),
            'preflight_sha256':sha((root/'preflight.json').read_bytes()),'accounting':accounting,
            'generative_optimization_calls':0,'arms':all_arms,'configuration_pairs':config_pairs,
            'privileged_source_vs_bm25':source_pairs,'audits':audits,
            'settings':{name:p['settings'] for name,p in plans.items()},
            'limitations':plans['reasoning']['limitations'],
            'task_outcomes':{name:[{k:r.get(k) for k in ('task','method','budget','request_sha256','task_success','parse_error','transport_success')}
                                    for r in d['rows']] for name,d in data.items()}}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-pending',action='store_true');a=p.parse_args()
    result=build(a.root,allow_pending=a.allow_pending);write_json(a.output.with_suffix('.json'),result)
    lines=['# Cycle 20: target competence controls','',
           'EMPIRICAL diagnostic on eight known questions. Manually chosen source is privileged input, not a retrieval algorithm. '
           'The target reasoning configuration changes both the thinking flag and output allowance; it is not a compute-matched isolated flag test.',
           '', '| Target configuration | Source | Correct / completed / planned | Invalid JSON | Valid JSON, wrong answer | Mean input / output tokens |',
           '| --- | --- | --- | ---: | ---: | --- |']
    for r in result['arms']:
        usage='N/A' if r['mean_input_tokens'] is None else f"{r['mean_input_tokens']:.1f} / {r['mean_output_tokens']:.1f}"
        lines.append(f"| {r['configuration']} | {r['method']} | {r['passed']} / {r['completed']} / {r['planned']} | {r['parse_errors']} | {r['valid_json_wrong_answer']} | {usage} |")
    lines+=['','| Identical source: reasoning vs direct | Wins / losses / ties / missing |','| --- | --- |']
    for name,pair in result['configuration_pairs'].items():lines.append('| '+name+' | '+' / '.join(str(len(pair[k])) for k in ('wins','losses','ties','missing'))+' |')
    lines+=['','| Privileged source vs BM25 | Wins / losses / ties / missing |','| --- | --- |']
    for name,pair in result['privileged_source_vs_bm25'].items():lines.append('| '+name+' | '+' / '.join(str(len(pair[k])) for k in ('wins','losses','ties','missing'))+' |')
    lines+=['',f"Status: {result['status']}. Zero generative optimizer calls. Actual billed dollars and net savings are N/A.",'']
    lines+=['- '+x for x in result['limitations']]
    a.output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print({'status':result['status'],'arms':result['arms'],'configuration_pairs':result['configuration_pairs']})


if __name__=='__main__':main()

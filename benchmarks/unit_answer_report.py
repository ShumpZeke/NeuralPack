"""Regrade the frozen passage experiment and compare identical budget caps."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
from benchmarks.economics import report as audit_run
from benchmarks.prospective_eval import write_json
from benchmarks.target_controls_report import compare
from benchmarks.literal_answer_diagnostic import inspect_values


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def mean(values):return statistics.mean(values) if values else None


def build(root,local):
    audit=audit_run(root);data=read(root/'results.json');plan=read(root/'plan.json')
    if sha((local/'results.json').read_bytes())!=plan['local_results_sha256']:
        raise ValueError('LOCAL selection parent changed')
    rows=data['rows'];questions={t['id']:t['question'] for t in plan['dataset']['tasks']}
    expected={t['id']:t['answer'] for t in plan['dataset']['tasks']}
    groups={}
    for row in rows:groups.setdefault((row['method'],row['budget']),[]).append({**row,'question':questions[row['task']]})
    arms=[]
    for (method,budget),group in groups.items():
        done=[r for r in group if r.get('transport_success')]
        arms.append({'method':method,'budget':budget,'planned':len(group),'completed':len(done),
                     'passed':sum(r['task_success'] for r in done),'parse_errors':sum(r['parse_error'] for r in done),
                     'mean_input_tokens':mean([r['usage']['prompt_tokens'] for r in done]),
                     'mean_output_tokens':mean([r['usage']['completion_tokens'] for r in done]),
                     'mean_target_ms':mean([r['latency_ms'] for r in done]),
                     'mean_selected_tokens_estimate':mean([r['selected_tokens'] for r in group]),
                     'mean_selection_ms':mean([r['selection_ms'] for r in group]),
                     'cache_usage_reported':sum('cached_tokens' in r['usage'].get('prompt_tokens_details',{}) for r in done),
                     'reported_cached_input_sum':sum(r['usage'].get('prompt_tokens_details',{}).get('cached_tokens',0) or 0 for r in done),
                     'finish_reasons':dict(Counter(r['raw_response']['choices'][0].get('finish_reason') for r in done))})
    pairs=[]
    for cap in plan['budgets']:
        base=groups['shared_bm25',cap]
        for method in ('shared_hybrid','micro_paragraph'):
            pair=compare(base,groups[method,cap],identical_context=False)
            pairs.append({'baseline':'shared_bm25','candidate':method,'budget':cap,**pair})
    # This supplementary diagnostic was added after observing non-JSON Python
    # dictionaries. Preserve primary grades and mark unresolved formats missing.
    diagnostic_groups={};format_rows=[]
    for key,group in groups.items():
        diagnostic_groups[key]=[]
        for row in group:
            item=inspect_values(row['content'],expected[row['task']]) if row.get('transport_success') else {'form':'transport missing','values_match':None}
            format_rows.append({'task':row['task'],'method':row['method'],'budget':row['budget'],**item})
            diagnostic_groups[key].append({**row,'transport_success':item['values_match'] is not None,'task_success':item['values_match']})
    format_pairs=[]
    for cap in plan['budgets']:
        for method in ('shared_hybrid','micro_paragraph'):
            format_pairs.append({'candidate':method,'budget':cap,**compare(diagnostic_groups['shared_bm25',cap],diagnostic_groups[method,cap],identical_context=False)})
    # Same task set across every selected method AND swept cap. Never construct
    # a frontier by comparing success counts with different missing denominators.
    selected=[(m,b) for m in plan['methods'] for b in plan['budgets']]
    common=set(questions)
    for key in selected:common&={r['task'] for r in groups[key] if r.get('transport_success')}
    points=[]
    for method,cap in selected:
        completed=[r for r in groups[method,cap] if r['task'] in common]
        points.append({'method':method,'budget':cap,'tasks':len(common),
                       'successes':sum(r['task_success'] for r in completed),
                       'mean_actual_input_tokens':mean([r['usage']['prompt_tokens'] for r in completed])})
    frontier=[p for p in points if common and not any(
        q['mean_actual_input_tokens']<=p['mean_actual_input_tokens'] and q['successes']>=p['successes'] and
        (q['mean_actual_input_tokens']<p['mean_actual_input_tokens'] or q['successes']>p['successes']) for q in points)]
    return {'status':'COMPLETE','evidence_mode':'LIVE+REPLAY','report_processing':'LOCAL',
            'reporter_sha256':sha(Path(__file__).read_bytes()),'generative_optimization_calls':0,
            'arms':arms,'paired_vs_bm25':pairs,'common_completed_tasks':sorted(common),
            'posthoc_format_diagnostic':{'rows':format_rows,'pairs_vs_bm25':format_pairs,
                                        'primary_grades_changed':False,'unresolved_formats':'missing in this supplementary comparison'},
            'complete_case_curve':points,'complete_case_frontier':frontier,'audit':audit,
            'task_outcomes':[{k:r.get(k) for k in ('task','method','budget','request_sha256','context_sha256','task_success','parse_error','transport_success','http_status','latency_ms','usage')} for r in rows],
            'limitations':plan['limitations']+[
                'Complete-case frontier uses only tasks with responses in all six selected arms; transport selection can bias this small subset',
                'The no-source and full-source controls are outside the equal-cap comparison; full source is never silently truncated',
                'Reported cache hits can change hosted latency and economics; missing cache counters are unavailable, not proof of zero reuse',
                'One stochastic response per unique payload; shared requests are not independent replication',
                'Post-hoc literal-value diagnostic separates some formatting failures; it does not replace strict JSON outcomes or normalize semantically similar strings',
                'Source-pass counts are LOCAL diagnostics; exact executable-oracle answers determine LIVE task success']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',type=Path,required=True)
    p.add_argument('--local',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=build(a.live,a.local);write_json(a.output.with_suffix('.json'),result)
    lines=['# Cycle 24: answers from compiled SQLAlchemy documentation','',
           'EMPIRICAL. Ten developer-authored executable scenarios, one target model, one response per unique payload. '
           'The paragraph challenger was chosen after inspecting LOCAL passage diagnostics. This is not independently sealed validation.',
           '', '| Source method | Evidence cap | Correct / completed / planned | Mean actual input / output tokens | Mean target ms |',
           '| --- | ---: | --- | --- | ---: |']
    for r in result['arms']:
        usage='N/A' if r['mean_input_tokens'] is None else f"{r['mean_input_tokens']:.1f} / {r['mean_output_tokens']:.1f}"
        latency='N/A' if r['mean_target_ms'] is None else f"{r['mean_target_ms']:.1f}"
        lines.append(f"| {r['method']} | {r['budget'] or 'control'} | {r['passed']} / {r['completed']} / {r['planned']} | {usage} | {latency} |")
    lines+=['','| Same cap: candidate vs BM25 | Budget | Wins / losses / ties / missing |','| --- | ---: | --- |']
    for pair in result['paired_vs_bm25']:
        lines.append('| '+pair['candidate']+' | '+str(pair['budget'])+' | '+' / '.join(str(len(pair[k])) for k in ('wins','losses','ties','missing'))+' |')
    lines+=['','Post-hoc format diagnostic: JSON and bounded Python literal dictionaries are inspected for exact values. '
            'Primary grades remain unchanged; unsupported or ambiguous formats become missing in this supplementary comparison.',
            '', '| Literal values: candidate vs BM25 | Budget | Wins / losses / ties / missing |','| --- | ---: | --- |']
    for pair in result['posthoc_format_diagnostic']['pairs_vs_bm25']:
        lines.append('| '+pair['candidate']+' | '+str(pair['budget'])+' | '+' / '.join(str(len(pair[k])) for k in ('wins','losses','ties','missing'))+' |')
    audit=result['audit']
    lines+=['',f"{audit['live_attempts_in_ledger']} unique LIVE attempts, {audit['unique_responses']} completed answers, "
            f"{audit['transport_failures']} missing transport outcomes. Failures are not incorrect answers. "
            'Zero generative optimizer calls. Actual billed dollars, net savings and break-even are N/A.',
            '',f"The complete-case token/quality frontier uses {len(result['common_completed_tasks'])} tasks shared across all six selected arms. "
            'All arm outcomes and the discarded incomplete pairs remain in the JSON record. This frontier is a small descriptive subset, not a promotion test.', '']
    lines+=['- '+x for x in result['limitations']]
    a.output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print({'status':result['status'],'arms':result['arms'],'pairs':result['paired_vs_bm25'],'common_tasks':len(result['common_completed_tasks'])})


if __name__=='__main__':main()

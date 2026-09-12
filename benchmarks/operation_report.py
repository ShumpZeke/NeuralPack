"""Audit completed operation-view answers, missing results and paired budgets."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
from benchmarks.economics import report as audit_answers
from benchmarks.answer_records import counts
from benchmarks.literal_answer_diagnostic import inspect_values
from benchmarks.operation_seeds import operation_views
from benchmarks.prospective_eval import write_json
from benchmarks.target_controls_report import compare


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(body):return hashlib.sha256(body).hexdigest()
def mean(values):return statistics.mean(values) if values else None


def build(local,live,*,allow_pending=False):
    data=read(local/'results.json');plan=read(live/'plan.json');answers=read(live/'results.json')
    assert sha((local/'results.json').read_bytes())==plan['local_results_sha256']
    audit=audit_answers(live,allow_pending=allow_pending)
    ledger=read(live/'ledger.json');accounting=counts(ledger)
    mode_usage={mode:{'prompt_tokens':sum(e['result']['usage']['prompt_tokens'] for e in ledger.values() if e['result']['evidence_mode']==mode and e['result']['transport_success']),
                      'completion_tokens':sum(e['result']['usage']['completion_tokens'] for e in ledger.values() if e['result']['evidence_mode']==mode and e['result']['transport_success'])}
                for mode in ('LIVE','REPLAY')}
    tasks={t['id']:t for t in plan['dataset']['tasks']};windows=read(local/'encoder-windows.json')
    # The post-run Unicode repair may change new counterexamples. It must leave
    # every frozen operation query unchanged before these results describe it.
    for row in windows:
        query=next(t['question'] for t in data['tasks'] if t['id']==row['task'])
        views,signals=operation_views(query)
        assert [vars(v) for v in views]==row['operation_spans'] and signals==row['operation_signals']
    groups={};format_rows=[]
    for row in answers['rows']:
        groups.setdefault((row['cohort'],row['method'],row['budget']),[]).append({**row,'question':tasks[row['task']]['question']})
        diag=inspect_values(row['content'],tasks[row['task']]['answer']) if row.get('transport_success') else {'form':'transport missing','values_match':None}
        format_rows.append({k:row[k] for k in ('task','cohort','method','budget')}|diag)
    arms=[];pairs=[];format_pairs=[];curves=[]
    for (cohort,method,budget),group in groups.items():
        done=[r for r in group if r.get('transport_success')]
        arms.append({'cohort':cohort,'method':method,'budget':budget,'planned':len(group),'completed':len(done),
                     'passed':sum(r['task_success'] for r in done),'parse_errors':sum(r['parse_error'] for r in done),
                     'mean_actual_input_tokens':mean([r['usage']['prompt_tokens'] for r in done]),
                     'mean_actual_output_tokens':mean([r['usage']['completion_tokens'] for r in done]),
                     'mean_target_ms':mean([r['latency_ms'] for r in done]),'mean_selection_ms':mean([r['selection_ms'] for r in group]),
                     'mean_selected_tokens':mean([r['selected_tokens'] for r in group]),
                     'pending':sum(r.get('evidence_mode')=='PENDING' for r in group),
                     'transport_failures':dict(Counter(str(r.get('http_status') or r.get('error_type')) for r in group if r.get('transport_success') is False))})
    for cohort in ('known_scenarios','new_scenarios'):
        keys=[(cohort,m,b) for m in plan['methods'] for b in plan['budgets']]
        common=set.intersection(*[{r['task'] for r in groups[k] if r.get('transport_success')} for k in keys])
        points=[]
        for key in keys:
            rows=[r for r in groups[key] if r['task'] in common]
            points.append({'method':key[1],'budget':key[2],'tasks':len(common),'successes':sum(r['task_success'] for r in rows),
                           'mean_actual_input_tokens':mean([r['usage']['prompt_tokens'] for r in rows])})
        frontier=[p for p in points if common and not any(q['mean_actual_input_tokens']<=p['mean_actual_input_tokens'] and q['successes']>=p['successes'] and
                  (q['mean_actual_input_tokens']<p['mean_actual_input_tokens'] or q['successes']>p['successes']) for q in points)]
        curves.append({'cohort':cohort,'common_tasks':sorted(common),'points':points,'frontier':frontier})
        for budget in plan['budgets']:
            baseline=groups[cohort,'bm25',budget]
            for method in plan['methods']:
                if method=='bm25':continue
                candidate=groups[cohort,method,budget]
                pairs.append({'cohort':cohort,'candidate':method,'budget':budget,**compare(baseline,candidate,identical_context=False)})
                converted=[]
                for group in (baseline,candidate):
                    rows=[]
                    for row in group:
                        diag=next(d for d in format_rows if all(d[k]==row[k] for k in ('task','method','budget')))
                        rows.append({**row,'transport_success':diag['values_match'] is not None,'task_success':diag['values_match']})
                    converted.append(rows)
                format_pairs.append({'cohort':cohort,'candidate':method,'budget':budget,**compare(*converted,identical_context=False)})
    local_pairs=[];local_frontiers=[]
    for cohort in ('known_scenarios','new_scenarios'):
        for layout in ('original','padded'):
            points=[p for p in data['summary'] if p['cohort']==cohort and p['layout']==layout]
            frontier=[p for p in points if not any(q['mean_selected_tokens']<=p['mean_selected_tokens'] and q['all_required_passages']>=p['all_required_passages'] and
                       (q['mean_selected_tokens']<p['mean_selected_tokens'] or q['all_required_passages']>p['all_required_passages']) for q in points)]
            local_frontiers.append({'cohort':cohort,'layout':layout,'points':frontier})
            for budget in data['budgets']:
                rows=[r for r in data['unique'] if r['cohort']==cohort and r['layout']==layout and r['budget']==budget]
                base={r['task']:r for r in rows if r['method']=='bm25'}
                for method in data['methods']:
                    if method=='bm25':continue
                    pair={'cohort':cohort,'layout':layout,'candidate':method,'budget':budget,'wins':[],'losses':[],'ties':[]}
                    for row in (r for r in rows if r['method']==method):
                        name='ties' if row['all_required_spans']==base[row['task']]['all_required_spans'] else 'wins' if row['all_required_spans'] else 'losses'
                        pair[name].append(row['task'])
                    local_pairs.append(pair)
    return {'status':'INCOMPLETE' if audit['pending_unique_requests'] else 'COMPLETE','verdict':'PIVOT REQUIRED','evidence_mode':'LIVE+REPLAY','report_processing':'LOCAL',
            'audit':audit,'attempt_accounting':accounting,'reported_usage_by_mode':mode_usage,
            'plan_sha256':sha((live/'plan.json').read_bytes()),'local_results_sha256':sha((local/'results.json').read_bytes()),
            'reporter_sha256':sha(Path(__file__).read_bytes()),'current_operation_view_equivalence':len(windows),
            'local_curve':data['summary'],'local_pairs_vs_bm25':local_pairs,'local_descriptive_frontiers':local_frontiers,
            'answer_arms':arms,'paired_answers_vs_bm25':pairs,'complete_case_curves':curves,
            'literal_format_diagnostic':{'rows':format_rows,'pairs_vs_bm25':format_pairs,'primary_grades_changed':False},
            'limitations':plan['limitations']+['Transport failures remain missing; complete-case curves can be small and selectively biased',
              'Literal-value diagnostics are supplementary and preserve strict JSON grades',
              'Query-window diagnostics measure actual cached tokenizer offsets; counting untruncated tokens does not send that long sequence to the encoder',
              'Default runtime unchanged; query-view candidates and parser repairs remain research code']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('local','live','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--allow-pending',action='store_true')
    a=p.parse_args();result=build(a.local,a.live,allow_pending=a.allow_pending);write_json(a.output.with_suffix('.json'),result)
    lines=['# Cycle 27: operation-query evidence and target answers','',
           'EMPIRICAL. Twenty developer-authored scenarios; ten known and ten new. Five methods at equal 1K/4K caps. '
           'Exact matching old responses are explicitly REPLAY; new responses are LIVE. Zero generative optimizer calls.',
           '',f"Run status: {result['status']}. Unattempted requests: {len(result['audit']['pending_unique_requests'])}.",'',
           '| Cohort | Method | Cap | Correct / completed / planned | Mean actual input / output tokens |',
           '| --- | --- | ---: | ---: | ---: |']
    for r in result['answer_arms']:
        usage='N/A' if r['mean_actual_input_tokens'] is None else f"{r['mean_actual_input_tokens']:.1f} / {r['mean_actual_output_tokens']:.1f}"
        lines.append(f"| {r['cohort']} | {r['method']} | {r['budget'] or 'control'} | {r['passed']} / {r['completed']} / {r['planned']} | {usage} |")
    lines+=['','| Cohort | Candidate vs BM25 | Cap | Wins / losses / ties / missing |','| --- | --- | ---: | --- |']
    for r in result['paired_answers_vs_bm25']:
        lines.append(f"| {r['cohort']} | {r['candidate']} | {r['budget']} | "+' / '.join(str(len(r[k])) for k in ('wins','losses','ties','missing'))+' |')
    lines+=['','Billing, local dollar cost and net savings are N/A. Missing answers are not losses. '
            'Source-retention scores and tokenizer truncation are diagnostics, not answer accuracy. '
            'The full-source and no-source controls are outside equal-cap comparisons.']
    a.output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print({'audit':{k:result['audit'][k] for k in ('live_attempts_in_ledger','replayed_records','unique_responses','transport_failures')},
           'answer_arms':result['answer_arms'],'view_equivalence':result['current_operation_view_equivalence']},flush=True)


if __name__=='__main__':main()

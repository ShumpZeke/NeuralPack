"""Audit and report modern seed trials without equating source coverage to accuracy."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics as st
from benchmarks.prospective_eval import request_key, write_json
from benchmarks.repository_eval import grade_answer
from benchmarks.answer_records import counts, validate_origin, validate_response


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def mean(values): return st.mean(values) if values else None


def grouped(rows, keys):
    groups = {}
    for row in rows: groups.setdefault(tuple(row[k] for k in keys), []).append(row)
    return groups


def dominates(a, b):
    return (a['mean_actual_input_tokens'] <= b['mean_actual_input_tokens'] and a['successes'] >= b['successes']
            and (a['mean_actual_input_tokens'] < b['mean_actual_input_tokens'] or a['successes'] > b['successes']))


def corpus_comparisons(rows, baseline):
    """Compare the same method/question/cap across explicitly named corpora."""
    if baseline is None:return []
    groups=grouped(rows,('corpus','cohort','method','budget'))
    if baseline not in {key[0] for key in groups}:raise ValueError('Unknown baseline corpus')
    indexed={}
    for key,group in groups.items():
        by_task={r['task']:r for r in group}
        if len(by_task)!=len(group):raise ValueError('Duplicate task in corpus comparison')
        indexed[key]=by_task
    comparisons=[]
    for (corpus,cohort,method,budget),candidate in indexed.items():
        if corpus==baseline:continue
        original=indexed.get((baseline,cohort,method,budget))
        if original is None or set(original)!=set(candidate):raise ValueError('Corpora lack matching task/method/budget groups')
        record={'baseline_corpus':baseline,'corpus':corpus,'cohort':cohort,'method':method,'budget':budget,
                'wins':[],'losses':[],'ties':[],'missing':[],'identical_requests':[]}
        for task,row in candidate.items():
            base=original[task]
            if row['request_sha256']==base['request_sha256']:record['identical_requests'].append(task)
            if not row.get('transport_success') or not base.get('transport_success'):kind='missing'
            elif row['task_success']==base['task_success']:kind='ties'
            elif row['task_success']:kind='wins'
            else:kind='losses'
            record[kind].append(task)
        comparisons.append(record)
    return comparisons


def audit_observations(plan, rows, ledger, allow_pending=False):
    tasks = {t['id']: t for t in plan['dataset']['tasks']}
    if len(rows) != len(plan['observations']):
        raise ValueError('Report must contain every planned observation exactly once')
    audited = 0; seen = set()
    for observation, row in zip(plan['observations'], rows):
        key = observation['request_sha256']
        if observation.get('status') == 'SELECTION_FAILED':
            expected = {**observation, 'evidence_mode': 'SELECTION_FAILED', 'task_success': False}
        elif key not in ledger or 'result' not in ledger[key]:
            if not allow_pending: raise ValueError('Report has an uncompleted request')
            expected = {**observation, 'evidence_mode': 'PENDING', 'task_success': None}
        else:
            result = dict(ledger[key]['result'])
            if key in seen: result.update(evidence_mode='REPLAY', api_attempts_this_run=0)
            seen.add(key)
            checked = grade_answer(result.get('content'), tasks[observation['task']]['answer']) if result.get('transport_success') else {
                'task_success': None, 'parse_error': None}
            expected = {**observation, **result, **checked}
            audited += int(bool(result.get('transport_success')))
        if row != expected:
            raise ValueError('Report observation differs from frozen plan, raw ledger or independent grade')
    return audited


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--local', type=Path, required=True); p.add_argument('--live', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--title', default='Cycle 14: modern seeds and external source')
    p.add_argument('--allow-pending', action='store_true', help='Report an explicitly incomplete plan without hiding pending observations')
    p.add_argument('--baseline-corpus', help='Also compare identical methods and budgets against this corpus')
    args = p.parse_args()
    local = json.loads((args.local/'results.json').read_text()); assert local['status'] == 'COMPLETE'
    live = json.loads((args.live/'results.json').read_text()); plan = live['plan']
    assert sha(args.live/'plan.json') == (args.live/'plan.sha256').read_text().strip() == live['plan_sha256']
    assert plan == json.loads((args.live/'plan.json').read_text()), 'embedded plan differs from frozen plan'
    assert plan['parent_results_sha256'] == sha(args.local/'results.json')
    tasks = {t['id']: t for t in plan['dataset']['tasks']}
    ledger = json.loads((args.live/'ledger.json').read_text()); audited = 0
    assert ledger.keys() <= plan['requests'].keys()
    if not args.allow_pending: assert ledger.keys() == plan['requests'].keys()
    for key, entry in ledger.items():
        assert entry['state'] == 'DONE'; result = entry['result']; request = plan['requests'][key]
        context_path = args.live/'contexts'/(request['context_sha256']+'.txt')
        assert sha(context_path) == request['context_sha256']
        context = context_path.read_bytes().decode()
        assert request_key(plan['settings'], request['question'], context) == key == result['request_sha256']
        assert result == json.loads((args.live/'responses'/(key+'.json')).read_text())
        validate_origin(args.live, result)
        validate_response(result)
    audited = audit_observations(plan, live['rows'], ledger, args.allow_pending)
    local_arms = []
    for (corpus, cohort, method, budget), rows in grouped(local['rows'], ('corpus', 'cohort', 'method', 'budget')).items():
        local_arms.append({'corpus': corpus, 'cohort': cohort, 'method': method, 'budget': budget,
                          'tasks': len(rows), 'required_source_present': sum(r['required_source_present'] for r in rows),
                          'all_required_spans': sum(r['all_required_spans'] for r in rows),
                          'mean_required_span_fraction': mean([r['required_span_fraction'] for r in rows]),
                          'median_selection_ms': st.median(r['selection_ms'] for r in rows),
                          'mean_selected_tokens': mean([r['selected_tokens'] for r in rows]),
                          'failed_selections': sum(r['seed_failed'] for r in rows),
                          'risk_bands': dict(Counter(r['risk_band'] for r in rows))})
    live_arms = []; pairs = []; frontiers = []
    for (corpus, cohort), all_rows in grouped(live['rows'], ('corpus', 'cohort')).items():
        arms = grouped(all_rows, ('method', 'budget'))
        completed_sets = [{r['task'] for r in rows if r.get('transport_success')} for rows in arms.values()]
        common = sorted(set.intersection(*completed_sets)); common_arms = []
        for (method, budget), rows in arms.items():
            done = [r for r in rows if r.get('transport_success')]
            live_arms.append({'corpus': corpus, 'cohort': cohort, 'method': method, 'budget': budget,
                              'planned': len(rows), 'completed': len(done), 'successes': sum(r['task_success'] for r in done),
                              'mean_actual_input_tokens': mean([r['usage']['prompt_tokens'] for r in done]),
                              'mean_selected_tokens': mean([r['selected_tokens'] for r in rows]),
                              'median_selection_ms': st.median(r['selection_ms'] for r in rows),
                              'errors': sorted(r['task'] for r in rows if not r.get('transport_success'))})
            selected = [r for r in done if r['task'] in common]
            common_arms.append({'method': method, 'budget': budget, 'tasks': len(common),
                               'successes': sum(r['task_success'] for r in selected),
                               'mean_actual_input_tokens': mean([r['usage']['prompt_tokens'] for r in selected])})
        frontier = [a for a in common_arms if common and not any(dominates(b, a) for b in common_arms)]
        frontiers.append({'corpus': corpus, 'cohort': cohort, 'common_tasks': common,
                          'all_arms': common_arms, 'frontier': frontier})
        for budget in plan['budgets']:
            base = {r['task']: r for r in arms[('bm25', budget)]}
            for method in plan['methods']:
                if method == 'bm25': continue
                wins = []; losses = []; ties = []; missing = []
                for row in arms[(method, budget)]:
                    other = base[row['task']]
                    if not row.get('transport_success') or not other.get('transport_success'): missing.append(row['task'])
                    elif row['task_success'] == other['task_success']: ties.append(row['task'])
                    elif row['task_success']: wins.append(row['task'])
                    else: losses.append(row['task'])
                pairs.append({'corpus': corpus, 'cohort': cohort, 'method': method, 'baseline': 'bm25', 'budget': budget,
                              'wins': wins, 'losses': losses, 'ties': ties, 'missing': missing})
    unique = [e['result'] for e in ledger.values()]; done = [r for r in unique if r['transport_success']]
    accounting = counts(ledger)
    corpus_pairs=corpus_comparisons(live['rows'],args.baseline_corpus)
    summary = {**accounting, 'plan_sha256': live['plan_sha256'], 'local_results_sha256': sha(args.local/'results.json'),
               'reporter_sha256': sha(Path(__file__)), 'audited_answer_observations': audited,
               'completed_unique_requests': len(done),
               'transport_errors': dict(Counter(str(r.get('http_status', r.get('error_type'))) for r in unique if not r['transport_success'])),
               'unique_reported_input_tokens': sum(r['usage']['prompt_tokens'] for r in done),
               'unique_reported_output_tokens': sum(r['usage']['completion_tokens'] for r in done),
               'finish_reasons': dict(Counter(r['raw_response']['choices'][0].get('finish_reason') for r in done)),
               'generative_optimization_calls': 0, 'dollar_cost': None,
               'returned_models': dict(Counter(r['raw_response'].get('model') for r in done)),
               'local_arms': local_arms, 'live_arms': live_arms, 'pairs': pairs, 'common_cohort_frontiers': frontiers,
               'corpus_pairs':corpus_pairs,
               'compilations': local.get('compilations',local.get('builds')), 'encoders': local.get('encoders',{}), 'limitations': plan['limitations'],
               'pending_unique_requests': sorted(set(plan['requests'])-set(ledger)),
               'task_outcomes': [{k: r.get(k) for k in ('corpus','cohort','task','method','budget','request_sha256','task_success','transport_success','selected_tokens')}
                                 for r in live['rows']]}
    write_json(args.output.with_suffix('.json'), summary)
    cohorts=Counter(t['cohort'] for t in plan['dataset']['tasks'])
    lines = ['# '+args.title, '',
             'EMPIRICAL. LOCAL retrieval uses zero generative calls. Answer evidence uses '+plan['settings']['model']+'. '
             +'Source modes: '+accounting['evidence_mode']+'. Identical archived requests may be explicitly replayed without another API call. '
             +'Question cohorts: '+', '.join(f'{name} ({count})' for name,count in cohorts.items())+'. '
             +'All alternatives use the same literal window chunks and budget caps within each corpus. Challengers are experimental sidecars, not product defaults.', '',
             '| Corpus / cohort | Method | Budget | Correct / completed / planned | Mean actual input tokens | Median local ms |',
             '| --- | --- | ---: | ---: | ---: | ---: |']
    for r in sorted(live_arms, key=lambda r: (r['corpus'],r['cohort'],r['method'],r['budget'] or 0)):
        usage='N/A' if r['mean_actual_input_tokens'] is None else f"{r['mean_actual_input_tokens']:.1f}"
        lines.append(f"| {r['corpus']} / {r['cohort']} | {r['method']} | {r['budget'] or 'none'} | {r['successes']} / {r['completed']} / {r['planned']} | {usage} | {r['median_selection_ms']:.2f} |")
    lines += ['', '| Corpus / cohort | Method vs BM25 | Budget | Wins / losses / ties / missing |', '| --- | --- | ---: | --- |']
    for r in pairs:
        lines.append(f"| {r['corpus']} / {r['cohort']} | {r['method']} | {r['budget']} | " + ' / '.join(str(len(r[k])) for k in ('wins','losses','ties','missing'))+' |')
    if corpus_pairs:
        lines += ['', '| Corpus vs baseline / cohort | Method | Budget | Wins / losses / ties / missing | Identical requests |',
                  '| --- | --- | ---: | --- | ---: |']
        for r in corpus_pairs:
            lines.append(f"| {r['corpus']} vs {r['baseline_corpus']} / {r['cohort']} | {r['method']} | {r['budget'] or 'none'} | "
                         +' / '.join(str(len(r[k])) for k in ('wins','losses','ties','missing'))+f" | {len(r['identical_requests'])} |")
    lines += ['', f"{accounting['attempts']} LIVE attempts, {accounting['live_answers']} new answers; "
              f"{accounting['replayed_records']} replayed records including {accounting['replayed_answers']} prior answers. "
              f"{len(done)} unique answer records in total. Usage across LIVE and REPLAY evidence: {summary['unique_reported_input_tokens']:,} input and {summary['unique_reported_output_tokens']:,} output tokens. "
              f"{len(summary['pending_unique_requests'])} unique requests remain unattempted. "
              'Dollar cost is N/A. Full-context and remote-preprocessor answer arms were not run, so no end-to-end savings claim follows.', '',
              'Whole required-span coverage is only a LOCAL diagnostic. The complete LOCAL grid, per-task outcomes, common-cohort frontiers, and index compilation costs are retained in the accompanying JSON. '
              'Frontiers below use only questions completed for every arm; missing transport outcomes are not scored as wrong answers.', '']
    lines += ['- '+s for s in summary['limitations']]
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    columns=min(4,len(frontiers));nrows=(len(frontiers)+columns-1)//columns
    figure, axes = plt.subplots(nrows,columns,figsize=(4*columns,4.5*nrows),squeeze=False)
    flat=list(axes.flat)
    for ax, group in zip(flat, frontiers):
        title_cohort=group['cohort']
        for prefix in ('known_','previous_'):
            while title_cohort.startswith(prefix):title_cohort=title_cohort.removeprefix(prefix)
        title=group['corpus'].replace('_',' ')+'\n'+title_cohort.replace('_',' ')
        if not group['common_tasks']:
            ax.text(.5, .5, 'No tasks completed\nfor every arm', ha='center', va='center', transform=ax.transAxes)
            ax.set_title(title+' (n=0)', fontsize=10)
            ax.set_axis_off()
            continue
        for method in plan['methods']+['none']:
            rows = sorted([r for r in group['all_arms'] if r['method'] == method],key=lambda r:r['mean_actual_input_tokens'])
            ax.plot([r['mean_actual_input_tokens'] for r in rows], [100*r['successes']/r['tasks'] for r in rows], marker='o', label=method)
        ax.set_title(title+f" (n={len(group['common_tasks'])})", fontsize=10)
        ax.set_xlabel('Mean actual provider input tokens'); ax.set_ylim(-5,105); ax.grid(alpha=.2)
        ax.set_ylabel('Exact JSON task success (%)')
        handles,labels=ax.get_legend_handles_labels()
        if handles:ax.legend(handles,labels,fontsize=8)
    for ax in flat[len(frontiers):]:ax.set_axis_off()
    figure.suptitle(accounting['evidence_mode']+' '+plan['settings']['model']+' — common completed cohorts; one observation per unique prompt', fontsize=11)
    figure.tight_layout(); figure.savefig(args.output.with_suffix('.png'),dpi=150); plt.close(figure)
    print({k:summary[k] for k in ('attempts','completed_unique_requests','transport_errors','unique_reported_input_tokens','unique_reported_output_tokens')})
    print(json.dumps(pairs))


if __name__ == '__main__': main()

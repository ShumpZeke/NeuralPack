"""Paired rendering diagnostics; privileged source controls never join a frontier."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from benchmarks.prospective_report import summarize,plot
from benchmarks.prospective_eval import write_json


def pairs(rows,left,right,budget):
    groups={method:{r['task']:r for r in rows if r['method']==method and r['budget']==budget}
            for method in (left,right)}
    common=sorted(groups[left].keys() & groups[right].keys());completed=[];wins=[];losses=[];ties=[]
    for task in common:
        a,b=groups[left][task],groups[right][task]
        if not a.get('transport_success') or not b.get('transport_success'):continue
        completed.append(task)
        if a['task_success']==b['task_success']:ties.append(task)
        elif a['task_success']:wins.append(task)
        else:losses.append(task)
    return {'left':left,'right':right,'budget':budget,'planned_pairs':len(common),
            'completed_pairs':len(completed),'wins':wins,'losses':losses,'ties':ties,
            'missing':sorted(set(common)-set(completed))}


def diagnostic(data):
    standard=summarize(data);rows=data['rows'];planned=data['plan']['observations'];budgets=data['plan']['budgets']
    for task in {r['task'] for r in planned}:
        for budget in budgets:
            pair=[r for r in planned if r['task']==task and r['budget']==budget and r['method'] in ('bm25_labeled','bm25_same_blocks')]
            if len(pair)!=2 or pair[0]['evidence']!=pair[1]['evidence']:
                raise ValueError('rendering arms do not contain identical source')
    comparisons=[pairs(rows,'bm25_labeled','bm25_same_blocks',b) for b in budgets]
    comparisons += [pairs(rows,'bm25_labeled','bm25_windows',b) for b in budgets]
    comparisons += [pairs(rows,'called_definitions','required_definitions',None)]
    per_task=[]
    for task in data['plan']['dataset']['tasks']:
        current=[r for r in rows if r['task']==task['id']]
        def success(method,budget=None):
            row=next(r for r in current if r['method']==method and r['budget']==budget)
            return row['task_success'] if row.get('transport_success') else None
        per_task.append({'task':task['id'],'required_success':success('required_definitions'),
                         'called_success':success('called_definitions'),'full_success':success('full'),
                         'none_success':success('none'),
                         'bm25':{str(b):success('bm25_windows',b) for b in budgets},
                         'labeled':{str(b):success('bm25_labeled',b) for b in budgets},
                         'same_blocks':{str(b):success('bm25_same_blocks',b) for b in budgets},
                         'required_tokens':data['plan']['controls'][task['id']]['required_tokens'],
                         'called_tokens':data['plan']['controls'][task['id']]['called_tokens']})
    actual_models=Counter();reasoning=0
    for row in rows:
        if not row.get('transport_success'):continue
        raw=row.get('raw_response',{});actual_models[raw.get('model','unreported')]+=1
        reasoning+=any(bool(c.get('message',{}).get('reasoning_content')) for c in raw.get('choices',[]))
    return {'standard':standard,'pairs':comparisons,'tasks':per_task,
            'returned_models':dict(actual_models),'responses_with_nonempty_reasoning_field':reasoning,
            'interpretation':[
                'EMPIRICAL diagnostic follow-up, not an independent holdout or a source sufficiency proof',
                'Labeled versus same-block arms isolate source metadata at equal budget caps; actual token usage differs',
                'Labeled versus normal BM25 includes the opportunity cost of headers displacing source blocks',
                'Privileged controls have no context cap and cannot establish a retrieval win',
                'A correct source-control answer identifies potential headroom, not a deployable seed algorithm',
                'Control failures do not prove all necessary evidence was present; external functions and globals can matter',
                'Within-model pairs only; configurations and sampling differ across models',
                'Two workers per model, with overlapping model runs (up to four total requests); endpoint load and local activity are uncontrolled',
                'Missing transport outcomes remain unknown and are never silently counted as answer failures']}


def markdown(models):
    lines=['# Cycle 13: source labels and privileged source controls','',
           'LIVE target-model answers; LOCAL selection makes zero generative calls. '
           'Eight known Click 8.5.0 questions, not new held-out validation. '
           'Every question has 298,931 corpus tokens and 298,846 available compiled tokens (chars/4 estimates).','',
           '| Model | Method | Estimated budget | Correct / completed / planned | Mean actual input tokens |',
           '| --- | --- | ---: | ---: | ---: |']
    for model,report in models.items():
        for arm in report['standard']['arms']:
            usage='N/A' if arm['mean_input_tokens'] is None else f"{arm['mean_input_tokens']:,.1f}"
            lines.append(f"| {model} | {arm['method']} | {arm['budget'] or 'uncapped reference'} | "
                         f"{arm['strict_json_successes']} / {arm['completed']} / {arm['planned']} | {usage} |")
    lines += ['', '| Model | Comparison (left vs right) | Budget | Paired wins / losses / ties | Missing pairs |',
              '| --- | --- | ---: | ---: | ---: |']
    for model,report in models.items():
        for pair in report['pairs']:
            lines.append(f"| {model} | {pair['left']} vs {pair['right']} | {pair['budget'] or 'uncapped reference'} | "
                         f"{len(pair['wins'])} / {len(pair['losses'])} / {len(pair['ties'])} | {len(pair['missing'])} |")
    lines += ['', 'Required and called definitions are privileged diagnostics selected using known source symbols '
              'or instrumented executable tests. Their source text is literal, but they are neither deployable '
              'retrieval competitors nor proven sufficient or minimum context.','',
              'Dollar cost is N/A: endpoint pricing is unverified. There is one target-model request per unique '
              'prompt, with failed transport recorded separately. No remote LLM preprocessing arm was tested.','']
    for model,report in models.items():
        standard=report['standard'];usage=standard['unique_request_usage']
        lines += [f"{model}: {standard['answer_attempts_in_ledger']} attempts; "
                  f"{usage['prompt_tokens']['reported_total']} reported input and "
                  f"{usage['completion_tokens']['reported_total']} output tokens. "
                  f"The common completed retrieval cohort has {len(standard['common_completed_tasks'])} tasks.",'']
    lines += ['- '+line for line in next(iter(models.values()))['interpretation']]
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args();models={}
    for model in ('deepseek','nemotron'):
        data=json.loads((args.run/model/'results.json').read_text())
        if any(r['evidence_mode']=='PENDING' for r in data['rows']):raise ValueError('planned answers still pending')
        models[model]=diagnostic(data)
    output={'evidence_mode':'LIVE','models':models,'reporter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_json(args.output.with_suffix('.json'),output)
    args.output.with_suffix('.md').write_text(markdown(models),encoding='utf-8')
    for name,report in models.items():
        plot(report['standard'],args.output.with_name(args.output.stem+'-'+name+'.png'),
             title_prefix=report['standard']['settings']['model'])
    print({name:{'attempts':r['standard']['answer_attempts_in_ledger'],'pairs':r['pairs']} for name,r in models.items()})


if __name__=='__main__':main()

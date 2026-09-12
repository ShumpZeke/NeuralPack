"""Regrade stored source spans with explicit, validated source namespaces."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics
from types import SimpleNamespace
from benchmarks.repository_eval import source_coverage
from benchmarks.repository_tasks import anchors


def canonical_tasks(tasks,manifest,source,prefix):
    available={item['path']:item for item in manifest}
    if len(available)!=len(manifest):raise ValueError('duplicate source paths')
    for name,item in available.items():
        path=(source/name).resolve()
        if not path.is_relative_to(source.resolve()):raise ValueError('source path escapes the declared collection')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('source hash changed')
    result=deepcopy(tasks);maps=[];seen=set();parsed={}
    for task in result:
        if task['id'] in seen:raise ValueError('duplicate task')
        seen.add(task['id'])
        for requirement in task['required']:
            original=requirement['path']
            name=original if original in available else prefix+original
            if name not in available:raise ValueError('required source is outside the declared namespace')
            path=source/name
            if name not in parsed:parsed[name]=anchors(path)
            if requirement['symbol'] not in parsed[name] or list(parsed[name][requirement['symbol']])!=requirement['span']:
                raise ValueError('required symbol span does not match pinned source')
            requirement['path']=name
            if original!=name:maps.append({'task':task['id'],'original':original,'canonical':name})
    return result,maps


def regrade(report,source,prefix='src/click/'):
    if report['status']!='COMPLETE':raise ValueError('complete selections required')
    result=deepcopy(report)
    result['tasks'],mapping=canonical_tasks(report['tasks'],report['source_manifest'],source,prefix)
    expected={t['id']:t for t in result['tasks']}
    seen=set();changed=0
    # read_text normalizes CR/LF; split only LF so Unicode string characters
    # cannot be mistaken for physical lines by the independent provenance check.
    source_lines={item['path']:(source/item['path']).read_text(encoding='utf-8').split('\n') for item in report['source_manifest']}
    for row in result['rows']:
        identity=(row['policy'],row['method'],row['budget'],row['task'])
        if identity in seen:raise ValueError('duplicate observation')
        seen.add(identity)
        if row['selected_tokens']>row['budget']:raise ValueError('budget exceeded')
        if hashlib.sha256(row['context'].encode()).hexdigest()!=row['context_sha256']:
            raise ValueError('saved context changed')
        snippets=[];block_ids=set()
        for evidence in row['evidence']:
            match=re.fullmatch(r'(.*):(\d+)-(\d+)',evidence['span'])
            if not match or match[1]!=evidence['path'] or evidence['path'] not in source_lines:
                raise ValueError('evidence source span is invalid')
            start,end=int(match[2]),int(match[3]);lines=source_lines[evidence['path']]
            if not 1<=start<=end<=len(lines):raise ValueError('evidence lines are outside source')
            if evidence['block_id'] in block_ids:raise ValueError('duplicate evidence block')
            block_ids.add(evidence['block_id']);snippets.append('\n'.join(lines[start-1:end]))
        if '\n\n'.join(snippets)!=row['context']:raise ValueError('saved context does not match its source spans')
        estimated=max(1,len(row['context'])//4) if snippets else 0
        if estimated!=row['selected_tokens']:raise ValueError('saved token estimate differs from rendered source')
        computed=source_coverage([SimpleNamespace(**e) for e in row['evidence']],expected[row['task']]['required'])
        row['original_coverage']={k:row[k] for k in computed}
        if computed!=row['original_coverage']:changed+=1
        row.update(computed)
    required={(policy,method,budget,task) for policy in ('windows','members') for method in report['methods'] for budget in report['budgets'] for task in expected}
    if seen!=required:raise ValueError('missing or unexpected observation')
    result['coverage_correction']={'explicit_package_prefix':prefix,'path_mappings':mapping,'changed_rows':changed,
                                   'scope':'Only required-source namespaces and derived coverage; saved selections and timing are unchanged'}
    result['report_code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def summary(report):
    groups=[]
    for policy in ('windows','members'):
        for cohort in ('identifier_pairs','previous_behavior_controls'):
            for budget in report['budgets']:
                for method in report['methods']:
                    rows=[r for r in report['rows'] if (r['policy'],r['cohort'],r['budget'],r['method'])==(policy,cohort,budget,method)]
                    baseline={r['task']:r for r in report['rows'] if (r['policy'],r['cohort'],r['budget'],r['method'])==(policy,cohort,budget,'bm25')}
                    groups.append({'policy':policy,'cohort':cohort,'budget':budget,'method':method,'questions':len(rows),
                                   'all_spans_retained':sum(r['all_required_spans'] for r in rows),
                                   'mean_span_fraction':statistics.mean(r['required_span_fraction'] for r in rows),
                                   'wins_vs_bm25':sum(r['all_required_spans'] and not baseline[r['task']]['all_required_spans'] for r in rows),
                                   'losses_vs_bm25':sum(not r['all_required_spans'] and baseline[r['task']]['all_required_spans'] for r in rows),
                                   'median_selection_ms':statistics.median(r['selection_ms'] for r in rows),
                                   'median_rerank_ms':statistics.median(r['rerank_ms'] for r in rows),
                                   'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in rows)})
    return {'evidence_mode':'LOCAL','generative_calls':0,'groups':groups,'coverage_correction':report['coverage_correction'],
            'compilations':report['compilations'],'notes':report['notes']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[1]
    report=json.loads(gzip.decompress(args.input.read_bytes()))
    corrected=regrade(report,args.source or repo/'experiments/runs/packs/cycle12-seeds/source')
    args.output.with_suffix('.json.gz').write_bytes(gzip.compress(json.dumps(corrected).encode(),mtime=0))
    result=summary(corrected)
    args.output.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print({'observations':len(corrected['rows']),'regraded_rows':corrected['coverage_correction']['changed_rows']})
    for policy in ('windows','members'):
        for cohort in ('identifier_pairs','previous_behavior_controls'):
            print(policy,cohort,{method:[g['all_spans_retained'] for g in result['groups'] if g['method']==method and g['policy']==policy and g['cohort']==cohort] for method in report['methods']})


if __name__=='__main__':main()

"""Audit literal sources and compare the corpus challenger without invented accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from benchmarks.api_source_eval import region_counts
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from benchmarks.unit_answer_plan import reconstruct
from npk.pack.compile import _source_lines


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(body):return hashlib.sha256(body).hexdigest()


def build(local,corpus):
    data=read(local/'results.json');assert data['status']=='COMPLETE' and data['generative_calls']==0
    sources={name.removeprefix('source/'):_source_lines(body.decode()) for name,body in manifest_sources(corpus/'source',data['source_manifests']['expanded'],'source').items()}
    inventory=read(corpus/'source-inventory.json');tasks={t['id']:t for t in data['tasks']};cells={}
    for row in data['rows']:
        pieces,context=reconstruct(row,sources);task=tasks[row['task']]
        assert (local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
        coverage=source_coverage(pieces,task['required']) if task['required'] else {'all_required_spans':None}
        assert all(row[k]==value for k,value in coverage.items())
        assert all(row[k]==value for k,value in region_counts(pieces,inventory['docstrings']).items())
        cells.setdefault((row['task'],row['corpus'],row['method'],row['budget']),[]).append(row)
    assert len(data['rows'])==1080 and len(cells)==360
    for row in data['unique']:
        group=cells[row['task'],row['corpus'],row['method'],row['budget']]
        assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
        assert row=={k:v for k,v in group[0].items() if k not in ('trial','latency_ms')}|{'median_ms':statistics.median(r['latency_ms'] for r in group)}
    points=[]
    for cohort in ('known_scenarios','new_scenarios'):
        for condition in ('manuals','expanded'):
            for method in data['methods']:
                for budget in data['budgets']:
                    group=[r for r in data['unique'] if (r['cohort'],r['corpus'],r['method'],r['budget'])==(cohort,condition,method,budget)]
                    scored=[r for r in group if r['all_required_spans'] is not None]
                    points.append({'cohort':cohort,'corpus':condition,'method':method,'budget':budget,'tasks':len(group),
                                   'manual_annotation_tasks':len(scored),'all_manual_annotations_retained':sum(r['all_required_spans'] for r in scored) if scored else None,
                                   'median_ms':statistics.median(r['median_ms'] for r in group),'mean_selected_tokens':statistics.mean(r['selected_tokens'] for r in group),
                                   'mean_api_source_lines':statistics.mean(r['selected_api_source_lines'] for r in group),
                                   'mean_api_docstring_lines':statistics.mean(r['selected_api_docstring_lines'] for r in group),
                                   'embedding_used':sum(r['signals'].get('embedding_used',False) for r in group),
                                   'fallbacks':sum(r['status']=='fallback_required' for r in group)})
    pairs=[]
    for cohort in ('known_scenarios','new_scenarios'):
        for method in data['methods']:
            for budget in data['budgets']:
                selected=[r for r in data['unique'] if (r['cohort'],r['method'],r['budget'])==(cohort,method,budget)]
                base={r['task']:r for r in selected if r['corpus']=='manuals'}
                pair={'cohort':cohort,'method':method,'budget':budget,'manual_annotation_wins':[],'manual_annotation_losses':[],'manual_annotation_ties':[],'unannotated':[],
                      'identical_contexts':0}
                for after in (r for r in selected if r['corpus']=='expanded'):
                    before=base[after['task']];pair['identical_contexts']+=before['context_sha256']==after['context_sha256']
                    label='unannotated' if after['all_required_spans'] is None else 'manual_annotation_ties' if after['all_required_spans']==before['all_required_spans'] else 'manual_annotation_wins' if after['all_required_spans'] else 'manual_annotation_losses'
                    pair[label].append(after['task'])
                pairs.append(pair)
    return {'status':'AUDITED_LOCAL','evidence_mode':'LOCAL','generative_calls':0,'production_change':None,
            'source_selections_reconstructed':len(data['rows']),'unique_cells':len(cells),'points':points,'paired_corpus_changes':pairs,
            'builds':data['builds'],'corpora':data['corpora'],'local_results_sha256':sha((local/'results.json').read_bytes()),
            'reporter_sha256':sha(Path(__file__).read_bytes()),'answer_quality':None,'cost_usd':None,'net_savings_usd':None,'break_even_requests':None,
            'limitations':data['limitations']+['Existing manual annotations do not recognize equivalent new code/docstring evidence; they cannot determine corpus superiority',
                                            'Line counts measure selected source provenance, not answer sufficiency or a token-efficiency ratio']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('local','corpus','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=build(a.local,a.corpus);write_json(a.output,result)
    print({'reconstructed':result['source_selections_reconstructed'],'points':result['points']},flush=True)


if __name__=='__main__':main()

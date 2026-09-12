"""Report measured end-to-end costs; never substitute seal-only speedups."""
import argparse
import gzip
import json
import math
from pathlib import Path
import statistics


def summarize(report):
    if report['status']!='COMPLETE' or report['evidence_differences']:
        raise ValueError('complete, equivalent paired results required')
    groups=[]
    for config in ('windows','members','hybrid'):
        sides={arm:[r for r in report['rows'] if r['arm']==arm and r['config']==config]
               for arm in ('champion','candidate')}
        assert len(sides['champion'])==len(sides['candidate'])>0
        med=lambda arm,key:statistics.median(r[key] for r in sides[arm])
        item={'config':config,'trials_per_arm':len(sides['champion']),
              'metrics':{key:{arm:med(arm,key) for arm in sides} for key in
                         ('compile_ms','verify_ms','noop_ms','warm_median_ms','disk_bytes')},'updates':[]}
        for op in ('small_file','large_file','one_percent','ten_percent','delete','rename'):
            values={arm:[next(u for u in r['updates'] if u['operation']==op) for r in rows] for arm,rows in sides.items()}
            times={arm:statistics.median(u['update_ms'] for u in updates) for arm,updates in values.items()}
            delta=med('candidate','compile_ms')-med('champion','compile_ms')
            saving=times['champion']-times['candidate']
            stats=values['candidate'][0]['stats']
            item['updates'].append({'operation':op,'median_ms':times,'speedup_ratio_of_medians':times['champion']/times['candidate'],
                                    'paired_speedup_ratios':[next(u for u in r['updates'] if u['operation']==op)['update_ms']/
                                                            next(u for u in next(c for c in sides['candidate'] if c['trial']==r['trial'])['updates'] if u['operation']==op)['update_ms']
                                                            for r in sides['champion']],
                                    'amortizing_updates_compile_wall_time_only':math.ceil(max(0,delta)/saving) if saving>0 else None,
                                    'candidate_file_hashes':stats['integrity_files_hashed'],
                                    'candidate_file_hashes_reused':stats['integrity_files_reused'],
                                    'median_seal_ms':{arm:statistics.median(u['stages_ms']['_seal'] for u in updates) for arm,updates in values.items()}})
        groups.append(item)
    return {'evidence_mode':'LOCAL','generative_calls':0,'groups':groups,
            'initial_and_updated_evidence_comparisons':sum(len(r['first_sweep'])+sum(len(u['evidence']) for u in r['updates']) for r in report['rows'])//2,
            'differences':0,'dollar_break_even':None,'query_break_even':None,
            'limitations':report['limitations']+['Amortization is compile/update wall time only; no hardware dollars, target model savings or full verification after each update included']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raw=gzip.decompress(args.input.read_bytes()) if args.input.suffix=='.gz' else args.input.read_bytes()
    report=json.loads(raw);summary=summarize(report)
    args.output.with_suffix('.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    lines=['# Cycle 11 — Incremental integrity costs','',
           'LOCAL paired measurements on 105 public Click source, documentation and test files, with approximately 300K available tokens per question. No generative model calls.',
           '',f"Compared against `{report['champion_commit']}`. This is the FIRST version-5 candidate, before the later single-transaction compilation fix. Retrieval algorithms are unchanged; see cycle11-summary.json for the final build and additional measurements.",'',
           f"All {summary['initial_and_updated_evidence_comparisons']:,} paired selections had identical context text hashes, spans and estimated token counts. Updated artifacts also matched independent fresh builds. This is selection equivalence, not new answer-quality validation.",'']
    for group in summary['groups']:
        lines.extend([f"## {group['config']} ({group['trials_per_arm']} trials per arm)",'',
                      '| Operation | v4 median ms | v5 median ms | Ratio | Files hashed / reused |','| --- | ---: | ---: | ---: | ---: |'])
        for update in group['updates']:
            a,b=update['median_ms']['champion'],update['median_ms']['candidate']
            lines.append(f"| {update['operation']} | {a:.1f} | {b:.1f} | {a/b:.2f}× | {update['candidate_file_hashes']} / {update['candidate_file_hashes_reused']} |")
        lines.extend(['','| Other cost | v4 | v5 |','| --- | ---: | ---: |'])
        for name,values in group['metrics'].items():lines.append(f"| {name} | {values['champion']:.1f} | {values['candidate']:.1f} |")
        lines.append('')
    lines.extend(['## Limits','',*['- '+s for s in summary['limitations']],'',
                  'A longer read transaction can delay a writer in DELETE journal mode. A busy timeout remains possible; writes must be serialized and failed updates retried explicitly. Older packs require recompilation, not an in-place digest relabel.',
                  '', 'The product verdict remains **PIVOT REQUIRED**: faster compilation infrastructure does not establish better answers than competent retrieval.'])
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    group=summary['groups'][0]
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    labels=['Small file','Large file','1% files','10% files','Delete','Rename']
    for offset,arm,label,color in ((-.18,'champion','v4','#718096'),(.18,'candidate','v5 first candidate','#007f86')):
        axes[0].bar([i+offset for i in range(6)],[r['median_ms'][arm] for r in group['updates']],.36,label=label,color=color)
        keys=['compile_ms','verify_ms','noop_ms','warm_median_ms']
        axes[1].bar([i+offset for i in range(4)],[group['metrics'][k][arm] for k in keys],.36,label=label,color=color)
    axes[0].set(xticks=range(6),xticklabels=labels,ylabel='Wall time (ms)',title='Whole update, median of 3 trials')
    axes[1].set(xticks=range(4),xticklabels=['Compile','Full verify','No change','Warm query'],yscale='log',ylabel='Wall time (ms, log scale)',title='Other costs, same default BM25')
    axes[0].tick_params(axis='x',rotation=25);axes[0].legend()
    fig.suptitle('Click 8.5.0 · 105 files · ≈300K available tokens\nLOCAL costs only; no answer-quality or dollar claim',fontsize=12)
    fig.savefig(args.output.with_suffix('.png'),dpi=150);plt.close(fig)


if __name__=='__main__':main()

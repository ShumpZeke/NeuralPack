"""Plot source-retention curves; neither axis is target-answer accuracy."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    out=Path(__file__).resolve().parents[1]/'experiments/results'
    data=json.loads((out/'cycle26-summary.json').read_text(encoding='utf-8'))
    fig,axes=plt.subplots(1,3,figsize=(14,4.8))
    methods={'champion':'Current lexical','normalized_index':'Normalized FTS','canonical_all':'Spelling dictionary',
             'canonical_marked':'Marked dictionary','query_variants':'Query variants (no index)','hybrid':'Local MiniLM hybrid'}
    for ax,cohort,title in zip(axes,('known_spelling','new_spelling','known_behavior'),
                              ('96 known spelling probes','96 new spelling probes','10 known behavior scenarios')):
        for method,label in methods.items():
            points=sorted((p for p in data['curve'] if p['cohort']==cohort and p['method']==method),key=lambda p:p['budget'])
            ax.plot([p['mean_selected_tokens'] for p in points],[100*p['metric_pass']/p['tasks'] for p in points],
                    marker='x' if method=='canonical_marked' else 'o',linestyle='--' if method=='canonical_marked' else '-',label=label,alpha=.85)
        ax.set(title=title,xlabel='Mean selected tokens (chars/4 estimate)',ylim=(-3,103),xlim=(0,4200))
        ax.set_ylabel('Literal source identifier present (%)' if cohort!='known_behavior' else 'All annotated source passages retained (%)')
        ax.grid(alpha=.2)
    fig.suptitle('LOCAL evidence diagnostics — 1,024 / 4,096 token caps, same blocks and assembly')
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=3,frameon=False)
    fig.text(.5,.14,'Three shuffled repeats per cell; repeated deterministic results are not independent tasks. No answer-quality measurement.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.17,1,.94));fig.savefig(out/'cycle26-source-curves.png',dpi=150);plt.close(fig)


if __name__=='__main__':main()

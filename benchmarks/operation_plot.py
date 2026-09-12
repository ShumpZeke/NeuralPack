"""Plot local source diagnostics and strictly paired target-answer outcomes."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    out=Path(__file__).resolve().parents[1]/'experiments/results';data=json.loads((out/'cycle27-operation-answers.json').read_text())
    names={'bm25':'BM25','clause_rrf':'Clause RRF','clause_balanced':'Balanced clauses','question_only':'Question only',
           'operations_only':'Operations only','operations_rrf':'Combined views','hybrid':'Hybrid','question_hybrid':'Focused hybrid'}
    fig,axes=plt.subplots(2,2,figsize=(12,8))
    for ax,(cohort,layout) in zip(axes.flat,[(c,l) for c in ('known_scenarios','new_scenarios') for l in ('original','padded')]):
        for method,label in names.items():
            points=sorted((p for p in data['local_curve'] if (p['cohort'],p['layout'],p['method'])==(cohort,layout,method)),key=lambda p:p['budget'])
            ax.plot([p['mean_selected_tokens'] for p in points],[p['all_required_passages'] for p in points],marker='o',label=label,alpha=.8)
        ax.set(title=cohort.replace('_',' ')+' / '+layout,xlabel='Mean selected tokens (chars/4 estimate)',ylabel='All annotated passages retained / 10',ylim=(-.3,10.3))
        ax.grid(alpha=.2)
    fig.suptitle('LOCAL diagnostics: identical blocks and assembly, 1K / 2K / 4K caps')
    handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=4,frameon=False)
    fig.tight_layout(rect=(0,.09,1,.96));fig.savefig(out/'cycle27-source-curves.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for ax,cohort in zip(axes,('known_scenarios','new_scenarios')):
        rows=[r for r in data['paired_answers_vs_bm25'] if r['cohort']==cohort]
        labels=[names[r['candidate']]+' '+str(r['budget']) for r in rows];ys=list(range(len(rows)))
        ax.barh(ys,[len(r['wins']) for r in rows],color='#29745c',label='Wins vs BM25')
        ax.barh(ys,[-len(r['losses']) for r in rows],color='#aa4949',label='Losses vs BM25')
        ax.set_yticks(ys,labels);ax.invert_yaxis();ax.axvline(0,color='black',linewidth=.6)
        ax.set(xlim=(-4,6),xlabel='Paired strict JSON task outcomes',title=cohort.replace('_',' '))
        for y,row in zip(ys,rows):ax.text(5.8,y,f"{len(row['missing'])} missing",va='center',ha='right',fontsize=8)
        ax.grid(axis='x',alpha=.2)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=2,frameon=False)
    fig.suptitle('Target answers: LIVE + explicit REPLAY; missing pairs are excluded')
    fig.tight_layout(rect=(0,.06,1,.94));fig.savefig(out/'cycle27-answer-pairs.png',dpi=150);plt.close(fig)


if __name__=='__main__':main()

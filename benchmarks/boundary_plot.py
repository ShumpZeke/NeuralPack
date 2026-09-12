"""Plot the complete LOCAL passage-coverage sweep, including zero-hit points."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.results.read_text(encoding='utf-8'));assert data['status']=='COMPLETE'
    names={'baseline':'Existing splitter','anchor_4800':'Anchors 4,800 chars',
           'anchor_4800_min512':'Anchors 4,800 / min 512','anchor_2048':'Anchors 2,048 chars',
           'fixed_4800':'Fixed 4,800 chars','fixed_2048':'Fixed 2,048 chars'}
    fig,axes=plt.subplots(1,2,figsize=(12,5.2),sharey=True)
    for method,label in names.items():
        rows=sorted((r for r in data['summary'] if r['method']==method),key=lambda r:r['budget'])
        assert len(rows)==4 and all(r['tasks']==10 for r in rows)
        for ax,key in zip(axes,('budget','mean_selected_tokens'),strict=True):
            ax.plot([r[key] for r in rows],[r['all_required_spans'] for r in rows],marker='o',linewidth=1.6,label=label)
    axes[0].set_xlabel('Matched evidence budget (estimated tokens)')
    axes[1].set_xlabel('Mean selected evidence (estimated tokens)')
    axes[0].set_ylabel('Tasks retaining every specified passage / 10')
    axes[0].set_title('Equal budget caps');axes[1].set_title('Actual selected context')
    for ax in axes:
        ax.set_ylim(-.2,10.2);ax.set_yticks(range(0,11,2));ax.grid(alpha=.2)
    fig.suptitle('LOCAL source-passage coverage — not answer accuracy',fontsize=14)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=3,fontsize=9)
    fig.tight_layout(rect=(0,.15,1,.92));a.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(a.output,dpi=160);plt.close(fig)


if __name__=='__main__':main()

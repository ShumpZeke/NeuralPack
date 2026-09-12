"""Standalone plots retaining zero-hit, format-failure and missing outcomes."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local',type=Path,required=True)
    p.add_argument('--answers',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    local=read(a.local);answers=read(a.answers);assert local['status']==answers['status']=='COMPLETE'
    names={'public_bm25':'Public BM25','shared_bm25':'Shared BM25','micro_seed':'Micro units',
           'micro_neighbor1':'Micro + 1 neighbor','micro_neighbor2':'Micro + 2 neighbors',
           'micro_paragraph':'Micro + paragraph','public_hybrid':'Public hybrid','shared_hybrid':'Shared hybrid'}
    fig,axes=plt.subplots(1,2,figsize=(12,5.5))
    for method,label in names.items():
        rows=sorted((r for r in local['summary'] if r['method']==method),key=lambda r:r['budget'])
        assert len(rows)==4 and all(r['tasks']==10 for r in rows)
        axes[0].plot([r['budget'] for r in rows],[r['all_required_spans'] for r in rows],marker='o',label=label)
        axes[1].plot([r['budget'] for r in rows],[r['median_selection_ms'] for r in rows],marker='o',label=label)
    for ax in axes:ax.set_xlabel('Matched evidence cap (estimated tokens)');ax.grid(alpha=.2)
    axes[0].set_ylim(-.2,10.2);axes[0].set_ylabel('Tasks retaining all specified passages / 10')
    axes[1].set_ylabel('Median local selection latency (ms)')
    fig.suptitle('LOCAL: 528K-token available source per task — passage checks are not answer accuracy')
    h,l=axes[0].get_legend_handles_labels();fig.legend(h,l,loc='lower center',ncol=4,fontsize=8)
    fig.tight_layout(rect=(0,.14,1,.93));a.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(str(a.output)+'-local.png',dpi=160);plt.close(fig)
    arms=answers['arms'];fig,ax=plt.subplots(figsize=(11,6));positions=list(range(len(arms)))
    segments=[('passed','Correct JSON + values','#168577'),('wrong','Valid JSON, wrong values','#c66565'),
              ('parse_errors','Invalid JSON','#e4ad4b'),('missing','Service failure','#a4adb9')]
    left=[0]*len(arms)
    for key,label,color in segments:
        counts=[r['passed'] if key=='passed' else r['parse_errors'] if key=='parse_errors' else
                r['planned']-r['completed'] if key=='missing' else r['completed']-r['passed']-r['parse_errors'] for r in arms]
        ax.barh(positions,counts,left=left,label=label,color=color)
        for i,count in enumerate(counts):
            if count:ax.text(left[i]+count/2,i,str(count),ha='center',va='center',fontsize=10)
        left=[n+c for n,c in zip(left,counts,strict=True)]
    assert all(n==10 for n in left)
    ax.set_yticks(positions,[names.get(r['method'],r['method'].title()+' control')+
                           (f" / {r['budget']:,} cap" if r['budget'] else '') for r in arms]);ax.invert_yaxis()
    ax.set_xlim(0,10);ax.set_xlabel('All 10 planned tasks per arm; service failures remain missing')
    ax.set_title('LIVE: exact executable-scenario answers\n78 unique calls; 61 responses; no generative optimizer',pad=12)
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.16),ncol=2,fontsize=9)
    fig.tight_layout(rect=(0,.09,1,1));fig.savefig(str(a.output)+'-answers.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()

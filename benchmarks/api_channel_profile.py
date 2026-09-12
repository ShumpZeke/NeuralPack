"""Attribute measured retrieval costs without changing rankings or sending answers."""
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import random
import statistics
import time
from unittest.mock import patch
from benchmarks.prospective_eval import write_json
from npk.pack.format import open_pack,read_manifest
from npk.pack.select import _lexical_channel,_symbol_channel,_embedding_channel


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('New profile result required')
    data=json.loads((a.local/'results.json').read_text());tasks=[data['tasks'][i] for i in (0,10,20)]
    rows=[];profiles=[];rng=random.Random(2833)
    with patch('socket.socket.connect',side_effect=AssertionError('LOCAL profile attempted network')):
        import torch
        from npk.context.embedding import get_backend
        torch.set_num_threads(2);backend=get_backend();assert backend.available()
        for trial in range(3):
            order=[(c,t) for c in ('manuals','expanded') for t in tasks];rng.shuffle(order)
            for corpus,task in order:
                with open_pack(a.local/(corpus+'_semantic.npk')) as con:
                    manifest=read_manifest(con);query=task['question']
                    channels={'lexical':lambda:_lexical_channel(con,query,60),'symbol':lambda:_symbol_channel(con,query,60),
                              'embedding':lambda:_embedding_channel(con,query,60,manifest)}
                    for name,call in channels.items():
                        start=time.perf_counter_ns();result=call();elapsed=(time.perf_counter_ns()-start)/1e6
                        digest=hashlib.sha256(json.dumps(result).encode()).hexdigest()
                        rows.append({'corpus':corpus,'task':task['id'],'channel':name,'trial':trial,'wall_ms':elapsed,'result_sha256':digest})
        with open_pack(a.local/'expanded_semantic.npk') as con:
            manifest=read_manifest(con);query=tasks[-1]['question']
            for name,call in (('symbol',lambda:_symbol_channel(con,query,60)),('embedding',lambda:_embedding_channel(con,query,60,manifest))):
                profiler=cProfile.Profile();profiler.enable();call();profiler.disable();stats=pstats.Stats(profiler)
                functions=[]
                for (file,line,function),(primitive,total,self_seconds,cumulative,callers) in stats.stats.items():
                    functions.append({'file':file,'line':line,'function':function,'calls':total,'self_seconds':self_seconds,'cumulative_seconds':cumulative})
                profiles.append({'channel':name,'functions':sorted(functions,key=lambda r:-r['cumulative_seconds'])[:25]})
    points=[]
    for corpus in ('manuals','expanded'):
        for channel in ('lexical','symbol','embedding'):
            medians=[]
            for task in tasks:
                group=[r for r in rows if (r['corpus'],r['channel'],r['task'])==(corpus,channel,task['id'])]
                assert len(group)==3 and len({r['result_sha256'] for r in group})==1
                medians.append(statistics.median(r['wall_ms'] for r in group))
            points.append({'corpus':corpus,'channel':channel,'median_of_task_medians_ms':statistics.median(medians)})
    result={'evidence_mode':'LOCAL','generative_calls':0,'rows':rows,'summary':points,'profiler_diagnostics':profiles,
            'tasks':[t['id'] for t in tasks],'torch_threads':2,'local_results_sha256':hashlib.sha256((a.local/'results.json').read_bytes()).hexdigest(),
            'limitations':['Three fixed diagnostic scenarios, not the full query benchmark','Uncontrolled host load; no overlapping agent tests, benchmarks or LIVE requests',
                           'Profiler timings include instrumentation overhead and are not substituted for unprofiled channel medians']}
    write_json(a.output,result);print(points,flush=True)
    print([{'channel':r['channel'],'top':r['functions'][:8]} for r in profiles],flush=True)


if __name__=='__main__':main()

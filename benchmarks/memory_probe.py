"""Reproduce the exploratory cycle-16 fresh-process memory probe; no network."""
import json
import subprocess
import sys
from pathlib import Path

code = '''import json,os,sys,time,psutil,socket
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
def denied(*a,**k): raise RuntimeError('network prohibited')
socket.socket.connect=denied
p=psutil.Process(); before=p.memory_info().rss; start=time.perf_counter()
if sys.argv[1]=='pack':
 from npk.pack import PackSelector
 PackSelector('experiments/runs/packs/cycle14-seeds-v1/expanded.npk').select('How are inherited defaults overridden by section options?',budget_tokens=2048)
else:
 if sys.argv[1]=='legacy_disabled':os.environ['NPK_ENABLE_EMBEDDINGS']='0'
 from npk.planner import ContextExecutionPlanner
 from pathlib import Path
 text=Path('experiments/runs/packs/cycle16-policy-final/context-2000.txt').read_text(encoding='utf-8')
 _,plan=ContextExecutionPlanner().plan_and_optimize([{'role':'user','content':text},{'role':'user','content':'How are inherited defaults overridden by section options?'}])
print(json.dumps({'case':sys.argv[1],'rss_before':before,'rss_after':p.memory_info().rss,'elapsed_ms':(time.perf_counter()-start)*1000,'torch_loaded':'torch' in sys.modules,'transformers_loaded':'transformers' in sys.modules}))'''

if __name__ == '__main__':
    output = Path(sys.argv[1])
    if output.exists(): raise ValueError('Use a new report path')
    rows = []
    for trial in range(3):
        for case in ('pack', 'legacy', 'legacy_disabled'):
            result = subprocess.run([sys.executable, '-c', code, case], check=True, capture_output=True, text=True)
            row = json.loads(result.stdout); row['trial'] = trial; rows.append(row)
    output.write_text(json.dumps({'evidence_mode': 'LOCAL', 'rows': rows,
                                 'limits': ['Fresh process per case; no peak memory or allocation attribution',
                                            'Different APIs, not answer-quality comparisons',
                                            'Network forbidden; disabled encoder is existing configuration, not code change']}, indent=2))

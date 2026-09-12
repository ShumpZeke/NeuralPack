"""Reconstruct LOCAL clause evidence and freeze paired target-model requests."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from benchmarks.modern_seed_plan import SYSTEM,tokens
from benchmarks.prospective_eval import request_key,write_json
from npk.pack.format import open_pack,load_blocks

METHODS=('bm25','flat_fields','clause_balanced')
BUDGETS=(2048,8192)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(body):return hashlib.sha256(body).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--local',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];root=a.output.resolve()
    if root.exists():raise ValueError('new answer run required')
    data=json.loads((a.local/'results.json').read_text());assert data['status']=='COMPLETE'
    code={}
    for path,expected in data['code_sha256'].items():
        body=(repo/path).read_bytes();assert digest(body)==expected
        code[path]={'sha256':expected,'text':body.decode()}
    code[Path(__file__).relative_to(repo).as_posix()]={'sha256':sha(Path(__file__)),'text':Path(__file__).read_bytes().decode()}
    sources={}
    for item in data['source_manifest']:
        body=(a.corpus/'expanded-source'/item['path']).read_bytes();assert digest(body)==item['sha256']
        sources[item['path']]=body.decode().replace('\r\n','\n').replace('\r','\n').split('\n')
    seen=set()
    for row in data['rows']:
        identity=(row['corpus'],row['task'],row['method'],row['budget'])
        assert identity not in seen;seen.add(identity)
        pieces=[]
        for e in row['evidence']:
            match=re.fullmatch(re.escape(e['path'])+r':(\d+)-(\d+)',e['span']);assert match
            start,end=map(int,match.groups());lines=sources[e['path']]
            assert 1<=start<=end<=len(lines);pieces.append('\n'.join(lines[start-1:end]))
        text='\n\n'.join(pieces);assert digest(text.encode())==row['context_sha256']
        assert text.encode()==(a.local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert tokens(text)==row['selected_tokens']<=row['budget']
        assert text or row['seed_failed']
    expected={('expanded',t['id'],method,budget) for t in data['tasks'] for method in data['methods'] for budget in data['budgets']}
    assert seen==expected
    with open_pack(a.corpus/'expanded.npk') as con:full='\n\n'.join(b.text for b in load_blocks(con))
    assert tokens(full)==data['available_tokens']
    root.mkdir(parents=True);reports=[]
    configs={
        'nemotron':{'model':'nvidia/nemotron-3-super-120b-a12b','temperature':1.0,'top_p':.95,
                    'chat_template_kwargs':{'enable_thinking':False},'reasoning_effort':None},
        'deepseek':{'model':'deepseek-ai/deepseek-v4-flash-0731','temperature':0,'reasoning_effort':'none'},
    }
    for model,settings in configs.items():
        settings={**settings,'system_prompt':SYSTEM,'max_output_tokens':2048,'timeout_seconds':90}
        folder=root/model;folder.mkdir();contexts=folder/'contexts';contexts.mkdir();observations=[];requests={}
        for i,task in enumerate(data['tasks']):
            selected=[dict(r) for r in data['rows'] if r['task']==task['id'] and r['method'] in METHODS and r['budget'] in BUDGETS]
            assert len(selected)==len(METHODS)*len(BUDGETS)
            selected.append({'corpus':'expanded','task':task['id'],'cohort':task['cohort'],'method':'none',
                             'budget':None,'context_sha256':digest(b''),'selected_tokens':0,'selection_ms':0,
                             'seed_failed':False,'evidence':[]})
            shift=i%len(selected)
            for row in selected[shift:]+selected[:shift]:
                context='' if row['method']=='none' else (a.local/'contexts'/(row['context_sha256']+'.txt')).read_bytes().decode()
                (contexts/(row['context_sha256']+'.txt')).write_bytes(context.encode())
                key=request_key(settings,task['question'],context)
                row.update(request_sha256=key,available_tokens=tokens(full),corpus_tokens=data['corpus_tokens'],
                           selected_prompt_tokens_estimate=tokens(SYSTEM+f"SOURCE\n{context}\n\nQUESTION\n{task['question']}"),
                           baseline_prompt_tokens_estimate=tokens(SYSTEM+f"SOURCE\n{full}\n\nQUESTION\n{task['question']}"))
                if row['seed_failed']:row['status']='SELECTION_FAILED'
                else:requests.setdefault(key,{'question':task['question'],'context_sha256':row['context_sha256']})
                observations.append(row)
        plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','dataset':{'tasks':data['tasks']},
              'settings':settings,'methods':METHODS,'budgets':BUDGETS,'source_manifest':data['source_manifest'],
              'parent_results_sha256':sha(a.local/'results.json'),'code_sha256':{k:v['sha256'] for k,v in code.items()},
              'observations':observations,'requests':requests,
              'limitations':[*data['limitations'],
                             'Methods chosen after LOCAL inspection, before any LIVE answers; balanced clauses showed limited partial-coverage gains on older compositions',
                             'New eight cases are developer-authored, not independently sealed; old 28 cases are explicit controls',
                             'One answer per unique prompt/model; duplicate prompts share responses and are not independent replications',
                             'No full-context or remote-preprocessor answer arm; full prompt counts are reference estimates only',
                             'Two model configurations have different sampling settings; compare paired methods within each model',
                             'Endpoint load, caching and model nondeterminism uncontrolled; no verified dollar price and no retries'],
              'research_sources':['https://www.microsoft.com/en-us/research/publication/information-retrieval-with-verbose-queries/']}
        write_json(folder/'plan.json',plan);(folder/'plan.sha256').write_text(sha(folder/'plan.json'))
        reports.append({'model':model,'plan_sha256':sha(folder/'plan.json'),'observations':len(observations),'unique_requests':len(requests)})
    archive=root/'preparation-sources.json.gz';archive.write_bytes(gzip.compress(json.dumps(code).encode(),mtime=0))
    result={'evidence_mode':'LOCAL','all_contexts_reconstructed':len(seen),'generative_calls':0,
            'reports':reports,'preparation_sources_sha256':sha(archive)}
    write_json(root/'preflight.json',result);print(result)


if __name__=='__main__':main()

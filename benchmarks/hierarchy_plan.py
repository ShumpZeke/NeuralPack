"""Freeze matched-budget hierarchy prompts for two target-model configurations."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from benchmarks.prospective_eval import request_key,write_json
from benchmarks.modern_seed_plan import SYSTEM,tokens
from npk.pack.format import open_pack,load_blocks

METHODS=('bm25','flat_fields','document_gate4','document_escape4')
BUDGETS=(2048,8192)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(raw):return hashlib.sha256(raw).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();repo=Path(__file__).resolve().parents[1];root=args.output.resolve()
    if root.exists():raise ValueError('new frozen run required')
    data=json.loads((args.parent/'results.json').read_text());assert data['status']=='COMPLETE'
    sources={};code={}
    for item in data['source_manifest']:
        body=(args.corpus/'expanded-source'/item['path']).read_bytes();assert digest(body)==item['sha256']
        sources[item['path']]=body.decode().replace('\r\n','\n').replace('\r','\n').split('\n')
    for name,value in data['code_sha256'].items():
        body=(repo/name).read_bytes();assert digest(body)==value
        code[name]={'sha256':value,'text':body.decode()}
    code[Path(__file__).relative_to(repo).as_posix()]={'sha256':sha(Path(__file__)),'text':Path(__file__).read_bytes().decode()}
    for row in data['rows']:
        pieces=[]
        for e in row['evidence']:
            match=re.fullmatch(re.escape(e['path'])+r':(\d+)-(\d+)',e['span']);assert match
            start,end=map(int,match.groups());assert 1<=start<=end<=len(sources[e['path']])
            pieces.append('\n'.join(sources[e['path']][start-1:end]))
        text='\n\n'.join(pieces)
        assert digest(text.encode())==row['context_sha256']
        assert text.encode()==(args.parent/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert tokens(text)==row['selected_tokens']<=row['budget']
        assert text or row['seed_failed']
    with open_pack(args.corpus/'expanded.npk') as con:full='\n\n'.join(b.text for b in load_blocks(con))
    corpus_tokens=tokens('\n\n'.join('\n'.join(lines) for lines in sources.values()))
    root.mkdir(parents=True);reports=[]
    configs={
        'nemotron':{'model':'nvidia/nemotron-3-super-120b-a12b','temperature':1.0,'top_p':.95,
                    'chat_template_kwargs':{'enable_thinking':False},'reasoning_effort':None},
        'deepseek':{'model':'deepseek-ai/deepseek-v4-flash-0731','temperature':0,'reasoning_effort':'none'},
    }
    for model,settings in configs.items():
        settings={**settings,'system_prompt':SYSTEM,'max_output_tokens':2048,'timeout_seconds':90}
        folder=root/model;folder.mkdir();contexts=folder/'contexts';contexts.mkdir();rows=[];requests={}
        for i,task in enumerate(data['tasks']):
            selected=[dict(r) for r in data['rows'] if r['corpus']=='expanded' and r['task']==task['id']
                      and r['method'] in METHODS and r['budget'] in BUDGETS]
            selected.append({'corpus':'expanded','task':task['id'],'cohort':task['cohort'],'method':'none',
                             'budget':None,'context_sha256':digest(b''),'selected_tokens':0,'selection_ms':0,'seed_failed':False,'evidence':[]})
            shift=i%len(selected)
            for row in selected[shift:]+selected[:shift]:
                context='' if row['method']=='none' else (args.parent/'contexts'/(row['context_sha256']+'.txt')).read_bytes().decode()
                (contexts/(row['context_sha256']+'.txt')).write_bytes(context.encode())
                key=request_key(settings,task['question'],context)
                row.update(request_sha256=key,available_tokens=tokens(full),corpus_tokens=corpus_tokens,
                           selected_prompt_tokens_estimate=tokens(SYSTEM+f"SOURCE\n{context}\n\nQUESTION\n{task['question']}"),
                           baseline_prompt_tokens_estimate=tokens(SYSTEM+f"SOURCE\n{full}\n\nQUESTION\n{task['question']}"))
                if row['seed_failed']:row['status']='SELECTION_FAILED'
                else:requests.setdefault(key,{'question':task['question'],'context_sha256':row['context_sha256']})
                rows.append(row)
        plan={'created_utc':datetime.now(timezone.utc).isoformat(),'evidence_mode':'LOCAL','dataset':{'tasks':data['tasks']},
              'settings':settings,'methods':METHODS,'budgets':BUDGETS,'source_manifest':data['source_manifest'],
              'parent_results_sha256':sha(args.parent/'results.json'),'code_sha256':{k:v['sha256'] for k,v in code.items()},
              'observations':rows,'requests':requests,
              'limitations':[*data['limitations'],
                             'Four methods fixed here before aggregating LOCAL outcome metrics; other methods remain LOCAL diagnostics',
                             'Only expanded corpus receives LIVE answers; out-of-corpus rows receive no live calls',
                             'No full-context or remote-preprocessor answer arm; baseline prompt tokens are estimates only',
                             'One observation per unique prompt/model; identical prompts share answers, not independent replications',
                             'Two model configurations differ in sampling settings; use within-model pairs, not absolute cross-model claims',
                             'Previously inspected questions are controls, not held-out validation; fresh compositions share component behavior',
                             'Dollar cost unverified and N/A; endpoint load/caching uncontrolled; no retries'],
              'research_sources':['https://aclanthology.org/2021.findings-emnlp.19/', 'https://www.sqlite.org/fts5.html']}
        write_json(folder/'plan.json',plan);(folder/'plan.sha256').write_text(sha(folder/'plan.json'))
        reports.append({'model':model,'plan_sha256':sha(folder/'plan.json'),'observations':len(rows),'unique_requests':len(requests)})
    snapshot=root/'preparation-sources.json.gz';snapshot.write_bytes(gzip.compress(json.dumps(code).encode(),mtime=0))
    preflight={'evidence_mode':'LOCAL','all_local_contexts_reconstructed':len(data['rows']),'reports':reports,
               'preparation_sources_sha256':sha(snapshot),'generative_calls':0}
    write_json(root/'preflight.json',preflight);print(json.dumps(preflight))


if __name__=='__main__':main()

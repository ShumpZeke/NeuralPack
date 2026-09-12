"""Regrade completed archived answers; never dispatch or overwrite evidence."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from benchmarks.repository_eval import grade_answer,equal_answer
from benchmarks.prospective_eval import write_json


def audit(paths):
    rows=[]
    for path in paths:
        raw=path.read_bytes();data=json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)
        data=data.get('results',data);tasks=data.get('plan',data)['dataset']['tasks']
        expected={t['id']:t['answer'] for t in tasks};changes=[];completed=0;unique=set()
        for i,row in enumerate(data['rows']):
            if not row.get('transport_success'):continue
            completed+=1;unique.add(row.get('request_sha256',str(i)))
            content=row.get('content');new=grade_answer(content,expected[row['task']])
            try:parsed=json.loads(content);old_success=equal_answer(parsed,expected[row['task']]);old_error=False
            except (ValueError,TypeError):old_success=False;old_error=True
            if (old_success,old_error)!=(new['task_success'],new['parse_error']):
                changes.append({'row':i,'task':row['task'],'method':row.get('method',row.get('arm')),
                                'budget':row.get('budget'),'old_success':old_success,'new_success':new['task_success'],
                                'old_parse_error':old_error,'new_parse_error':new['parse_error']})
        rows.append({'artifact':path.as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),
                     'completed_observations':completed,'distinct_requests':len(unique),'changes':changes})
    return {'evidence_mode':'REPLAY','api_calls':0,'grader_sha256':hashlib.sha256(Path(__file__).with_name('repository_eval.py').read_bytes()).hexdigest(),
            'archives':rows,'limitation':'Completed archived answers only; replay rows and repeated tasks are correlated'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=audit(args.input);write_json(args.output,result);print(json.dumps(result))

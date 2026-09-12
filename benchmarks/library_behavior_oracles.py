"""Declared executable answer tasks on frozen, unmodified public libraries.

Questions are new but source-informed development data, not sealed holdouts.
No LLM is called. Expected answers come from execution, never retrieval labels.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys


TASKS=[
 ('rich_overshoot','rich',
  'A Rich progress task has total=10, completed=15 and no recorded finishing time. '
  'What are its displayed percentage, remaining units and finished flag? '
  'Return JSON keys percentage, remaining, finished.'),
 ('rich_zero_unknown','rich',
  'Two Rich progress tasks have completed=3 and no recorded finishing time. '
  'One has total=0, the other total=None. What are the percentage and remaining units for each? '
  'Return JSON keys zero and unknown, each containing percentage and remaining.'),
 ('rich_stopped_clock','rich',
  'A Rich task starts at clock time -4 and stops at time 0. The supplied clock now reads 25. '
  'What does its elapsed-time property return? For a second task that was never started, '
  'what does that property return? Return JSON keys stopped_elapsed and unstarted_elapsed.'),
 ('rich_terminal_cells','rich',
  'In Rich, truncate a Text containing the two characters 界界 to width 3, first with crop overflow '
  'and then with ellipsis overflow. Neither call requests padding. '
  'Give the exact resulting plain strings, including any spaces, as JSON keys crop and ellipsis.'),
 ('rich_ignore_padding','rich',
  'In Rich, a Text containing X is truncated to width 4 with pad=True. Compare explicit '
  'overflow=ignore with overflow=crop. What exact strings result, including spaces? '
  'Return JSON keys ignore and crop.'),
 ('jinja_missing_falsey','jinja2',
  'In Jinja2, render {{ value|default("M") }} with a missing value, an empty string and integer 0. '
  'Also render {{ value|default("M", true) }} for the empty string and 0. '
  'Return the exact strings as JSON keys missing, empty, zero, boolean_empty, boolean_zero.'),
 ('jinja_chained_missing','jinja2',
  'In Jinja2, user is an empty dict and the template is {{ user.address.city|default("M") }}. '
  'Compare a standard Environment with one configured with undefined=ChainableUndefined. '
  'For each, give either the rendered string or exception class, as JSON keys standard and chainable.'),
 ('jinja_url_forms','jinja2',
  'Using Jinja2 URL encoding, compare the string a/b c with a mapping whose key k has value a/b c. '
  'Give the exact encoded outputs as JSON keys string and mapping. Account for both slash and space handling.'),
 ('jinja_integer_fallback','jinja2',
  'Using Jinja2 integer conversion with default=7 and base=2, what results from string "10", '
  'integer 10, string "12.7" and string "nan"? Return JSON keys binary_string, number, decimal_string, nan_string.'),
 ('jinja_unique_case','jinja2',
  'Jinja2 removes duplicate values from ["Foo", "foo", "BAR", "bar", "Foo"]. '
  'Compare the default case handling with case_sensitive=True, retaining output order and spelling. '
  'Return JSON arrays under keys default and sensitive.'),
 ('jinja_last_generator','jinja2',
  'Apply the Jinja2 last-item filter directly to a generator yielding 1, 2, 3, and separately '
  'to the list [1, 2, 3]. Give the result or exception class as JSON keys generator and list. '
  'Do not insert a conversion before the filter.'),
 ('werkzeug_duplicate_cookie','werkzeug',
  'Werkzeug parses the Cookie header a=1; a=2; b=x with its default container. '
  'What does ordinary key lookup for a return, and what does retrieving all values for a return? '
  'Return JSON keys first and all.'),
 ('werkzeug_filename_windows','werkzeug',
  'On Windows, Werkzeug sanitizes upload filenames 猫 and CON.txt. What exact names result? '
  'Do two calls with the same filename report.pdf automatically produce different names? '
  'Return JSON keys unicode_name, reserved_name and automatically_unique (boolean).'),
 ('werkzeug_mime_charset','werkzeug',
  'Werkzeug constructs content-type strings with charset utf-8 for application/javascript, '
  'application/json, application/problem+json and image/svg+xml. Which exact strings result? '
  'Return JSON keys javascript, json, problem_json and svg.'),
 ('werkzeug_slash_redirect','werkzeug',
  'Werkzeug appends a slash using the WSGI path /user/42 and query string x=1, without an explicit '
  'status override. What status code and Location header does the response object contain before '
  'browser resolution? Return JSON keys status and location.'),
]


def probe(task_id):
    from rich.progress import Task
    from rich.text import Text
    from jinja2 import Environment,ChainableUndefined
    from jinja2.filters import do_int,do_urlencode,sync_do_unique,do_last
    from werkzeug.http import parse_cookie
    from werkzeug.utils import secure_filename,get_content_type,append_slash_redirect
    def task(total,completed):return Task(0,'job',total,completed,lambda:25.0)
    def capture(call):
        try:return call()
        except Exception as exc:return type(exc).__name__
    if task_id=='rich_overshoot':
        t=task(10,15);return {'percentage':t.percentage,'remaining':t.remaining,'finished':t.finished}
    if task_id=='rich_zero_unknown':
        return {k:{'percentage':t.percentage,'remaining':t.remaining} for k,t in
                [('zero',task(0,3)),('unknown',task(None,3))]}
    if task_id=='rich_stopped_clock':
        t=task(10,0);t.start_time=-4;t.stop_time=0
        return {'stopped_elapsed':t.elapsed,'unstarted_elapsed':task(10,0).elapsed}
    if task_id=='rich_terminal_cells':
        out={}
        for mode in ('crop','ellipsis'):
            t=Text('界界');t.truncate(3,overflow=mode);out[mode]=t.plain
        return out
    if task_id=='rich_ignore_padding':
        out={}
        for mode in ('ignore','crop'):
            t=Text('X');t.truncate(4,overflow=mode,pad=True);out[mode]=t.plain
        return out
    if task_id=='jinja_missing_falsey':
        env=Environment();plain=env.from_string('{{ value|default("M") }}')
        boolean=env.from_string('{{ value|default("M", true) }}')
        return {'missing':plain.render(),'empty':plain.render(value=''),'zero':plain.render(value=0),
                'boolean_empty':boolean.render(value=''),'boolean_zero':boolean.render(value=0)}
    if task_id=='jinja_chained_missing':
        template='{{ user.address.city|default("M") }}'
        return {'standard':capture(lambda:Environment().from_string(template).render(user={})),
                'chainable':capture(lambda:Environment(undefined=ChainableUndefined).from_string(template).render(user={}))}
    if task_id=='jinja_url_forms':return {'string':do_urlencode('a/b c'),'mapping':do_urlencode({'k':'a/b c'})}
    if task_id=='jinja_integer_fallback':
        return {key:do_int(value,default=7,base=2) for key,value in
                [('binary_string','10'),('number',10),('decimal_string','12.7'),('nan_string','nan')]}
    if task_id=='jinja_unique_case':
        values=['Foo','foo','BAR','bar','Foo'];env=Environment()
        return {'default':list(sync_do_unique(env,values)),
                'sensitive':list(sync_do_unique(env,values,case_sensitive=True))}
    if task_id=='jinja_last_generator':
        env=Environment();return {'generator':capture(lambda:do_last(env,(x for x in [1,2,3]))),
                                  'list':capture(lambda:do_last(env,[1,2,3]))}
    if task_id=='werkzeug_duplicate_cookie':
        cookies=parse_cookie('a=1; a=2; b=x');return {'first':cookies['a'],'all':cookies.getlist('a')}
    if task_id=='werkzeug_filename_windows':
        assert os.name=='nt','This declared task requires the Windows filename branch'
        return {'unicode_name':secure_filename('猫'),'reserved_name':secure_filename('CON.txt'),
                'automatically_unique':secure_filename('report.pdf')!=secure_filename('report.pdf')}
    if task_id=='werkzeug_mime_charset':
        return {key:get_content_type(value,'utf-8') for key,value in
                [('javascript','application/javascript'),('json','application/json'),
                 ('problem_json','application/problem+json'),('svg','image/svg+xml')]}
    if task_id=='werkzeug_slash_redirect':
        response=append_slash_redirect({'PATH_INFO':'/user/42','QUERY_STRING':'x=1'})
        return {'status':response.status_code,'location':response.headers['Location']}
    raise ValueError('Unknown declared behavior task')


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def declare(snapshot,output):
    if output.exists():raise ValueError('Fresh declaration directory required')
    frozen=read(snapshot/'snapshot.json')
    for name,info in frozen['files'].items():assert sha((snapshot/name).read_bytes())==info['sha256']
    source_root=snapshot/'corpus/test_src'
    files={p.relative_to(source_root).as_posix():sha(p.read_bytes()) for p in sorted(source_root.rglob('*.py'))}
    code=Path(__file__).read_bytes()
    plan={'evidence_mode':'LOCAL','generative_calls':0,'snapshot_sha256':sha((snapshot/'snapshot.json').read_bytes()),
          'probe_sha256':sha(code),'source_sha256':files,'declared_before_oracles':True,
          'tasks':[{'task_id':tid,'library':lib,'query':q} for tid,lib,q in TASKS],
          'limits':['Source-informed development tasks, not a sealed test or generalization proof',
                    'Executable outputs are ground truth for specified inputs and frozen environment only',
                    'Trace lines are provenance, not a proven minimal sufficient context',
                    'Public-library knowledge may be memorized; downstream answer tests require no-context controls']}
    output.mkdir(parents=True);(output/'probe_source.py').write_bytes(code)
    (output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print({'phase':'declared','tasks':len(TASKS),'plan_sha256':sha((output/'plan.json').read_bytes())},flush=True)


def execute(snapshot,output,repeat):
    plan=read(output/'plan.json');destination=output/f'oracles-{repeat}.json'
    if destination.exists():raise ValueError('Do not overwrite a completed oracle run')
    assert plan['probe_sha256']==sha(Path(__file__).read_bytes())
    assert plan['probe_sha256']==sha((output/'probe_source.py').read_bytes())
    assert plan['snapshot_sha256']==sha((snapshot/'snapshot.json').read_bytes())
    root=(snapshot/'corpus/test_src').resolve()
    for name,digest in plan['source_sha256'].items():assert sha((root/name).read_bytes())==digest
    assert all(name not in sys.modules for name in ('rich','jinja2','werkzeug'))
    sys.path.insert(0,str(root))
    import rich,rich.progress,rich.text,jinja2,jinja2.filters,werkzeug,werkzeug.utils,werkzeug.http
    # All target-library imports must come from the pinned source, not the venv.
    origins={}
    for name,module in list(sys.modules.items()):
        if name.split('.')[0] in ('rich','jinja2','werkzeug'):
            path=Path(module.__file__).resolve();assert path.is_relative_to(root)
            origins[name]=path.relative_to(root).as_posix()
    environment={'python':sys.version,'platform':platform.platform(),'os_name':os.name,
        'dependencies':{name:importlib.metadata.version(name) for name in ('MarkupSafe','Pygments')},
        'dependency_note':'Versions of imported third-party dependencies; Markdown rendering is not used',
        'module_origins':origins}
    rows=[]
    for task in plan['tasks']:
        lines={};cached={}
        def trace(frame,event,arg):
            if event=='line':
                filename=frame.f_code.co_filename
                if filename not in cached:
                    path=Path(filename).resolve()
                    cached[filename]=path.relative_to(root).as_posix() if path.is_relative_to(root) else None
                path=cached[filename]
                if path:lines.setdefault(path,set()).add(frame.f_lineno)
            return trace
        previous=sys.gettrace();sys.settrace(trace)
        try:expected=probe(task['task_id'])
        finally:sys.settrace(previous)
        rows.append({'task_id':task['task_id'],'expected':expected,
                     'executed_source_lines':{p:sorted(v) for p,v in sorted(lines.items())}})
    for name,module in list(sys.modules.items()):
        if name.split('.')[0] in ('rich','jinja2','werkzeug'):
            path=Path(module.__file__).resolve();assert path.is_relative_to(root)
            relative=path.relative_to(root).as_posix()
            assert relative in plan['source_sha256']
            environment['module_origins'][name]=relative
    report={'evidence_mode':'LOCAL','generative_calls':0,'status':'COMPLETE','repeat':repeat,
            'plan_sha256':sha((output/'plan.json').read_bytes()),'environment':environment,'rows':rows}
    if repeat>1:
        prior=read(output/f'oracles-{repeat-1}.json')
        assert prior['environment']==environment and prior['plan_sha256']==report['plan_sha256']
        assert [r['expected'] for r in prior['rows']]==[r['expected'] for r in rows], 'Oracle disagreement'
        report['expected_outputs_match_previous']=True
        report['trace_lines_match_previous']=[r['executed_source_lines'] for r in prior['rows']]==[r['executed_source_lines'] for r in rows]
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print({'status':'COMPLETE','repeat':repeat,'tasks':len(rows),
           'matched_previous':report.get('expected_outputs_match_previous')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--phase',choices=('declare','execute'),required=True);p.add_argument('--repeat',type=int,default=1)
    a=p.parse_args()
    if a.phase=='declare':declare(a.snapshot,a.output)
    else:execute(a.snapshot,a.output,a.repeat)

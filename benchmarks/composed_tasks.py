"""Prospective developer-authored questions combining real standard libraries."""
import configparser as cp
import difflib
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
from unittest.mock import patch
from urllib.parse import urljoin, urlsplit
from benchmarks.stdlib_tasks import Task, outcome
from benchmarks.repository_tasks import anchors


def config_tokens():
    c=cp.ConfigParser(defaults={'root':'/srv/team files'})
    c.read_dict({'job':{'command':'copy "%(root)s/a" target # skip'}})
    value=c.get('job','command')
    return {'expanded':value,'tokens':shlex.split(value,comments=True),
            'raw_tokens':shlex.split(c.get('job','command',raw=True),comments=True)}


def config_urls():
    c=cp.ConfigParser(interpolation=cp.ExtendedInterpolation())
    c.read_dict({'DEFAULT':{'host':'example.test'},'paths':{'base':'https://${host}/v1/'},
                 'job':{'endpoint':'${paths:base}objects/'}})
    base=c.get('job','endpoint',vars={'host':'override.test'})
    return {'base':base,'parent':urljoin(base,'../status?ready=1'),
            'other_host':urljoin(base,'//else.test/x')}


def wildcards():
    values=['pkg/main.py','pkg/sub/main.py','pkg/sub/deep/main.py']
    return {'pure':[PurePosixPath(v).match('pkg/**/*.py') for v in values],
            'strings':[fnmatch.fnmatchcase(v,'pkg/**/*.py') for v in values],
            'slash_crossing':fnmatch.fnmatchcase('pkg/sub/main.py','pkg/*.py')}


def config_paths():
    c=cp.ConfigParser(defaults={'root':'/srv'})
    c.read_dict({'job':{'path':'%(root)s/a/../b/file'}})
    p=PurePosixPath(c.get('job','path'))
    return {'parts':list(p.parts),'relative':str(p.relative_to('/srv/a')),
            'walk_up':str(p.relative_to('/srv/z',walk_up=True)),'parent':str(p.parent)}


def url_shell():
    uri=urljoin('https://example.test/a/b?old=1','../c?q=two%20words#frag')
    quoted=shlex.join(['fetch',uri])
    parsed=shlex.split(quoted,comments=True)
    return {'command':quoted,'tokens':parsed,'query':urlsplit(parsed[1]).query,
            'fragment':urlsplit(parsed[1]).fragment,'unquoted':shlex.split('fetch '+uri,comments=True)}


def suggestions():
    c=cp.ConfigParser();c.read_dict({'job':{'RETRY':'2','RETRY_MAX':'7','Route':'local'}})
    options=list(c['job'])
    return {'options':options,'uppercase':difflib.get_close_matches('RETRY',options),
            'lowercase':difflib.get_close_matches('retry',options),
            'exact_cutoff':difflib.get_close_matches('retry',options,cutoff=1)}


def path_filter():
    c=cp.ConfigParser();c.read_dict({'scan':{'pattern':'src/*.py'}})
    items=shlex.split('src/main.py "src/sub/helper.py" docs/readme.md')
    pattern=c.get('scan','pattern')
    return {'string_filter':fnmatch.filter(items,pattern),
            'path_filter':[x for x in items if PurePosixPath(x).match(pattern)],'items':items}


def conversion_tokens():
    c=cp.ConfigParser();c.read_dict({'job':{'timeout':'oops','args':'alpha "beta gamma"'}})
    def split_missing():return shlex.split(c.get('job','missing',fallback='one "two three"'))
    return {'timeout':outcome(lambda:c.getint('job','timeout',fallback=5)),
            'args':shlex.split(c.get('job','args')),'missing':split_missing(),
            'raw_timeout':c.get('job','timeout',fallback='5')}


TASKS=[
 Task('composed_config_tokens',"A default INI parser has DEFAULT root='/srv/team files' and job command='copy \"%(root)s/a\" target # skip'. Get command normally and tokenize it with the standard shell split helper using comments=True; also tokenize the raw=True value. Return JSON expanded, tokens, raw_tokens. Do not execute the command.",config_tokens,
      (('configparser.py','BasicInterpolation._interpolate_some'),('configparser.py','RawConfigParser.get'),('shlex.py','split'),('shlex.py','shlex.read_token'))),
 Task('composed_config_urls',"An INI parser uses extended interpolation. read_dict receives DEFAULT host='example.test', paths base='https://${host}/v1/', and job endpoint='${paths:base}objects/'. Get job endpoint with vars={'host':'override.test'} and use it as the urljoin base for '../status?ready=1' and '//else.test/x'. Return JSON base, parent, other_host. Do not access the network.",config_urls,
      (('configparser.py','ExtendedInterpolation._interpolate_some'),('configparser.py','RawConfigParser.get'),('urllib/parse.py','urljoin'))),
 Task('composed_wildcards',"Compare pure POSIX path matching to case-sensitive shell wildcard string matching. With pattern 'pkg/**/*.py', test 'pkg/main.py', 'pkg/sub/main.py', 'pkg/sub/deep/main.py' in that order under each API. Also test the string matcher with 'pkg/sub/main.py' and 'pkg/*.py'. Return JSON pure and strings as boolean arrays, and slash_crossing as a boolean. Do not use filesystem globbing.",wildcards,
      (('pathlib.py','PurePath.match'),('pathlib.py','_compile_pattern'),('fnmatch.py','fnmatchcase'),('fnmatch.py','translate'))),
 Task('composed_config_paths',"A default INI parser has DEFAULT root='/srv' and job path='%(root)s/a/../b/file'. Get the path and create a pure POSIX path. Return JSON parts (array), relative (relative_to('/srv/a')), walk_up (relative_to('/srv/z',walk_up=True)), parent. Paths must be strings except parts. Do not resolve paths or access the filesystem.",config_paths,
      (('configparser.py','BasicInterpolation._interpolate_some'),('pathlib.py','PurePath.relative_to'),('pathlib.py','PurePath.parts'))),
 Task('composed_url_shell',"Join URL base 'https://example.test/a/b?old=1' with '../c?q=two%20words#frag' using urljoin. Build a command with the standard shell join helper on ['fetch',joined_url], then split that command with comments=True. Parse the second token as a URL. Return JSON command, tokens, query, fragment, unquoted (split 'fetch '+joined_url with comments=True). Do not execute commands or access the network.",url_shell,
      (('urllib/parse.py','urljoin'),('urllib/parse.py','urlsplit'),('shlex.py','join'),('shlex.py','shlex.read_token'))),
 Task('composed_suggestions',"A default INI parser reads {'job':{'RETRY':'2','RETRY_MAX':'7','Route':'local'}} with read_dict. List the section proxy's option names in iteration order. Use that list as possibilities for the standard close-string-match helper with word 'RETRY' at defaults, 'retry' at defaults, and 'retry' with cutoff=1. Return JSON options, uppercase, lowercase, exact_cutoff as arrays. Do not normalize the query words yourself.",suggestions,
      (('configparser.py','RawConfigParser.optionxform'),('configparser.py','RawConfigParser.options'),('difflib.py','get_close_matches'))),
 Task('composed_path_filter',"A default INI parser reads {'scan':{'pattern':'src/*.py'}}. Shell-split 'src/main.py \"src/sub/helper.py\" docs/readme.md'. Filter those strings using fnmatch.filter and the configured pattern, then independently filter using pure POSIX path.match with that pattern. Return JSON string_filter, path_filter, items as arrays. Inputs use lowercase ASCII; no filesystem operations.",path_filter,
      (('configparser.py','RawConfigParser.get'),('shlex.py','split'),('fnmatch.py','filter'),('pathlib.py','PurePath.match'))),
 Task('composed_conversion_tokens',"A default INI parser reads {'job':{'timeout':'oops','args':'alpha \"beta gamma\"'}}. Get timeout as an integer with fallback=5, shell-split args, shell-split missing with fallback='one \"two three\"', and get timeout as a string with fallback='5'. Return JSON timeout, args, missing, raw_timeout; an exception is {\"error\": class name}. Do not execute a shell.",conversion_tokens,
      (('configparser.py','RawConfigParser._get_conv'),('configparser.py','RawConfigParser.get'),('shlex.py','split'))),
]


def freeze(source,output):
    assert sys.version_info[:3]==(3,12,10)
    if output.exists():raise ValueError('new frozen task file required')
    rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('oracle attempted network')):
        for task in TASKS:
            required=[{'path':'cpython/Lib/'+path,'symbol':symbol,'span':anchors(source/'cpython/Lib'/path)[symbol]}
                      for path,symbol in task.required]
            assert len({r['path'] for r in required})>=2
            rows.append({'id':task.id,'family':task.id,'cohort':'prospective_composed',
                         'question':'In CPython 3.12.10, '+task.question,'answer':task.oracle(),'required':required})
    data={'evidence_mode':'LOCAL','generative_calls':0,'python_version':'3.12.10','tasks':rows,
          'definition_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'limitations':['Developer-authored before retrieval, not independent sealed validation',
                         'Combines known libraries/behaviors; correlated with the cycle14 component questions',
                         'Required symbols are conservative source-span diagnostics, not proven sufficient or minimal context']}
    raw=json.dumps(data,indent=2).encode();output.write_bytes(raw)
    output.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest())
    print({'tasks':len(rows),'sha256':hashlib.sha256(raw).hexdigest(),'generative_calls':0})


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();freeze(a.source,a.output)

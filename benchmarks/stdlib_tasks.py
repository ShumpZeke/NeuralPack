"""Prospective developer-authored CPython behavior cases, frozen before retrieval.

Oracles are trusted local tests, not runtime tools. Required spans are conservative
diagnostics, not proofs of sufficient or minimum context. Cases share libraries.
"""
from dataclasses import dataclass
import configparser as cp
import hashlib
import json
from pathlib import Path,PurePosixPath
import shlex
import sys
from unittest.mock import patch
from urllib.parse import urljoin
from benchmarks.repository_tasks import anchors


def outcome(call):
    try:return call()
    except (ValueError,KeyError,cp.Error) as error:return {'error':type(error).__name__}


def extended_chain():
    c=cp.ConfigParser(interpolation=cp.ExtendedInterpolation())
    c.read_dict({'DEFAULT':{'root':'/srv'},'paths':{'base':'${root}/var'},
                 'svc':{'home':'${root}/app','cache':'${paths:base}/tmp'}})
    return {'home':c.get('svc','home',vars={'root':'/opt'}),
            'cache':c.get('svc','cache',vars={'root':'/opt'}),'ordinary_cache':c.get('svc','cache')}


def fallback_conversion():
    c=cp.ConfigParser(defaults={'port':'oops'});c.read_dict({'svc':{'timeout':'25'}})
    return {'missing':c.getint('svc','missing',fallback=7),
            'bad_default':outcome(lambda:c.getint('svc','port',fallback=7)),
            'override':c.getint('svc','port',vars={'port':'8'},fallback=7)}


def duplicate_case():
    body='[svc]\nColor=red\ncolor=blue\n'
    strict=outcome(lambda:cp.ConfigParser().read_string(body))
    relaxed=cp.ConfigParser(strict=False);relaxed.read_string(body)
    preserve=cp.ConfigParser();preserve.optionxform=str;preserve.read_string(body)
    return {'strict':strict,'relaxed':relaxed.get('svc','color'),
            'preserved_keys':sorted(preserve['svc']),'upper':preserve['svc']['Color'],'lower':preserve['svc']['color']}


def percent_escapes():
    c=cp.ConfigParser(defaults={'root':'/srv'})
    c.read_dict({'svc':{'progress':'100%% ready','path':'%(root)s/data','missing':'%(absent)s'}})
    return {'progress':c.get('svc','progress'),'raw':c.get('svc','progress',raw=True),
            'path':c.get('svc','path'),'missing':outcome(lambda:c.get('svc','missing',fallback='backup'))}


def valueless_options():
    c=cp.ConfigParser(allow_no_value=True);c.read_string('[svc]\nflag\nempty=\nspace=  \n')
    return {'flag':c.get('svc','flag'),'empty':c.get('svc','empty'),'space':c.get('svc','space'),
            'contains_flag':'flag' in c['svc'],'missing':c.get('svc','absent',fallback='backup')}


def proxy_defaults():
    c=cp.ConfigParser(defaults={'shared':'base','inherited':'keep'})
    c.read_dict({'svc':{'local':'x','shared':'override'}});before=sorted(c['svc'])
    del c['svc']['shared']
    def remove():del c['svc']['inherited']
    return {'keys':before,'shared_after_delete':c['svc']['shared'],
            'delete_inherited':outcome(remove),'inherited_after':c['svc']['inherited']}


def interpolation_cycle():
    c=cp.ConfigParser();c.read_dict({'svc':{'a':'%(b)s','b':'%(a)s'}})
    return {'plain':outcome(lambda:c.get('svc','a')),'fallback':outcome(lambda:c.get('svc','a',fallback='backup')),
            'raw':c.get('svc','a',raw=True),'limit':cp.MAX_INTERPOLATION_DEPTH}


def dictionary_casting():
    c=cp.ConfigParser(allow_no_value=True)
    c.read_dict({'svc':{'number':17,'enabled':True,'unset':None,'complex':[1,2]}})
    return {'number':c.get('svc','number'),'enabled':c.get('svc','enabled'),
            'unset':c.get('svc','unset'),'complex':c.get('svc','complex'),
            'integer':c.getint('svc','number'),'boolean':c.getboolean('svc','enabled')}


def path_matching():
    p=PurePosixPath('/srv/pkg/main.py')
    return {'suffix':p.match('*.py'),'relative_pattern':p.match('pkg/*.py'),'absolute_pattern':p.match('/pkg/*.py'),
            'double_star_zero':PurePosixPath('pkg/main.py').match('pkg/**/*.py'),
            'double_star_one':PurePosixPath('pkg/sub/main.py').match('pkg/**/*.py'),
            'double_star_two':PurePosixPath('pkg/sub/deep/main.py').match('pkg/**/*.py')}


def path_walk_up():
    p=PurePosixPath('/srv/a/file')
    return {'strict':outcome(lambda:str(p.relative_to('/srv/b'))),
            'walk_up':str(p.relative_to('/srv/b',walk_up=True)),
            'different_anchor':outcome(lambda:str(p.relative_to('srv/b',walk_up=True))),
            'own_parent':str(p.relative_to('/srv/a'))}


def join_boundaries():
    base='https://example.test/a/b?old=1#old'
    return {'query':urljoin(base,'?new=2'),'fragment':urljoin(base,'#new'),
            'host':urljoin(base,'//other.test/x'),'empty':urljoin(base,''),'parent':urljoin(base,'../c')}


def shell_lexing():
    body='alpha "beta gamma" # note'
    return {'default':shlex.split(body),'comments':shlex.split(body,comments=True),
            'nonposix':shlex.split(body,posix=False),'unclosed':outcome(lambda:shlex.split('alpha "beta'))}


@dataclass(frozen=True)
class Task:
    id:str
    question:str
    oracle:object
    required:tuple


TASKS=[
 Task('extended_scope',"An INI reader uses extended dollar-sign interpolation. read_dict receives DEFAULT root='/srv', paths base='${root}/var', and svc home='${root}/app', cache='${paths:base}/tmp'. Read svc home and cache with vars={'root':'/opt'}, then cache without vars. Return JSON home, cache, ordinary_cache.",extended_chain,
      (('configparser.py','ExtendedInterpolation._interpolate_some'),('configparser.py','RawConfigParser._unify_values'))),
 Task('fallback_conversion',"An INI reader has defaults={'port':'oops'} and read_dict({'svc':{'timeout':'25'}}). Call getint('svc','missing',fallback=7), getint('svc','port',fallback=7), and getint('svc','port',vars={'port':'8'},fallback=7). Return JSON missing, bad_default, override. Exceptions are objects with an error field containing the class name.",fallback_conversion,
      (('configparser.py','RawConfigParser._get_conv'),('configparser.py','RawConfigParser.get'),('configparser.py','RawConfigParser._unify_values'))),
 Task('duplicate_case',"Read the INI text '[svc]\\nColor=red\\ncolor=blue\\n' into three separate parsers: the default parser; strict=False; and a default parser whose optionxform is set to str before reading. Return JSON strict (null if reading succeeds, otherwise {\"error\": class name}), relaxed (the value of color in svc), preserved_keys (sorted names in svc from the third parser), upper and lower (third-parser values of Color and color).",duplicate_case,
      (('configparser.py','RawConfigParser._read'),('configparser.py','RawConfigParser.optionxform'))),
 Task('percent_escapes',"An INI reader uses default interpolation with defaults={'root':'/srv'} and read_dict({'svc':{'progress':'100%% ready','path':'%(root)s/data','missing':'%(absent)s'}}). Read progress normally and with raw=True, then path and missing (the latter with fallback='backup'). Return JSON progress, raw, path, missing; an exception is {\"error\": its class name}.",percent_escapes,
      (('configparser.py','BasicInterpolation._interpolate_some'),('configparser.py','RawConfigParser.get'))),
 Task('valueless_options',"An INI reader has allow_no_value=True and reads '[svc]\\nflag\\nempty=\\nspace=  \\n'. Obtain flag, empty, and space with get; test whether flag is in the section proxy; then get absent with fallback='backup'. Return JSON flag, empty, space, contains_flag, missing.",valueless_options,
      (('configparser.py','RawConfigParser._read'),('configparser.py','RawConfigParser.get'))),
 Task('proxy_defaults',"An INI reader has defaults={'shared':'base','inherited':'keep'} and read_dict({'svc':{'local':'x','shared':'override'}}). First list sorted keys of the svc section proxy, then delete its shared key. Read shared again. Attempt to delete inherited, then read inherited again. Return JSON keys, shared_after_delete, delete_inherited (null or {\"error\": class name}), inherited_after.",proxy_defaults,
      (('configparser.py','SectionProxy.__delitem__'),('configparser.py','RawConfigParser.remove_option'),('configparser.py','RawConfigParser.options'))),
 Task('interpolation_cycle',"An INI reader uses default interpolation and read_dict({'svc':{'a':'%(b)s','b':'%(a)s'}}). Read svc a normally, with fallback='backup', and with raw=True. Also report the module's interpolation depth limit. Return JSON plain, fallback, raw, limit; exceptions are {\"error\": class name}.",interpolation_cycle,
      (('configparser.py','BasicInterpolation._interpolate_some'),('configparser.py','RawConfigParser.get'))),
 Task('dictionary_casting',"An INI reader has allow_no_value=True. read_dict receives {'svc':{'number':17,'enabled':True,'unset':None,'complex':[1,2]}}. Read all four values with get, then number with getint and enabled with getboolean. Return JSON number, enabled, unset, complex, integer, boolean with exact types.",dictionary_casting,
      (('configparser.py','RawConfigParser.read_dict'),('configparser.py','RawConfigParser._get_conv'))),
 Task('path_matching',"Use pure POSIX paths, without accessing a filesystem. For '/srv/pkg/main.py', call match with '*.py', 'pkg/*.py', and '/pkg/*.py'. Then match 'pkg/**/*.py' against 'pkg/main.py', 'pkg/sub/main.py', and 'pkg/sub/deep/main.py'. Return six booleans in JSON suffix, relative_pattern, absolute_pattern, double_star_zero, double_star_one, double_star_two. Use the behavior of match, not filesystem globbing.",path_matching,
      (('pathlib.py','PurePath.match'),('pathlib.py','_compile_pattern'))),
 Task('path_walk_up',"Use pure POSIX path '/srv/a/file'. Compute relative_to('/srv/b') with defaults, relative_to('/srv/b',walk_up=True), relative_to('srv/b',walk_up=True), and relative_to('/srv/a'). Convert successful paths to strings. Return JSON strict, walk_up, different_anchor, own_parent; exceptions are {\"error\": class name}. Do not resolve files on disk.",path_walk_up,
      (('pathlib.py','PurePath.relative_to'),)),
 Task('url_join_boundaries',"A URL reference resolver uses base 'https://example.test/a/b?old=1#old'. Resolve the references '?new=2', '#new', '//other.test/x', '', and '../c' with the standard urljoin function. Return exact URL strings in JSON query, fragment, host, empty, parent. Do not access the network.",join_boundaries,
      (('urllib/parse.py','urljoin'),('urllib/parse.py','urlparse'),('urllib/parse.py','urlunparse'))),
 Task('shell_lexing',"Tokenize the string 'alpha \"beta gamma\" # note' with the standard shell-like split helper using defaults, comments=True, and posix=False in separate calls. Then tokenize 'alpha \"beta' with defaults. Return JSON default, comments, nonposix, unclosed; tokens are arrays and an exception is {\"error\": class name}. Do not execute any shell commands.",shell_lexing,
      (('shlex.py','split'),('shlex.py','shlex.read_token'))),
]


def freeze(source,output):
    assert sys.version_info[:3]==(3,12,10)
    if output.exists():raise ValueError('new frozen task file required')
    rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('oracle attempted network')):
        for task in TASKS:
            required=[]
            for path,symbol in task.required:
                relative='cpython/Lib/'+path
                required.append({'path':relative,'symbol':symbol,'span':anchors(source/relative)[symbol]})
            rows.append({'id':task.id,'family':task.id,'cohort':'prospective_stdlib',
                         'question':'In CPython 3.12.10, '+task.question,'answer':task.oracle(),'required':required})
    data={'evidence_mode':'LOCAL','tasks':rows,'python_version':'3.12.10','generative_calls':0,
          'definition_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'limitations':['Developer-authored and frozen before retrieval; not independently sealed',
                         'Eight cases share configparser; families and required spans are correlated',
                         'Required spans are conservative source diagnostics, not sufficient or minimum-context proof']}
    raw=json.dumps(data,indent=2).encode();output.write_bytes(raw)
    output.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest())
    print({'tasks':len(rows),'sha256':hashlib.sha256(raw).hexdigest(),'generative_calls':0})


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();freeze(a.source,a.output)

"""New developer-authored Click questions frozen before retrieval experiments.

Identifier/prose pairs share one executable oracle and are correlated cases,
not independent or externally sealed validation. Required spans are diagnostic.
"""
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from unittest.mock import patch
import click
from benchmarks.repository_tasks import anchors


def value_or_error(operation):
    try:return operation()
    except (click.ClickException,TypeError,ValueError) as error:return {'error':type(error).__name__}


def integer_bounds():
    param=click.IntRange(1,5,min_open=True,max_open=True,clamp=True)
    return {'low':param.convert('0',None,None),'high':param.convert('6',None,None),
            'middle':param.convert('3',None,None),'invalid':value_or_error(lambda:param.convert('bad',None,None))}


def float_bounds():
    return {'open_clamp':value_or_error(lambda:click.FloatRange(0,1,min_open=True,clamp=True)),
            'closed_low':click.FloatRange(0,1,clamp=True).convert('-2',None,None),
            'closed_high':click.FloatRange(0,1,clamp=True).convert('3',None,None)}


def booleans():
    return {key:value_or_error(lambda v=value:click.BOOL.convert(v,None,None)) for key,value in
            (('spaced_yes',' YES '),('false','False'),('off','off'),('zero','0'),('invalid','junk'))}


def bad_parameter():
    param=click.Option(['--real'])
    return {'override':click.BadParameter('broken',param=param,param_hint='custom').format_message(),
            'derived':click.BadParameter('broken',param=param).format_message(),
            'bare':click.BadParameter('broken').format_message()}


def missing_parameter():
    return {'bare':click.MissingParameter().format_message(),
            'hinted':click.MissingParameter('supply one',param_hint=['--one','--two'],param_type='option').format_message(),
            'choice':click.MissingParameter(param=click.Option(['--mode'],type=click.Choice(['slow','fast']))).format_message()}


def no_option():
    return {'none':click.NoSuchOption('--bad').format_message(),
            'one':click.NoSuchOption('--bad',possibilities=['--good']).format_message(),
            'many':click.NoSuchOption('--bad',possibilities=['--zoom','--alpha']).format_message()}


def file_error():
    return {'default':click.FileError('sample.txt').format_message(),
            'custom':click.FileError('sample.txt','blocked').format_message(),
            'exit_code':click.FileError('sample.txt').exit_code}


def choice_identity():
    import enum
    class Colour(enum.Enum): RED='scarlet';BLUE='azure'
    param=click.Choice(Colour,case_sensitive=False)
    return {'name':param.convert('red',None,None).name,'value':param.convert('RED',None,None).value,
            'enum_value':value_or_error(lambda:param.convert('scarlet',None,None))}


@dataclass(frozen=True)
class Task:
    id:str
    symbol:str
    description:str
    body:str
    oracle:object
    required:tuple


TASKS=[
    Task('integer_open_clamp','IntRange','integer argument type with lower and upper numeric boundaries',
         "Use min=1, max=5, min_open=True, max_open=True, clamp=True. Convert strings '0', '6', '3' and 'bad' with param=None and ctx=None. Return JSON low, high, middle, invalid; an exception is represented as {\"error\": its class name}.",integer_bounds,
         (('types.py','_NumberRangeBase.convert'),('types.py','IntRange._clamp'),('types.py','_NumberParamTypeBase.convert'))),
    Task('float_open_clamp','FloatRange','floating-point argument type with numeric bounds',
         "First construct with min=0, max=1, min_open=True, clamp=True; report open_clamp as an exception object {\"error\": class name} if construction fails. Separately use closed min=0/max=1/clamp=True to convert '-2' and '3' with no parameter/context. Return JSON open_clamp, closed_low, closed_high.",float_bounds,
         (('types.py','FloatRange.__init__'),('types.py','FloatRange._clamp'),('types.py','_NumberRangeBase.convert'))),
    Task('boolean_spelling','BoolParamType','boolean option-value converter',
         "Convert strings ' YES ', 'False', 'off', '0', and 'junk', with param=None and ctx=None. Return JSON spaced_yes, false, off, zero, invalid. Encode any exception as {\"error\": class name}.",booleans,
         (('types.py','BoolParamType.convert'),('types.py','BoolParamType.str_to_bool'))),
    Task('parameter_error_hints','BadParameter','exception for an invalid parameter value',
         "Use message='broken'. Compare a parameter declared as Option(['--real']) with explicit param_hint='custom', that parameter without a hint, and neither parameter nor hint. Call format_message(). Return exact strings in JSON override, derived, bare.",bad_parameter,
         (('exceptions.py','BadParameter.format_message'),('exceptions.py','_join_param_hints'),('core.py','Parameter.get_error_hint'))),
    Task('missing_error_detail','MissingParameter','exception for a required value that was not supplied',
         "Call format_message() for: no arguments; message='supply one', param_hint=['--one','--two'], param_type='option'; and param=Option(['--mode'],type=Choice(['slow','fast'])). Return exact strings in JSON bare, hinted, choice.",missing_parameter,
         (('exceptions.py','MissingParameter.format_message'),('exceptions.py','_join_param_hints'),('types.py','Choice.get_missing_message'))),
    Task('option_suggestions','NoSuchOption','exception for an unrecognized option name',
         "Use option_name='--bad' and default message. Compare no possibilities, possibilities=['--good'], and possibilities=['--zoom','--alpha'] in that order. Call format_message(). Return exact strings in JSON none, one, many.",no_option,
         (('exceptions.py','NoSuchOption.__init__'),('exceptions.py','NoSuchOption.format_message'),('exceptions.py','_format_possibilities'))),
    Task('file_error_default','FileError','exception for a file that cannot be opened',
         "Use filename='sample.txt'. Call format_message() with default hint and with hint='blocked'. Also obtain the default instance's exit_code. Return JSON default, custom, exit_code. These objects are constructed directly; do not open a file.",file_error,
         (('exceptions.py','FileError.__init__'),('exceptions.py','FileError.format_message'),('exceptions.py','ClickException'))),
    Task('enum_choice_names','Choice','argument type restricted to enumerated choices',
         "An enum Colour has RED='scarlet' and BLUE='azure'. Configure choices=Colour and case_sensitive=False. Convert 'red' and report its .name, convert 'RED' and report its .value, then convert 'scarlet'. Return JSON name, value, enum_value; exceptions are {\"error\": class name}. All conversions use param=None/ctx=None.",choice_identity,
         (('types.py','Choice.normalize_choice'),('types.py','Choice.convert'))),
]


def freeze(output):
    output=Path(output)
    if output.exists():raise ValueError('new frozen task path required')
    assert version('click')=='8.5.0'
    source=Path(click.__file__).parent
    rows=[]
    with patch('socket.socket.connect',side_effect=AssertionError('oracle attempted network')):
        for task in TASKS:
            answer=task.oracle()
            required=[{'path':'src/click/'+path,'symbol':symbol,'span':anchors(source/path)[symbol]} for path,symbol in task.required]
            for style,label in (('identifier',task.symbol),('prose',task.description)):
                rows.append({'id':task.id+'_'+style,'family':task.id,'query_style':style,
                             'question':f"In Click 8.5.0, consider {label}. {task.body}",
                             'answer':answer,'required':required})
    data={'package':'click','version':'8.5.0','evidence_mode':'LOCAL','tasks':rows,
          'definition_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'limitations':['Developer-authored after reading pinned source, frozen before retrieval; not externally sealed',
                         'Identifier/prose pairs share an oracle and are correlated','Full required spans are conservative diagnostics, not proven sufficient minima']}
    raw=json.dumps(data,indent=2).encode();output.write_bytes(raw)
    output.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='utf-8')
    print({'questions':len(rows),'families':len(TASKS),'sha256':hashlib.sha256(raw).hexdigest()})


if __name__=='__main__':
    import sys
    freeze(sys.argv[1])

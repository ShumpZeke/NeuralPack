"""Prospective Click behavior questions with executable, network-free oracles.

Authored before retrieving/scoring this workload. Once observed they are
development data, not an independently authored or permanently sealed test.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from unittest.mock import patch

import click
from click.testing import CliRunner

from benchmarks.repository_tasks import anchors

PACKAGE_VERSION="8.5.0"
SOURCE=Path(click.__file__).resolve().parent
ENV_NAMES=("NPK_CP_LEVEL","NPK_CP_PRIMARY","NPK_CP_SECONDARY","NPK_CP_CACHE",
           "NPK_CP_MODE","NPK_CP_POINT","NPKAPP_CHILD_LEVEL")


def invoke(command,args=(),env=None,**kwargs):
    clean={name:None for name in ENV_NAMES}
    clean.update(env or {})
    result=CliRunner().invoke(command,list(args),env=clean,**kwargs)
    if result.exit_code==0:
        return [0,json.loads(result.output)]
    if result.exit_code!=2:
        raise AssertionError(f"unexpected oracle failure: {type(result.exception).__name__}")
    return [result.exit_code,None]


def precedence():
    @click.command()
    @click.option("--level",type=int,default=7,envvar="NPK_CP_LEVEL")
    @click.pass_context
    def command(ctx,level):
        click.echo(json.dumps([level,ctx.get_parameter_source("level").name]))
    return {"cli":invoke(command,["--level","5"],{"NPK_CP_LEVEL":"9"},default_map={"level":"11"})[1],
            "env":invoke(command,env={"NPK_CP_LEVEL":"9"},default_map={"level":"11"})[1],
            "map":invoke(command,default_map={"level":"11"})[1],"default":invoke(command)[1]}


def env_chain():
    @click.command()
    @click.option("--level",type=int,default=5,envvar=["NPK_CP_PRIMARY","NPK_CP_SECONDARY"])
    def command(level): click.echo(json.dumps(level))
    return {"empty_first":invoke(command,env={"NPK_CP_PRIMARY":"","NPK_CP_SECONDARY":"8"}),
            "invalid_first":invoke(command,env={"NPK_CP_PRIMARY":"bad","NPK_CP_SECONDARY":"8"})}


def bool_env():
    @click.command()
    @click.option("--cache/--no-cache",default=True,envvar="NPK_CP_CACHE")
    def command(cache): click.echo(json.dumps(cache))
    return {"false_text":invoke(command,env={"NPK_CP_CACHE":"false"})[1],
            "off_text":invoke(command,env={"NPK_CP_CACHE":"OFF"})[1],
            "empty_text":invoke(command,env={"NPK_CP_CACHE":""})[1],
            "explicit_no":invoke(command,["--no-cache"],{"NPK_CP_CACHE":"true"})[1]}


def payload_env():
    @click.command()
    @click.option("--upper","transform",flag_value="upper",default=False,envvar="NPK_CP_MODE")
    def command(transform): click.echo(json.dumps(transform))
    return {name:invoke(command,env={"NPK_CP_MODE":value})
            for name,value in (("matching","upper"),("true_text","true"),("false_text","false"),("invalid","unrelated"))}


def multiple_env():
    @click.command()
    @click.option("--point",type=(str,int),multiple=True,envvar="NPK_CP_POINT")
    def command(point): click.echo(json.dumps(point))
    return {"env":invoke(command,env={"NPK_CP_POINT":"red 1 blue 2"}),
            "cli":invoke(command,["--point","green","9"],{"NPK_CP_POINT":"red 1 blue 2"}),
            "odd":invoke(command,env={"NPK_CP_POINT":"red 1 blue"})}


def conversion_callback():
    seen=[]
    def callback(ctx,param,value):
        seen.append([value,type(value).__name__]);return value
    @click.command()
    @click.option("--count",type=int,default="7",callback=callback)
    def command(count): click.echo(json.dumps(count))
    results={}
    for name,args,extra in (("default",(),{}),("mapped",(),{"default_map":{"count":"11"}}),("invalid",("--count","bad"),{})):
        seen.clear();result=invoke(command,args,**extra)
        results[name]={"exit_code":result[0],"callbacks":list(seen)}
    return results


def eager_order():
    seen=[]
    def callback(ctx,param,value): seen.append(param.name);return value
    def command(**kwargs): click.echo(json.dumps(seen))
    command=click.Command("tool",callback=command,params=[
        click.Option(["--first"],is_eager=True,callback=callback),
        click.Option(["--second"],is_eager=True,callback=callback),
        click.Option(["--normal"],callback=callback)])
    explicit=invoke(command,["--normal","N","--second","S","--first","F"])[1]
    seen.clear();absent=invoke(command)[1]
    return {"explicit":explicit,"absent":absent}


def normalize_choice():
    @click.command(context_settings={"token_normalize_func":lambda text:text.replace("_","-")})
    @click.option("--mode",type=click.Choice(["Fast_Mode","slow-mode"],case_sensitive=False))
    def command(mode): click.echo(json.dumps(mode))
    return {"hyphen":invoke(command,["--mode","FAST-MODE"]),"underscore":invoke(command,["--mode","SLOW_MODE"])}


def invoke_forward():
    target=click.Command("target",callback=lambda level:level,params=[click.Option(["--level"],type=int,default=7)])
    with click.Context(click.Command("source")) as ctx:
        ctx.params={"level":3}
        return {"invoke":ctx.invoke(target),"forward":ctx.forward(target),"explicit":ctx.invoke(target,level=9)}


def nested_defaults():
    @click.group(context_settings={"auto_envvar_prefix":"NPKAPP"})
    def command(): pass
    @command.command()
    @click.option("--level",type=int,default=7)
    @click.pass_context
    def child(ctx,level): click.echo(json.dumps([level,ctx.get_parameter_source("level").name]))
    return {"nested":invoke(command,["child"],default_map={"child":{"level":"12"}})[1],
            "flat":invoke(command,["child"],default_map={"level":"21"})[1],
            "env":invoke(command,["child"],{"NPKAPP_CHILD_LEVEL":"8"},default_map={"child":{"level":"12"}})[1]}


def resilient_parse():
    seen=[]
    def callback(ctx,param,value): seen.append(value);return value
    command=click.Command("tool",params=[click.Option(["--count"],type=int,required=True,callback=callback)])
    with command.make_context("tool",["--count","bad"],resilient_parsing=True) as ctx:
        relaxed={"value":ctx.params.get("count"),"callbacks":len(seen)}
    seen.clear()
    try:
        with command.make_context("tool",["--count","bad"]):
            raise AssertionError("invalid integer did not fail")
    except click.BadParameter as exc:
        strict={"exception":type(exc).__name__,"callbacks":len(seen)}
    return {"resilient":relaxed,"strict":strict}


def shared_destination():
    @click.command()
    @click.option("--left","value",type=int)
    @click.option("--right","value",type=int)
    def command(value): click.echo(json.dumps(value))
    return {"left_only":invoke(command,["--left","1"])[1],
            "both":invoke(command,["--left","1","--right","2"])[1],"absent":invoke(command)[1]}


@dataclass(frozen=True)
class Task:
    id:str
    question:str
    oracle:object
    required:tuple


TASKS=[
    Task("source_precedence","An integer option --level defaults to 7 and reads NPK_CP_LEVEL. A supplied default_map sets level to string '11'. Compare CLI --level 5 with env '9' and the map, env '9' with only the map, only the map, and no overrides. Return cli, env, map, default, each [value, ParameterSource.name].",precedence,(("core.py","Parameter.consume_value"),("core.py","Context.lookup_default"),("core.py","Parameter.handle_parse_result"))),
    Task("empty_env_chain","An integer option --level defaults to 5 and tries envvar=['NPK_CP_PRIMARY','NPK_CP_SECONDARY']. Secondary is '8'. Compare primary '' and primary 'bad'. Return empty_first and invalid_first as [exit_code, callback_value_or_null]; conversion failures exit 2 and do not run the command callback.",env_chain,(("core.py","Parameter.resolve_envvar_value"),("core.py","Parameter.consume_value"),("core.py","Parameter.process_value"))),
    Task("boolean_environment","Option --cache/--no-cache has default=True and envvar='NPK_CP_CACHE'. Return callback booleans false_text for env 'false', off_text for 'OFF', empty_text for '', and explicit_no for CLI --no-cache with env 'true'. No other overrides apply.",bool_env,(("core.py","Option.value_from_envvar"),("core.py","Option.consume_value"),("types.py","BoolParamType.str_to_bool"))),
    Task("flag_payload_environment","A command declares @click.option('--upper','transform',flag_value='upper',default=False,envvar='NPK_CP_MODE'). No CLI flag is passed. For env values 'upper', 'true', 'false', 'unrelated', return matching, true_text, false_text, invalid as [exit_code, exact callback_value_or_null].",payload_env,(("core.py","Option.value_from_envvar"),("core.py","Option.consume_value"),("types.py","StringParamType.convert"))),
    Task("tuple_environment","Option --point has type=(str,int), multiple=True, envvar='NPK_CP_POINT'. Compare env 'red 1 blue 2', CLI --point green 9 with that env, and env 'red 1 blue'. Return env, cli, odd as [exit_code, callback_tuple_sequence_as_JSON_or_null].",multiple_env,(("core.py","Option.value_from_envvar"),("core.py","batch"),("core.py","Parameter.type_cast_value"),("types.py","Tuple.convert"))),
    Task("conversion_before_callback","An integer --count option has default='7' and a parameter callback recording [value,type(value).__name__]. Compare no override, default_map={'count':'11'}, and CLI --count bad. Return default, mapped, invalid as objects with exit_code and callbacks (the recorded list).",conversion_callback,(("core.py","Parameter.process_value"),("core.py","Parameter.type_cast_value"),("core.py","Parameter.handle_parse_result"))),
    Task("eager_callback_order","A Command declares parameters in this order: --first (is_eager=True), --second (is_eager=True), --normal. All take a string and have callbacks recording param.name. Compare CLI --normal N --second S --first F with no CLI options. Return callback-name lists explicit and absent, including callbacks for missing optional parameters.",eager_order,(("core.py","iter_params_for_processing"),("core.py","Command.parse_args"))),
    Task("normalized_choice_identity","Option --mode uses Choice(['Fast_Mode','slow-mode'],case_sensitive=False). Its command token_normalize_func replaces '_' with '-'. Return hyphen for --mode FAST-MODE and underscore for --mode SLOW_MODE as [exit_code, exact callback_value_or_null].",normalize_choice,(("types.py","Choice.normalize_choice"),("types.py","Choice.convert"))),
    Task("invoke_vs_forward","A source Context has params={'level':3}. A target Command has integer --level default=7 and returns level from its callback. Return invoke for ctx.invoke(target), forward for ctx.forward(target), and explicit for ctx.invoke(target,level=9). These are separate calls in the same source context.",invoke_forward,(("core.py","Context.invoke"),("core.py","Context.forward"),("core.py","Parameter.get_default"))),
    Task("nested_defaults_and_environment","A group uses auto_envvar_prefix='NPKAPP' and has child command named child with integer --level default=7. Invoke child with default_map={'child':{'level':'12'}}, with flat default_map={'level':'21'}, and with the nested map plus env NPKAPP_CHILD_LEVEL='8'. Return nested, flat, env, each [value,ParameterSource.name].",nested_defaults,(("core.py","Context.__init__"),("core.py","Context.lookup_default"),("core.py","Option.resolve_envvar_value"))),
    Task("resilient_parse_suppression","A Command has required integer --count and a parameter callback recording each call. Compare make_context('tool',['--count','bad'],resilient_parsing=True) with the same call using normal parsing. Return resilient as {value: ctx.params.get('count'), callbacks: count}; strict as {exception: raised class name, callbacks: count}. Reset the recording list between calls.",resilient_parse,(("core.py","Parameter.handle_parse_result"),("core.py","Parameter.process_value"))),
    Task("shared_parameter_destination","A command declares @click.option('--left','value',type=int) above @click.option('--right','value',type=int), both optional with no explicit default. Its callback returns value. Return left_only for CLI --left 1, both for --left 1 --right 2, and absent for no CLI options.",shared_destination,(("core.py","Parameter.handle_parse_result"),("parser.py","_Option.process"))),
]


def dataset():
    if version("click")!=PACKAGE_VERSION:
        raise RuntimeError(f"oracles require click=={PACKAGE_VERSION}")
    records=[]
    for task in TASKS:
        required=[{"path":p,"symbol":name,"span":anchors(SOURCE/p)[name]} for p,name in task.required]
        with patch("socket.create_connection",side_effect=AssertionError("oracle attempted network")), \
             patch("socket.socket.connect",side_effect=AssertionError("oracle attempted network")):
            answer=task.oracle()
        records.append({"id":task.id,"question":"For Click 8.5.0 on Python 3.12. "+task.question,
                        "answer":answer,"required":required})
    return {"package":"click","version":PACKAGE_VERSION,"evidence_mode":"LOCAL",
            "limitations":["Prospective developer-authored workload, not independent sealed validation",
                           "Source spans are diagnostic annotations, not proven sufficient contexts"],
            "source_manifest":[{"path":p.relative_to(SOURCE).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size}
                               for p in sorted(SOURCE.rglob("*.py"))],"tasks":records}


if __name__=="__main__":
    print(json.dumps(dataset(),indent=2))

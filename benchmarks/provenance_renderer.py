"""Research renderer: retain source identity and charge it to the context cap.

The raw evidence payload is not changed. Headers are machine-produced JSON
metadata, not generated summaries or provider state. This is not a new default.
"""
import ast
import importlib
import inspect
import json
import textwrap

from npk.pack import PackSelector
from npk.pack.select import Selection
from npk.pack.format import PackError


def render_item(item):
    if not item.text.strip(): raise PackError('Cannot render empty source evidence')
    header = json.dumps([item.span, item.name], ensure_ascii=True, separators=(',', ':'))
    return '# source '+header+'\n'+item.text


def render(evidence, separator='\n\n'):
    return separator.join(render_item(e) for e in evidence)


class ProvenanceSelection(Selection):
    def context_text(self, separator='\n\n'):
        return render(self.evidence, separator)

    def as_dict(self, include_text=True):
        result = super().as_dict(include_text)
        result['context_format'] = 'source_identity_json_header_v1'
        result['token_accounting'] = ('exact for supplied tokenizer including source headers and default separators'
                                      if self.tokenizer else 'estimated chars/4 including source headers and default separators')
        result['token_accounting'] += '; excludes query/caller wrappers; item tokens describe raw source bodies'
        return result


def adapt(function):
    module = importlib.import_module('npk.pack.select')
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == '_fits'
             and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self']
    if len(calls) != 1: raise ValueError('Expected one public admission call')
    call = calls[0]
    if ast.dump(call.args[1]) != ast.dump(ast.parse('blk.text', mode='eval').body):
        raise ValueError('The public admission payload changed')
    call.func.attr = '_fits_block'
    call.args[1] = ast.Name(id='blk', ctx=ast.Load())
    ast.fix_missing_locations(tree)
    namespace = dict(vars(module)); namespace['Selection'] = ProvenanceSelection
    # Keep the existing research channel substitution interface functional;
    # the adapter itself never mutates global retrieval functions.
    for name in ('_lexical_channel', '_symbol_channel', '_embedding_channel'):
        def forward(*args, _name=name, **kwargs): return getattr(module, _name)(*args, **kwargs)
        namespace[name] = forward
    exec(compile(tree, __file__, 'exec'), namespace)
    return namespace[function.__name__]


class ProvenanceSelector(PackSelector):
    _select_once = adapt(PackSelector._select_once)
    _assemble = adapt(PackSelector._assemble)

    def _text_count(self, text):
        if self.tokenizer is not None: return self.tokenizer.count(text)
        return max(1, len(text)//4) if text else 0

    def _count(self, evidence):
        return self._text_count(render(evidence))

    def _fits_block(self, evidence, block, budget, *, used_chars):
        if not block.text.strip(): return False
        return self._text_count(render([*evidence, block])) <= budget

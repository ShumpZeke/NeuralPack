"""Research-only exact-source views with explicit docstring omissions.

These are evidence excerpts, not executable replacements or semantic-preserving
program transformations. Docstrings may affect answers and Python execution.
The default product selector does not import this module.
"""
from dataclasses import dataclass
import ast
from typing import Callable


@dataclass(frozen=True)
class Fragment:
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class View:
    fragments: tuple[Fragment, ...]
    omitted: tuple[tuple[int, int], ...]
    text: str


@dataclass(frozen=True,slots=True)
class PreparedViewPacking:
    representations: tuple[tuple[int,bool], ...]
    total_tokens: int
    graph_attempts: int
    fallback_attempts: int


def docstring_lines(source: str) -> tuple[tuple[int, int], ...]:
    """Only whole physical lines belonging exclusively to a literal docstring.

    Use full-file parsing, so a capped block beginning inside a string cannot
    turn a string literal into invented code. No source code is executed.
    Mixed statement lines and trailing comments are retained in full.
    """
    lines = source.split('\n')
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ()
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        # CPython AST columns are UTF-8 byte offsets, not character offsets.
        before = lines[first.lineno-1].encode('utf-8')[:first.col_offset]
        after = lines[first.end_lineno-1].encode('utf-8')[first.end_col_offset:]
        if before.strip() or after.strip():
            continue
        spans.append((first.lineno, first.end_lineno))
    return tuple(sorted(spans))


def omit_docstrings(text: str, start_line: int,
                    docstrings: tuple[tuple[int, int], ...]) -> View | None:
    """Create an explicitly marked excerpt; never return marker-only evidence."""
    lines = text.split('\n')
    end_line = start_line + len(lines) - 1
    clipped = [(max(start_line, lo), min(end_line, hi)) for lo, hi in docstrings
               if lo <= end_line and hi >= start_line]
    if not clipped:
        return None
    # Compiler-provided intervals must be sorted, disjoint, and valid.
    if any(lo < 1 or hi < lo for lo, hi in docstrings) or any(
            left[1] >= right[0] for left, right in zip(docstrings, docstrings[1:])):
        raise ValueError('Invalid docstring intervals')
    fragments = []
    parts = []
    cursor = start_line
    for lo, hi in clipped:
        if cursor < lo:
            body = '\n'.join(lines[cursor-start_line:lo-start_line])
            fragments.append(Fragment(cursor, lo-1, body))
            parts.append(body)
        parts.append(f'# [NPK: docstring omitted; source lines {lo}-{hi}]')
        cursor = hi + 1
    if cursor <= end_line:
        body = '\n'.join(lines[cursor-start_line:])
        fragments.append(Fragment(cursor, end_line, body))
        parts.append(body)
    if not any(f.text.strip() for f in fragments):
        return None
    return View(tuple(fragments), tuple(clipped), '\n'.join(parts))


def pack_views(query: str, budget: int, ordered_ids: list[int], blocks: dict,
               views: dict[int, View], count: Callable[[str], int], *, policy: str,
               count_parts: Callable[[list[str]], int] | None = None,
               state_counter=None,compact_ids: set[int] | None = None,
               transition_cache=None) -> dict:
    """Same fixed ranks, exact whole-payload budget, three declared policies.

    ``compact`` tries the smaller view even when the full block fits. ``rescue``
    tries it only after full-block rejection. Neither is a sufficiency claim.
    """
    if policy not in ('raw', 'compact', 'rescue'):
        raise ValueError('Unknown source-view policy')
    if type(budget) is not int or budget < 1:
        raise ValueError('Positive integer budget required')
    if len(ordered_ids) != len(set(ordered_ids)) or any(i not in blocks for i in ordered_ids):
        raise ValueError('Candidate identities must be unique and known')
    items = []
    context = ''
    state=state_counter.initial_state() if state_counter is not None else None
    state_active=state_counter is not None
    incremental_attempts=fallback_attempts=0
    for rank, bid in enumerate(ordered_ids):
        b = blocks[bid]
        full = b['text']
        view = views.get(bid)
        alternatives = [(full, None)]
        smaller=(bid in compact_ids if compact_ids is not None
                 else bool(view) and count(view.text)<count(full))
        if policy != 'raw' and view and smaller:
            if policy == 'compact':
                alternatives = [(view.text, view)]
            else:
                alternatives.append((view.text, view))
        for body, chosen in alternatives:
            proposed = context + ('\n\n' if items else '') + body
            trial=(state_counter.extend_state(state,body,transition_cache=transition_cache)
                   if state_active else None)
            if trial is not None:
                size=trial.total_tokens;incremental_attempts+=1
            else:
                size=(count_parts([i['text'] for i in items]+[body])
                      if count_parts else count(proposed))
                if state_counter is not None:fallback_attempts+=1
            if not body.strip() or size > budget:
                continue
            item = {'block_id': bid, 'path': b['path'], 'span': b['span'],
                    'name': b['name'], 'kind': b['kind'], 'rank': rank+1,
                    'text': body, 'omitted': list(chosen.omitted) if chosen else [],
                    'fragments': [vars(f) for f in chosen.fragments] if chosen else [
                        {'start_line': b['start_line'], 'end_line': b['end_line'], 'text': full}]}
            items.append(item)
            context = proposed
            if state_counter is not None:
                state=trial;state_active=trial is not None
            break
    omitted = any(i['omitted'] for i in items)
    tokens=(state.total_tokens if state_counter is not None and state_active else count(context))
    return {'query': query, 'items': items, 'context': context, 'tokens': tokens,
            'budget': budget, 'fallback_required': not items, 'used_generative_llm': False,
            'status': 'fallback_required' if not items else 'selected_with_omissions' if omitted else 'selected',
            'risk': 'uncalibrated:docstrings_omitted' if omitted else 'uncalibrated',
            'policy': policy,'incremental_attempts':incremental_attempts,
            'fallback_attempts':fallback_attempts}


def prepared_pack_views(ordered_ids,budgets,blocks,views,compact_ids,cost_graph,policy):
    """Evaluate one source-view ranking at every budget with exact graph costs."""
    if policy not in ('raw','compact','rescue'):raise ValueError('Unknown source-view policy')
    if not isinstance(budgets,(list,tuple)) or any(type(b) is not int or b<1 for b in budgets):
        raise ValueError('Positive integer budgets required')
    if len(set(budgets))!=len(budgets):raise ValueError('Budgets must be unique')
    if len(ordered_ids)!=len(set(ordered_ids)) or any(i not in blocks for i in ordered_ids):
        raise ValueError('Candidate identities must be unique and known')
    # Mutable cell state is private to this call and to one budget.
    states={cap:{'items':[],'texts':[],'total':0,'last':None,'active':True,
                 'graph':0,'fallback':0} for cap in budgets}
    for bid in ordered_ids:
        block=blocks[bid];full=block['text'];view=views.get(bid)
        eligible=view is not None and bid in compact_ids
        alternatives=((view.text,True),) if policy=='compact' and eligible else ((full,False),)
        if policy=='rescue' and eligible:alternatives=((full,False),(view.text,True))
        for cap,cell in states.items():
            for body,is_view in alternatives:
                trial=(cost_graph.extend(cell['total'],cell['last'],body)
                       if cell['active'] else None)
                if trial is None:
                    size=cost_graph.counter.count_parts(cell['texts']+[body]);cell['fallback']+=1
                else:size=trial[0];cell['graph']+=1
                if not body.strip() or size>cap:
                    continue
                cell['items'].append((bid,is_view));cell['texts'].append(body);cell['total']=size
                if trial is None:cell['active']=False;cell['last']=None
                else:cell['last']=trial[1]
                break
    return {cap:PreparedViewPacking(tuple(cell['items']),cell['total'],
                                    cell['graph'],cell['fallback'])
            for cap,cell in states.items()}

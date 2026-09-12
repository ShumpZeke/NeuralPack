"""Manually seeded source reference arms, not a deployable retrieval algorithm.

Function exposure is not a proof of sufficiency. Direct module bindings are a
separate ablation; neither arm executes source or closes dynamic dependencies.
"""
import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import symtable

from benchmarks.answer_records import sha, counts
from benchmarks.library_failure_analysis import PRIMARY
from benchmarks.prospective_eval import request_key, write_json
from benchmarks.repository_eval import answer_payload
from npk.auditor import _json
from npk.pack.source_policy import check_source

ARMS = ('reference_primary', 'reference_module_bindings')
SEEDS = {k: [list(s) for s in v] for k, v in PRIMARY.items()}
# Inspected frozen Werkzeug3.1.3 implementation; lines259/261 are overload stubs.
# This is explicit manual seed data, never an automatic last-definition heuristic.
SEEDS['werkzeug_duplicate_cookie'][-1].append(262)


def definitions_and_scopes(text):
    tree = ast.parse(text); scopes = symtable.symtable(text, '<source>', 'exec')
    found = {}
    def visit(nodes, table, prefix=()):
        for node in nodes:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): continue
            name = '.'.join((*prefix, node.name))
            matches = [s for s in table.get_children() if s.get_name() == node.name and s.get_lineno() == node.lineno]
            if len(matches) != 1: raise ValueError('Unsupported or ambiguous reference scope')
            found.setdefault(name, []).append((node, matches[0]))
            visit(node.body, matches[0], (*prefix, node.name))
    visit(tree.body, scopes)
    return tree, found


def referenced_globals(table):
    names = {s.get_name() for s in table.get_symbols() if s.is_referenced() and s.is_global()}
    for child in table.get_children(): names.update(referenced_globals(child))
    return names


def binding_names(node):
    if isinstance(node, ast.Import): return {a.asname or a.name.split('.')[0] for a in node.names}
    if isinstance(node, ast.ImportFrom): return {a.asname or a.name for a in node.names if a.name != '*'}
    if isinstance(node, ast.Assign): return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name): return {node.target.id}
    return set()


def source_segments(source, seeds, *, bindings=False):
    if not seeds: raise ValueError('Reference seeds cannot be empty')
    ranges = {}; parsed = {}; metadata = []
    for seed in seeds:
        if len(seed) not in (2, 3): raise ValueError('Invalid reference seed')
        path, name = seed[:2]
        if path not in source: raise ValueError('Reference source missing')
        if path not in parsed: parsed[path] = definitions_and_scopes(source[path])
        tree, found = parsed[path]
        if name not in found: raise ValueError('Reference definition missing')
        matches = found[name]
        if len(seed) == 3:
            if type(seed[2]) is not int or seed[2] <= 0: raise ValueError('Invalid reference line')
            matches = [v for v in matches if v[0].lineno == seed[2]]
        if len(matches) != 1: raise ValueError('Ambiguous or absent reference definition')
        node, table = matches[0]
        if isinstance(node, ast.ClassDef): raise ValueError('Reference seed must be a function or method')
        lo = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        ranges.setdefault(path, []).append((lo, node.end_lineno))
        globals_ = referenced_globals(table); included = []
        if bindings:
            for declaration in tree.body:
                names = binding_names(declaration) & globals_
                if names:
                    ranges[path].append((declaration.lineno, declaration.end_lineno))
                    included.extend(names)
        metadata.append({'path': path, 'definition': name, 'referenced_globals': sorted(globals_),
                         'included_direct_bindings': sorted(set(included))})
    segments = []
    for path, spans in sorted(ranges.items()):
        merged = []
        for lo, hi in sorted(spans):
            if merged and lo <= merged[-1][1]+1: merged[-1][1] = max(merged[-1][1], hi)
            else: merged.append([lo, hi])
        # Python AST line numbers count physical LF lines, not every Unicode
        # separator recognized by str.splitlines(). Keep original source bytes.
        lines = source[path].split('\n')
        for lo, hi in merged:
            text = '\n'.join(lines[lo-1:hi])
            segments.append({'path': path, 'start_line': lo, 'end_line': hi,
                             'text': text, 'text_sha256': sha(text.encode())})
    if not segments or not any(s['text'].strip() for s in segments):
        raise ValueError('Reference selection cannot be empty')
    return segments, metadata


def render(segments):
    return '\n\n'.join(f"[Source: {s['path']}:{s['start_line']}-{s['end_line']}]\n{s['text']}" for s in segments)


def bounded_reference(source, seeds, bindings, count, budget):
    segments, metadata = source_segments(source, seeds, bindings=bindings)
    context = render(segments); tokens = count(context)
    if type(tokens) is not int or tokens <= 0 or tokens > budget:
        raise ValueError('Complete reference context does not fit the declared budget')
    return context, tokens, segments, metadata


def read(path): return _json(path.read_bytes().decode('utf-8'))


def counters(assets, manifest, settings):
    from tokenizers import Tokenizer
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    for name, meta in manifest['files'].items():
        if sha((assets/name).read_bytes()) != meta['sha256']: raise ValueError('Tokenizer asset changed')
    codec = Tokenizer.from_file(str(assets/'tokenizer.json')); codec.no_padding(); codec.no_truncation()
    template = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True).from_string(
        (assets/'chat_template.jinja').read_text(encoding='utf-8'))
    def count(text): return len(codec.encode(text, add_special_tokens=False))
    def prompt(query, context):
        payload = answer_payload(settings['model'], query, context,
                                 **{k: v for k, v in settings.items() if k not in {'model', 'timeout_seconds'}})
        return count(template.render(messages=payload['messages'], add_generation_prompt=True,
                                      **settings['chat_template_kwargs']))
    return count, prompt


def validate_reference(root, assets=None):
    root = Path(root); raw = (root/'plan.json').read_bytes(); plan = _json(raw.decode())
    if sha(raw) != (root/'plan.sha256').read_text().strip(): raise ValueError('Reference plan changed')
    meta = plan['reference_evidence']; parent_raw = (root/'parent-plan.json').read_bytes()
    if meta['version'] != 1 or plan['comparison_baselines'] != [ARMS[0]]:
        raise ValueError('Unsupported reference comparison policy')
    for name, digest in meta['source_sha256'].items():
        if sha(Path(__file__).with_name(name).read_bytes()) != digest:
            raise ValueError('Reference construction code changed')
    if sha(parent_raw) != meta['parent_plan_sha256']: raise ValueError('Reference parent changed')
    parent = _json(parent_raw.decode())
    for field in ('settings', 'dataset', 'tokenizer_assets', 'source_manifest', 'corpus_tokens', 'available_tokens'):
        if plan[field] != parent[field]: raise ValueError('Reference changed parent conditions')
    if meta['manual_seeds'] != SEEDS:
        raise ValueError('Manual reference seeds changed')
    count, prompt_count = counters(Path(assets) if assets is not None else root/'tokenizer-assets',
                                   plan['tokenizer_assets'], plan['settings'])
    source = {}
    for path in {s[0] for seeds in SEEDS.values() for s in seeds}:
        body = (root/'source'/path).read_bytes()
        if sha(body) != parent['source_manifest'][path]: raise ValueError('Reference source changed')
        source[path] = body.decode()
    tasks = {t['id']: t for t in parent['dataset']['tasks']}
    if set(tasks) != set(SEEDS): raise ValueError('Reference tasks differ from declared seed set')
    cells = set(); requests = {}
    for row in plan['observations']:
        cell = row['task'], row['method']
        if cell in cells or row['method'] not in ARMS or row['budget'] != 2048:
            raise ValueError('Duplicate or unsupported reference cell')
        cells.add(cell); task = tasks[row['task']]
        context, tokens, segments, metadata = bounded_reference(source, SEEDS[row['task']],
            row['method'] == ARMS[1], count, 2048)
        digest = sha(context.encode()); key = request_key(plan['settings'], task['question'], context)
        if ((root/'contexts'/(digest+'.txt')).read_bytes() != context.encode()
                or row['context_sha256'] != digest or row['request_sha256'] != key
                or row['selected_tokens'] != tokens or row['selected_prompt_tokens'] != prompt_count(task['question'], context)
                or row['segments'] != segments or row['reference_metadata'] != metadata
                or row['corpus_tokens'] != parent['corpus_tokens'] or row['available_tokens'] != parent['available_tokens']):
            raise ValueError('Reference source, span, budget or payload identity changed')
        if key in parent['requests']: raise ValueError('Existing payload requires explicit replay, not a new sample')
        requests[key] = {'question': task['question'], 'context_sha256': digest}
    if cells != {(t, arm) for t in tasks for arm in ARMS} or requests != plan['requests']:
        raise ValueError('Missing or foreign reference requests')
    ledger = read(root/'ledger.json') if (root/'ledger.json').exists() else {}
    if not set(ledger) <= set(requests) or any(e.get('state') != 'DONE' for e in ledger.values()):
        raise ValueError('Unknown reference attempt; inspect before resuming')
    if {p.stem for p in (root/'responses').glob('*.json')} != set(ledger):
        raise ValueError('Orphan reference response cannot be silently replayed')
    from benchmarks.answer_recovery import require_payload
    for key, entry in ledger.items():
        if read(root/'responses'/(key+'.json')) != entry['result']: raise ValueError('Reference response and ledger differ')
        require_payload(root, plan, key, entry['result'])
    counts(ledger, allowed_modes=('LIVE',))
    return {'plan_sha256': sha(raw), 'observations': len(cells), 'unique_payloads': len(requests),
            'manual_seed_diagnostic': True, 'max_selected_tokens': max(r['selected_tokens'] for r in plan['observations']),
            'generative_optimizer_calls': 0}


def prepare(args):
    if args.output.exists(): raise ValueError('Fresh reference destination required')
    raw = (args.parent/'plan.json').read_bytes(); parent = _json(raw.decode())
    if sha(raw) != args.expected_parent or sha(raw) != (args.parent/'plan.sha256').read_text().strip():
        raise ValueError('Parent plan differs from frozen reference')
    count, prompt_count = counters(args.assets, parent['tokenizer_assets'], parent['settings'])
    source = {}; bodies = {}
    for path in {s[0] for seeds in SEEDS.values() for s in seeds}:
        body = (args.source/path).read_bytes()
        if sha(body) != parent['source_manifest'][path]: raise ValueError('Source differs from frozen library')
        check_source(body.decode(), path); bodies[path] = body; source[path] = body.decode()
    tasks = parent['dataset']['tasks']
    if {t['id'] for t in tasks} != set(SEEDS): raise ValueError('Reference tasks differ from seed set')
    rows = []; contexts = {}; baseline_prompts = {r['task']: r['baseline_prompt_tokens'] for r in parent['observations']}
    for task in tasks:
        for arm in ARMS:
            text, tokens, segments, metadata = bounded_reference(source, SEEDS[task['id']], arm == ARMS[1], count, 2048)
            digest = sha(text.encode()); contexts[digest] = text
            rows.append({'task': task['id'], 'method': arm, 'budget': 2048, 'context_sha256': digest,
                'request_sha256': request_key(parent['settings'], task['question'], text),
                'selected_tokens': tokens, 'selected_prompt_tokens': prompt_count(task['question'], text),
                'baseline_prompt_tokens': baseline_prompts[task['id']],
                'corpus_tokens': parent['corpus_tokens'], 'available_tokens': parent['available_tokens'],
                'seed_failed': False, 'manual_seed_diagnostic': True, 'segments': segments, 'reference_metadata': metadata})
    random.Random(2912).shuffle(rows)
    questions = {t['id']: t['question'] for t in tasks}; requests = {}
    for row in rows: requests.setdefault(row['request_sha256'], {'question': questions[row['task']], 'context_sha256': row['context_sha256']})
    if set(requests) & set(parent['requests']): raise ValueError('A reference payload already exists; explicit replay is required')
    plan = {k: parent[k] for k in ('settings', 'dataset', 'tokenizer_assets', 'source_manifest', 'corpus_tokens', 'available_tokens')}
    plan.update(created_utc=datetime.now(timezone.utc).isoformat(), evidence_mode='LOCAL',
        generative_optimization_calls=0, observations=rows, requests=requests,
        comparison_baselines=[ARMS[0]], execution_order='Frozen shuffle seed2912; one answer per unique payload',
        reference_evidence={'version': 1, 'parent_plan_sha256': sha(raw),
            'manual_seeds': SEEDS,
            'source_sha256': {p.name: sha(p.read_bytes()) for p in (Path(__file__), Path(__file__).with_name('library_failure_analysis.py'))}},
        limitations=['Manually seeded source diagnostic selected after inspecting prior answers; not automatic retrieval',
                    'No proven sufficient context or quality upper bound; no MSC/minimality claim',
                    'Only direct top-level imports and assignments are added, not transitive/dynamic closure',
                    'Conditional declarations, monkeypatching, object state and unlisted helpers can remain absent',
                    'Shared payloads are one sample; do not count arm observations as independent responses',
                    'Parent answers are historical and stochastic; they do not establish a controlled causal effect',
                    'Same2048 evidence caps; actual evidence lengths differ',
                    'No new generation settings, oracle answers, prices or claim of a deployable improvement'])
    args.output.mkdir(parents=True); (args.output/'contexts').mkdir()
    (args.output/'tokenizer-assets').mkdir()
    for name in parent['tokenizer_assets']['files']:
        (args.output/'tokenizer-assets'/name).write_bytes((args.assets/name).read_bytes())
    for path, body in bodies.items():
        target = args.output/'source'/path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
    for digest, text in contexts.items(): (args.output/'contexts'/(digest+'.txt')).write_bytes(text.encode())
    (args.output/'parent-plan.json').write_bytes(raw)
    write_json(args.output/'plan.json', plan)
    (args.output/'plan.sha256').write_text(sha((args.output/'plan.json').read_bytes()))
    print(validate_reference(args.output, args.assets), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'source', 'assets', 'output'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--expected-parent', required=True)
    prepare(p.parse_args())

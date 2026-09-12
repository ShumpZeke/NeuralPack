"""Post-hoc literal function exposure diagnostic; never a sufficiency metric."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path


# These are inspected primary implementations, not proven necessary/sufficient
# evidence. Helpers and configuration may matter beyond these definitions.
PRIMARY = {
    'rich_overshoot': [('rich/progress.py', 'Task.percentage'), ('rich/progress.py', 'Task.remaining'), ('rich/progress.py', 'Task.finished')],
    'rich_zero_unknown': [('rich/progress.py', 'Task.percentage'), ('rich/progress.py', 'Task.remaining')],
    'rich_stopped_clock': [('rich/progress.py', 'Task.elapsed')],
    'rich_terminal_cells': [('rich/text.py', 'Text.truncate'), ('rich/cells.py', 'set_cell_size')],
    'rich_ignore_padding': [('rich/text.py', 'Text.truncate')],
    'jinja_missing_falsey': [('jinja2/filters.py', 'do_default')],
    'jinja_chained_missing': [('jinja2/filters.py', 'do_default'), ('jinja2/runtime.py', 'Undefined.__getattr__'), ('jinja2/runtime.py', 'ChainableUndefined.__getattr__')],
    'jinja_url_forms': [('jinja2/filters.py', 'do_urlencode'), ('jinja2/utils.py', 'url_quote')],
    'jinja_integer_fallback': [('jinja2/filters.py', 'do_int')],
    'jinja_unique_case': [('jinja2/filters.py', 'sync_do_unique'), ('jinja2/filters.py', 'ignore_case')],
    'jinja_last_generator': [('jinja2/filters.py', 'do_last')],
    'werkzeug_duplicate_cookie': [('werkzeug/http.py', 'parse_cookie'), ('werkzeug/sansio/http.py', 'parse_cookie'), ('werkzeug/datastructures/structures.py', 'MultiDict.__getitem__'), ('werkzeug/datastructures/structures.py', 'MultiDict.getlist')],
    'werkzeug_filename_windows': [('werkzeug/utils.py', 'secure_filename')],
    'werkzeug_mime_charset': [('werkzeug/utils.py', 'get_content_type')],
    'werkzeug_slash_redirect': [('werkzeug/utils.py', 'append_slash_redirect')],
}


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def definitions(source):
    """Full contiguous definitions, with decorators and exact indentation."""
    lines = source.split('\n'); found = {}
    def visit(nodes, prefix=()):
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = (*prefix, node.name)
                lo = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                found['.'.join(name)] = (lo, node.end_lineno, '\n'.join(lines[lo-1:node.end_lineno]))
                visit(node.body, name)
    visit(ast.parse(source).body)
    return found


def summarize(method, budget, rows):
    present = [r for r in rows if r['all_listed_definitions_present']]
    returned = [r for r in rows if r['transport_success'] is True]
    return {'method': method, 'budget': budget, 'planned': len(rows),
            'all_primary_definitions_exposed': len(present),
            'responses_returned': len(returned),
            'response_parse_failures': sum(r['parse_error'] is True for r in returned),
            'responses_with_all_listed_definitions': sum(r['all_listed_definitions_present'] for r in returned),
            'wrong_with_all_listed_definitions': [r['task'] for r in present if r['task_success'] is False],
            'correct_without_all_listed_definitions': [r['task'] for r in rows if r['task_success'] is True and not r['all_listed_definitions_present']]}


def analyze(a):
    if a.output.exists(): raise ValueError('Fresh diagnostic output required')
    report = read(a.report); plan_bytes = (a.run/'plan.json').read_bytes(); plan = json.loads(plan_bytes)
    assert report['plan_sha256'] == sha(plan_bytes)
    # Use the report's frozen ledger, not a running ledger or partial new answers.
    ledger = (a.run/'report-ledgers'/(report['ledger_sha256']+'.json')).read_bytes()
    assert sha(ledger) == report['ledger_sha256']
    source_plan = read(a.oracles/'plan.json')
    expected = {r['task_id']: r['expected'] for r in read(a.oracles/'oracles-1.json')['rows']}
    source_root = a.snapshot/'corpus/test_src'; snippets = {}
    for path in {p for refs in PRIMARY.values() for p, _ in refs}:
        body = (source_root/path).read_bytes(); assert sha(body) == source_plan['source_sha256'][path]
        snippets[path] = definitions(body.decode().replace('\r\n', '\n').replace('\r', '\n'))
    records = []; meta = {}
    for row in report['rows']:
        refs = PRIMARY[row['task']]
        body = (a.run/'contexts'/(row['context_sha256']+'.txt')).read_bytes()
        assert sha(body) == row['context_sha256']; context = body.decode()
        exposure = []
        for path, name in refs:
            lo, hi, text = snippets[path][name]
            key = path+':'+name
            meta[key] = {'path': path, 'name': name, 'start_line': lo, 'end_line': hi,
                         'text_sha256': sha(text.encode()), 'text': text}
            exposure.append({'reference': key, 'whole_definition_present': text in context})
        records.append({'task': row['task'], 'method': row['method'], 'budget': row['budget'],
                        'request_sha256': row.get('request_sha256'), 'evidence_mode': row['evidence_mode'],
                        'context_sha256': row['context_sha256'], 'exposure': exposure,
                        'all_listed_definitions_present': all(e['whole_definition_present'] for e in exposure),
                        'task_success': row['task_success'], 'parsed': row.get('parsed'),
                        'transport_success': row['transport_success'], 'parse_error': row.get('parse_error'),
                        'expected': expected[row['task']]})
    grouped = defaultdict(list)
    for row in records: grouped[row['method'], row['budget']].append(row)
    summaries = []
    for (method, budget), rows in grouped.items():
        summaries.append(summarize(method, budget, rows))
    a.output.mkdir(parents=True)
    (a.output/'execution-source.py').write_bytes(Path(__file__).read_bytes())
    result = {'status': 'COMPLETE', 'evidence_mode': 'POST_HOC_LOCAL_ANALYSIS_OF_LIVE_RESULTS',
              'generative_calls': 0, 'code_sha256': sha(Path(__file__).read_bytes()),
              'answer_report_sha256': sha(a.report.read_bytes()), 'ledger_sha256': report['ledger_sha256'],
              'references': meta, 'rows': records, 'summaries': summaries,
              'limits': ['Primary implementation list was selected after inspecting some answers',
                         'Full contiguous definition presence is a conservative exposure diagnostic, not necessity or sufficiency',
                         'Partial views can contain useful evidence without matching a full definition',
                         'Unlisted helpers, initialization and platform/configuration can matter',
                         'Shared requests are not independent answer samples; failures remain missing',
                         'No causal attribution of all errors to either retrieval or target-model reasoning']}
    (a.output/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print({'status': 'COMPLETE', 'references': len(meta), 'summaries': [s for s in summaries if s['budget'] == 2048 or s['method'] == 'none']}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('report', 'run', 'oracles', 'snapshot', 'output'): p.add_argument('--'+name, type=Path, required=True)
    analyze(p.parse_args())

"""Reconstruct cycle-17 LOCAL selection diagnostics from frozen blocks and IDs."""
import hashlib
import statistics


def tokens(text): return max(1, int(len(text)/3.8)) if text else 0


def audit(inputs, rows):
    tasks = {t['id']: t for t in inputs['tasks']}
    if len(tasks) != len(inputs['tasks']): raise ValueError('duplicate task')
    expected = {(arm, mode, task, budget) for arm in ('before','after')
                for mode in ('default','lexical','embedding') for task in tasks for budget in inputs['budgets']}
    observed = set(); blocks = inputs['blocks']
    available = tokens('\n\n'.join(b['text'] for b in blocks))
    for row in rows:
        key = (row['arm'],row['mode'],row['task'],row['budget'])
        if key not in expected or key in observed: raise ValueError('unexpected or duplicate observation')
        observed.add(key); task = tasks[row['task']]; ids = row['selected_indices']
        if len(set(ids)) != len(ids) or any(type(i) is not int or not 0 <= i < len(blocks) for i in ids):
            raise ValueError('invalid evidence indices')
        text = '\n\n'.join(blocks[i]['text'] for i in ids); used = tokens(text)
        covered = {}
        for i in ids:
            block = blocks[i]
            covered.setdefault(block['path'],set()).update(range(block['start'],block['end']+1))
        hits = [set(range(r['span'][0],r['span'][1]+1)) <= covered.get(r['path'],set()) for r in task['required']]
        within = used <= row['budget']
        if type(row['seed_failed']) is not bool or row['seed_failed'] != (not ids):
            raise ValueError('misclassified empty evidence')
        fields = {'context_sha256':hashlib.sha256(text.encode()).hexdigest(), 'selected_tokens':used,
                  'available_tokens':available,'corpus_tokens':sum(tokens(b['text']) for b in blocks),
                  'within_budget':within,'required_span_fraction':statistics.mean(hits),
                  'all_required_spans':all(hits),
                  'eligible_required_span_fraction':statistics.mean(hits) if within and ids else None,
                  'cohort':task['cohort']}
        if any(row[k] != value for k,value in fields.items()): raise ValueError('diagnostic disagrees with source evidence')
        if row['arm'] == 'after' and (not within or row['reported_tokens'] != used):
            raise ValueError('candidate violated budget contract')
    if observed != expected: raise ValueError('incomplete observations')
    return len(observed)

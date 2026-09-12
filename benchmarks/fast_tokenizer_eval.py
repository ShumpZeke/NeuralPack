"""Cheap challenger: omit tokenizer offsets when only an exact count is needed.

Uses the documented tokenizers encode_batch_fast API, not a custom BPE or an
additive estimate. Research only until differential and public-packing gates pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import time

from npk.pack import LocalTokenizer, PackSelector
from npk.pack.format import PackError


class FastCount(LocalTokenizer):
    def _count_uncached(self, text):
        if not text: return 0
        try:
            count = len(self._backend.encode_batch_fast([text], add_special_tokens=False)[0])
        except Exception:
            raise PackError('Local tokenizer could not count the supplied text') from None
        if text.strip() and count == 0:
            raise PackError('Local tokenizer discarded all non-whitespace input')
        return count


def sha(body): return hashlib.sha256(body).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))


def run(a):
    if a.output.exists(): raise ValueError('Fresh challenger output required')
    from tokenizers import Tokenizer
    a.output.mkdir(parents=True)
    cfg = read(a.asset)
    plan = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'asset_sha256': sha(a.asset.read_bytes()),
            'pack_sha256': sha(a.pack.read_bytes()), 'tasks_sha256': sha(a.tasks.read_bytes()),
            'code_sha256': sha(Path(__file__).read_bytes()), 'budgets': [512, 2048, 8192],
            'profile_repeats': 3, 'seed': 2912,
            'hypothesis': 'The upstream no-offset path plus Encoding length preserves counts at lower cost',
            'source': 'https://huggingface.co/docs/tokenizers/api/tokenizer#tokenizers.Tokenizer.encode_batch_fast',
            'limits': ['One explicit tokenizer asset; no general equivalence theorem',
                       'Every profiled selection has exact full-assembly counts; no additive admission',
                       'Each query starts with an empty exact-text cache, with models already loaded',
                       'CPU process and uncontrolled host, not a deployment latency guarantee']}
    (a.output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    (a.output/'execution-source.py').write_bytes(Path(__file__).read_bytes())
    backend = Tokenizer.from_file(str(a.asset)); backend.no_padding(); backend.no_truncation()
    corpus = {}
    for p in sorted((a.seed/'contexts').glob('*.txt')):
        raw = p.read_bytes(); assert sha(raw) == p.stem; corpus[p.stem] = raw.decode()
    # Boundary, Unicode, and all explicitly added tokens, including spellings
    # that the ordinary pre-tokenizer would split differently.
    rng = random.Random(2912)
    for t in cfg.get('added_tokens', []):
        for s in (t['content'], 'x '+t['content']+' y', '\n'+t['content']+'\n'):
            corpus[sha(s.encode())] = s
    for _ in range(500):
        text = ''.join(rng.choice(['a', '界', '\u0301', '\r\n', '\n\n', ' ', '😀', '/', '42', '\x00'])
                       for _ in range(rng.randrange(1, 90)))
        corpus[sha(text.encode())] = text
    checked = []
    for digest, text in corpus.items():
        ordinary = backend.encode(text, add_special_tokens=False)
        fast = backend.encode_batch_fast([text], add_special_tokens=False)[0]
        assert fast.ids == ordinary.ids and len(fast) == len(ordinary.ids), 'No-offset token IDs differ'
        checked.append({'text_sha256': digest, 'tokens': len(fast)})
    (a.output/'differential.json').write_text(json.dumps(checked), encoding='utf-8')
    counters = {'ordinary': LocalTokenizer(a.asset), 'no_offsets': FastCount(a.asset)}
    selectors = {name: PackSelector(a.pack, tokenizer=counter) for name, counter in counters.items()}
    rows = []; tasks = read(a.tasks)['tasks']
    for task in tasks:
        for budget in plan['budgets']:
            contexts = {}
            for repeat in range(plan['profile_repeats']):
                order = list(counters); rng.shuffle(order)
                for name in order:
                    counters[name].clear_cache()
                    started = time.perf_counter(); cpu = time.process_time()
                    result = selectors[name].select(task['query'], budget_tokens=budget)
                    wall = 1000*(time.perf_counter()-started); processor = 1000*(time.process_time()-cpu)
                    text = result.context_text()
                    exact = len(backend.encode(text, add_special_tokens=False))
                    assert exact == result.total_tokens <= budget
                    assert result.query == task['query'] and not result.used_generative_llm
                    digest = sha(text.encode())
                    if contexts: assert digest == next(iter(contexts.values())), 'Public selection differs'
                    contexts[name] = digest
                    rows.append({'task': task['task_id'], 'budget': budget, 'repeat': repeat, 'arm': name,
                                 'tokens': exact, 'context_sha256': digest, 'wall_ms': wall, 'cpu_ms': processor,
                                 'fallback': result.seed_failed})
            (a.output/'partial.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        print({'phase': 'profile', 'task': task['task_id'], 'rows': len(rows)}, flush=True)
    summaries = [{'arm': name, 'budget': budget,
                  'median_wall_ms': statistics.median(r['wall_ms'] for r in rows if r['arm'] == name and r['budget'] == budget)}
                 for name in counters for budget in plan['budgets']]
    assert sha(Path(__file__).read_bytes()) == plan['code_sha256']
    report = {'status': 'COMPLETE', 'evidence_mode': 'LOCAL', 'generative_calls': 0,
              'differential_cases': len(checked), 'rows': rows, 'summary': summaries,
              'plan_sha256': sha((a.output/'plan.json').read_bytes())}
    (a.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print({'status': 'COMPLETE', 'differential_cases': len(checked), 'summary': summaries}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('pack', 'tasks', 'asset', 'seed', 'output'): p.add_argument('--'+name, type=Path, required=True)
    run(p.parse_args())

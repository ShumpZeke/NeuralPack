import json
from pathlib import Path

path = Path('experiments/results/incremental/raw.jsonl')
if not path.exists():
    print('No results')
    raise SystemExit(0)

lines = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
ops = sorted(set(x['operation'] for x in lines))
for op in ops:
    print(f'=== {op} ===')
    sub = [x for x in lines if x['operation'] == op]
    for cand in sorted(set(x['candidate'] for x in sub)):
        c_rows = [x for x in sub if x['candidate'] == cand]
        avg_up = sum(x['update_ms'] for x in c_rows) / len(c_rows)
        avg_rebuild = sum(x['full_rebuild_ms'] for x in c_rows) / len(c_rows)
        saving = avg_rebuild - avg_up
        pct = (saving / avg_rebuild) * 100 if avg_rebuild else 0
        print(f'  {cand:12s}: update={avg_up:6.2f}ms, rebuild={avg_rebuild:6.2f}ms, saving={saving:6.2f}ms ({pct:4.1f}%)')

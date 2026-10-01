"""D1: does a code-trained bi-encoder lift gold blocks out of the lexical tail?

For pandas and mypy issues on gym-dev: take the lexical ranking (the product's
weighted query) to depth DEPTH, embed the query and those blocks with
gte-modernbert-base (CLS pooling, normalized; offline, pinned), and compare the
rank of the first gold block under lexical order, dense order and RRF(lexical,
dense). Usage: dense_diag.py [repo ...]
"""
import importlib
import json
import os
import sys
import time

sys.path.insert(0, "/home/user/NeuralPack")
os.environ.setdefault("NPK_BENCH_HOME", "/home/user/npk-data")
import torch
from transformers import AutoModel, AutoTokenizer

from benchmarks.npkbench import data, packs
from npk.pack.format import open_pack

sel = importlib.import_module("npk.pack.select")
DEPTH = int(os.environ.get("DEPTH", "500"))
MAXLEN = int(os.environ.get("MAXLEN", "256"))
REPOS = set(sys.argv[1:]) or {"pandas-dev/pandas", "python/mypy"}
torch.set_num_threads(int(os.environ.get("THREADS", "2")))
CACHE = "/home/user/NeuralPack/experiments/models/hf_cache"
REV = "e7f32e3c00f91d699e8c43b53106206bcc72bb22"
kw = dict(cache_dir=CACHE, revision=REV, local_files_only=True, trust_remote_code=False)
tok = AutoTokenizer.from_pretrained("Alibaba-NLP/gte-modernbert-base", **kw)
model = AutoModel.from_pretrained("Alibaba-NLP/gte-modernbert-base", use_safetensors=True, **kw).eval()


def embed(texts, batch=16):
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), batch):
            enc = tok(texts[i:i + batch], max_length=MAXLEN, padding=True, truncation=True, return_tensors="pt")
            vec = model(**enc).last_hidden_state[:, 0]
            out.append(torch.nn.functional.normalize(vec, dim=-1))
    return torch.cat(out)


def first_gold(order, gold_ids):
    return next((r for r, b in enumerate(order) if b in gold_ids), None)


results = []
started = time.time()
for task in data.split("gym-dev"):
    if task.repo not in REPOS:
        continue
    packs.ensure_pack(task)
    with open_pack(packs.pack_path(task)) as con:
        query = sel._strip_issue_template(task.query)
        lex = sel._lexical_channel(con, query, DEPTH, sel.TITLE_WEIGHT, sel.TF_CAP)
        if not lex:
            continue
        rows = con.execute(
            f"SELECT b.id, f.path, b.start_line, b.end_line, b.text FROM blocks b JOIN files f ON f.id=b.file_id "
            f"WHERE b.id IN ({','.join('?' * len(lex))})", lex).fetchall()
        info = {r[0]: r for r in rows}
        gold_ids = {b for b in lex if any(h.found_by([(info[b][1], info[b][2], info[b][3])]) for h in task.hunks)}
        qv = embed([query[:4000]])
        bv = embed([f"{info[b][1]}\n{info[b][4]}" for b in lex])
        sims = (bv @ qv.T).squeeze(1).tolist()
        dense = [b for _, b in sorted(zip([-s for s in sims], lex))]
        dense_rank = {b: r for r, b in enumerate(dense)}
        rrf = sorted(lex, key=lambda b: -(1 / (60 + lex.index(b)) + 1 / (60 + dense_rank[b])))
        results.append({"id": task.instance_id, "gold_in_depth": bool(gold_ids),
                        "lex": first_gold(lex, gold_ids), "dense": first_gold(dense, gold_ids),
                        "rrf": first_gold(rrf, gold_ids)})
        print(json.dumps(results[-1]), round(time.time() - started), "s", flush=True)
json.dump(results, open(f"/tmp/claude-0/-home-user-NeuralPack/41890f36-07b3-5e02-9885-0b9280cb882f/scratchpad/dense_diag_{DEPTH}.json", "w"))
for key in ("lex", "dense", "rrf"):
    ranks = [r[key] for r in results if r[key] is not None]
    print(key, "gold ranked", len(ranks), "| top10", sum(r < 10 for r in ranks), "| top60", sum(r < 60 for r in ranks),
          "| median", sorted(ranks)[len(ranks) // 2] if ranks else None)

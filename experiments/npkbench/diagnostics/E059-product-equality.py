"""E059: the product's default selects exactly as the prototype arm on every issue of the harm check."""
import gzip
import json
import sys
from pathlib import Path

RUNS = Path("experiments/npkbench/runs")
PAIRS = [("gym-heldout-b", "E059-env-gymheldoutb", "E059p-product-gymheldoutb"),
         ("gym-dev", "E059-env-gymdev", "E059p-product-gymdev"),
         ("poly-dev-b", "E059-env-polydevb", "E059p-product-polydevb"),
         ("ood-multi-dev", "E059-env-multidev", "E059p-product-multidev"),
         ("ood-multi-sample", "E059-env-multisample", "E059p-product-multisample")]


def spans(run, arm):
    out = {}
    for line in gzip.open(RUNS / run / "rows.jsonl.gz", "rt"):
        r = json.loads(line)
        if r["arm"].split("@")[0] == arm:
            out[(r["arm"].partition("@")[2] or "fix", r["budget"], r["instance_id"])] = r["spans"]
    return out


total = same = 0
for split, proto, product in PAIRS:
    if not (RUNS / product / "summary.json").exists():
        print(f"{split}: {product} not finished")
        continue
    a, b = spans(proto, "e059_env"), spans(product, "npk_default")
    cells = set(a) | set(b)
    equal = sum(1 for k in cells if a.get(k) == b.get(k))
    issues = len({k[2] for k in cells})
    print(f"{split}: {issues} issues, {len(cells)} cells, {equal} identical")
    total += len(cells)
    same += equal
print(f"total: {same} of {total} cells identical")
sys.exit(0 if total and same == total else 1)

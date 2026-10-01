"""E059: apply the declared harm check to each split and show the per-repository effect."""
import collections
import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())
from benchmarks.npkbench import report

RUNS = Path("experiments/npkbench/runs")
SPLITS = [
    ("gym-heldout-b", "E058d-confirm-gymheldoutb", "E059-env-gymheldoutb"),
    ("gym-dev", "E058-coverage-gymdev", "E059-env-gymdev"),
    ("poly-dev-b", "E058-coverage-polydevb", "E059-env-polydevb"),
    ("ood-multi-dev", "E058b-coverage-multidev", "E059-env-multidev"),
    ("ood-multi-sample", "E058d-guard-multisample", "E059-env-multisample"),
]


def rows(run, arm):
    out = {}
    for line in gzip.open(RUNS / run / "rows.jsonl.gz", "rt"):
        r = json.loads(line)
        if r["arm"].split("@")[0] == arm:
            out[(r["arm"].partition("@")[2] or "fix", r["budget"], r["instance_id"])] = (r["hunk_recall"], r["repo"])
    return out


verdicts = []
for split, base_run, cand_run in SPLITS:
    if not (RUNS / cand_run / "summary.json").exists():
        print(f"{split}: {cand_run} not finished")
        continue
    result = report.judge(RUNS / base_run, "npk_default", "e059_env", targets=("", "@tests"),
                          candidate_run=RUNS / cand_run)
    print(f"== {split} ({cand_run} against the default arm of {base_run})")
    print(report.render_judgement(result))
    verdicts.append((split, result["utility_nonnegative"] and result["no_significant_loss"]))
    base, cand = rows(base_run, "npk_default"), rows(cand_run, "e059_env")
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    changed = collections.defaultdict(set)
    for key, (value, repo) in cand.items():
        if key in base:
            per[repo][key[0]].append((key[1], value - base[key][0]))
            if value != base[key][0]:
                changed[repo].add(key[2])
    n = collections.Counter(repo for (t, b, i), (v, repo) in cand.items() if t == "fix" and b == 1024)
    for repo in sorted(per):
        cells = []
        for target in ("fix", "tests"):
            by_budget = collections.defaultdict(list)
            for b, d in per[repo][target]:
                by_budget[b].append(d)
            cells.append(" ".join(f"{sum(v) / len(v) * 100:+6.2f}" for b, v in sorted(by_budget.items())))
        print(f"   {repo:28s} n={n[repo]:3d} issues changed={len(changed[repo]):2d} | fix {cells[0]} | tests {cells[1]}")
print("harm check (utility >= 0 at every budget and no significant loss):", verdicts)

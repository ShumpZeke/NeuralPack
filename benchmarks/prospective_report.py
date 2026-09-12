"""Report frozen multi-budget answer trials without hiding missing observations.

Curves share one completed task cohort across every retrieval method and budget.
That diagnostic is accompanied by the full planned-task table and every error;
it is not an estimate of success on requests lost to transport failures.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from benchmarks.repository_eval import grade_answer


def mean(values):
    return statistics.mean(values) if values else None


def median(values):
    return statistics.median(values) if values else None


def arm_key(row):
    return row["method"], row["budget"]


def pareto(points):
    """EMPIRICAL: observed two-objective nondominance; no interpolation/minimum claim."""
    valid=[p for p in points if p["mean_input_tokens"] is not None and p["success_rate"] is not None]
    return [p for p in valid if not any(
        q["mean_input_tokens"]<=p["mean_input_tokens"] and q["success_rate"]>=p["success_rate"] and
        (q["mean_input_tokens"]<p["mean_input_tokens"] or q["success_rate"]>p["success_rate"])
        for q in valid)]


def summarize(data):
    expected={t["id"]:t["answer"] for t in data["plan"]["dataset"]["tasks"]}
    rows=data["rows"]
    groups={}; scores={}; grades={}; observed=set()
    for row in rows:
        key=(*arm_key(row),row["task"])
        if key in observed:
            raise ValueError("duplicate task/method/budget observation")
        if row["task"] not in expected:
            raise ValueError("unknown task")
        observed.add(key)
        groups.setdefault(arm_key(row),[]).append(row)
        if row.get("transport_success"):
            grade=grade_answer(row.get("content"),expected[row["task"]])
            if grade["task_success"] is not row["task_success"]:
                raise ValueError("stored grade disagrees with the frozen executable answer")
            scores[key]=grade["task_success"]
            grades[key]=grade
    planned={(*arm_key(r),r["task"]) for r in data["plan"]["observations"]}
    if observed!=planned:
        raise ValueError("results omit or add frozen observations")

    arms=[]
    for (method,budget),group in sorted(groups.items()):
        complete=[r for r in group if r.get("transport_success")]
        prompt=[r["usage"]["prompt_tokens"] for r in complete
                if (r.get("usage") or {}).get("prompt_tokens") is not None]
        output=[r["usage"]["completion_tokens"] for r in complete
                if (r.get("usage") or {}).get("completion_tokens") is not None]
        cached=[r["usage"]["prompt_tokens_details"]["cached_tokens"] for r in complete
                if ((r.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens") is not None]
        successes=sum(scores[(method,budget,r["task"])] for r in complete)
        arms.append({"method":method,"budget":budget,"planned":len(group),
                     "completed":len(complete),"strict_json_successes":successes,
                     "success_rate_completed":successes/len(complete) if complete else None,
                     "observed_successes_per_planned":successes/len(group) if group else None,
                     "transport_errors":sum(r.get("transport_success") is False for r in group),
                     "selection_failures":sum(r["evidence_mode"]=="SELECTION_FAILED" for r in group),
                     "pending_or_replay_miss":sum(r["evidence_mode"] in {"PENDING","REPLAY_MISS"} for r in group),
                     "parse_errors":sum(grades[(method,budget,r["task"])]["parse_error"] for r in complete),
                     "top_level_key_errors":sum(
                         not grades[(method,budget,r["task"])]["parse_error"] and
                         (not isinstance(grades[(method,budget,r["task"])]["parsed"],dict) or
                          grades[(method,budget,r["task"])]["parsed"].keys()!=expected[r["task"]].keys())
                         for r in complete),
                     "output_limit_hits":sum(any(c.get("finish_reason")=="length" for c in
                                                 r.get("raw_response",{}).get("choices",[])) for r in complete),
                     "mean_selected_tokens":mean([r["selected_tokens"] for r in group]),
                     "median_selection_ms":median([r["selection_ms"] for r in group if "selection_ms" in r]),
                     "answers_reporting_input_usage":len(prompt),"mean_input_tokens":mean(prompt),
                     "median_input_tokens":median(prompt),"mean_output_tokens":mean(output),
                     "answers_reporting_cached_usage":len(cached),"mean_cached_tokens":mean(cached),
                     "median_answer_ms":median([r["latency_ms"] for r in complete if "latency_ms" in r]),
                     "distinct_requests":len({r["request_sha256"] for r in group})})

    pairs=[]
    for method,budget in sorted(groups):
        if budget is None or method=="bm25_windows":
            continue
        baseline="bm25_windows"
        tasks=[t for t in expected if (method,budget,t) in scores and (baseline,budget,t) in scores]
        pairs.append({"method":method,"baseline":baseline,"budget":budget,"completed_pairs":len(tasks),
                      "wins":sum(scores[(method,budget,t)] and not scores[(baseline,budget,t)] for t in tasks),
                      "losses":sum(not scores[(method,budget,t)] and scores[(baseline,budget,t)] for t in tasks),
                      "ties":sum(scores[(method,budget,t)]==scores[(baseline,budget,t)] for t in tasks)})

    retrieval_keys=[key for key in groups if key[1] is not None]
    cohort=[t for t in expected if retrieval_keys and all((*key,t) in scores for key in retrieval_keys)]
    points=[]
    for method,budget in sorted(retrieval_keys):
        group=[r for r in groups[(method,budget)] if r["task"] in cohort]
        prompt=[r["usage"]["prompt_tokens"] for r in group
                if (r.get("usage") or {}).get("prompt_tokens") is not None]
        successes=sum(scores[(method,budget,t)] for t in cohort)
        points.append({"method":method,"budget":budget,"cohort_tasks":len(cohort),
                       "successes":successes,"success_rate":successes/len(cohort) if cohort else None,
                       # Incomplete token usage cannot yield an apparently cheap point.
                       "mean_input_tokens":mean(prompt) if len(prompt)==len(cohort) else None,
                       "median_selection_ms":median([r["selection_ms"] for r in group if "selection_ms" in r])})

    # Count API observations once per request. REPLAY can refer to an already paid call.
    unique={}
    for row in rows:
        key=row["request_sha256"]
        if key not in unique or row.get("api_attempts_this_run",0)>unique[key].get("api_attempts_this_run",0):
            unique[key]=row
    usage_rows=[r for r in unique.values() if r.get("transport_success")]
    usage={}
    for field in ("prompt_tokens","completion_tokens","total_tokens"):
        values=[r["usage"][field] for r in usage_rows if (r.get("usage") or {}).get(field) is not None]
        usage[field]={"reported_total":sum(values) if values else None,"requests_reporting":len(values)}

    tasks=[{"task":t,"results":[{"method":m,"budget":b,"success":scores.get((m,b,t))}
                                for m,b in sorted(groups)]} for t in expected]
    return {"evidence_modes":dict(Counter(r["evidence_mode"] for r in rows)),
            "plan_sha256":data["plan_sha256"],"settings":data["plan"]["settings"],
            "corpus_tokens":data["plan"]["corpus_tokens"],"available_tokens":data["plan"]["available_tokens"],
            "answer_attempts_in_ledger":data["answer_attempts_in_ledger"],
            "requests_with_execution_code_stamp":sum(bool(r.get("execution_code_sha256")) for r in unique.values()
                                                      if r.get("api_attempts_this_run",0)),
            "unique_request_usage":usage,"generative_optimization_calls":data["generative_optimization_calls"],
            "arms":arms,"paired_same_budget":pairs,"common_completed_tasks":cohort,
            "common_cohort_curves":points,"empirical_input_quality_frontier":pareto(points),"tasks":tasks,
            "errors":[{k:r.get(k) for k in ("task","method","budget","http_status","error_type","error_detail")}
                      for r in rows if r.get("transport_success") is False],
            "limitations":[*data["plan"].get("limitations",[]),
                           "Repeated budgets and exact-prompt replays are correlated observations, not independent trials",
                           "The completed cohort excludes any task with a missing retrieval answer; all planned counts remain visible",
                           "Empirical frontier covers observed input-token/answer-success points only, excluding local compute and billing",
                           "Full and no-context controls are reference conditions, not matched-budget retrieval competitors",
                           "Two concurrent requests and uncontrolled endpoint caching/load make answer latency observational"]}


def markdown(report):
    lines=["# Prospective Click answer-quality budget sweep", "",
           f"Available context per question: **{report['available_tokens']:,} estimated tokens**. "
           f"Answer attempts: **{report['answer_attempts_in_ledger']}**; generative selection calls: **0**.", "",
           "Success requires the entire requested JSON object to match an executable oracle. "
           "Errors are separate from completed-answer success. N/A means unobserved or undefined.", "",
           "| Method | Estimated context budget | Correct / completed | Errors / pending / selection failures | Mean actual input tokens | Local selection median ms |",
           "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for arm in report["arms"]:
        value=lambda x: "N/A" if x is None else f"{x:,.1f}"
        lines.append(f"| {arm['method']} | {arm['budget'] or 'reference'} | "
                     f"{arm['strict_json_successes']} / {arm['completed']} | "
                     f"{arm['transport_errors']} / {arm['pending_or_replay_miss']} / {arm['selection_failures']} | "
                     f"{value(arm['mean_input_tokens'])} | {value(arm['median_selection_ms'])} |")
    lines += ["", "| Same-budget comparison against BM25 windows | Budget | Wins / losses / ties |",
              "| --- | ---: | ---: |"]
    for pair in report["paired_same_budget"]:
        lines.append(f"| {pair['method']} | {pair['budget']} | {pair['wins']} / {pair['losses']} / {pair['ties']} |")
    lines += ["", f"The plotted common completed cohort contains **{len(report['common_completed_tasks'])}** tasks. "
              "Its observed frontier is a diagnostic, not a claim of optimality or generalization.", ""]
    lines += ["- "+text for text in report["limitations"]]
    return "\n".join(lines)+"\n"


def plot(report,path,*,title_prefix=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,5.5))
    methods=sorted({p['method'] for p in report['common_cohort_curves']})
    colors=plt.get_cmap('tab10');markers=('o','s','^','D','v','P','X')
    styles={method:(colors(i%10),markers[i%len(markers)]) for i,method in enumerate(methods)}
    for method,(color,marker) in styles.items():
        points=[p for p in report["common_cohort_curves"] if p["method"]==method and
                p["mean_input_tokens"] is not None and p["success_rate"] is not None]
        if not points:
            continue
        ax.plot([p["mean_input_tokens"] for p in points],[100*p["success_rate"] for p in points],
                color=color,marker=marker,label=method,linewidth=1.4)
    frontier=report["empirical_input_quality_frontier"]
    if frontier:
        ax.scatter([p["mean_input_tokens"] for p in frontier],[100*p["success_rate"] for p in frontier],
                   s=150,facecolors="none",edgecolors="#222222",linewidths=1.1,label="Observed nondominated points")
    if any(p["mean_input_tokens"] for p in report["common_cohort_curves"]):
        ax.set_xscale("log")
        ax.legend(loc="best",fontsize=9)
    ax.set_ylim(-3,103);ax.set_ylabel("Entire answer correct (%)")
    ax.set_xlabel("Mean provider-reported input tokens per task (log scale)")
    ax.set_title((title_prefix+'\n' if title_prefix else '')+f"Click 8.5.0 · {len(report['common_completed_tasks'])} common completed tasks\n"
                 "Same questions across every method and budget")
    ax.grid(True,alpha=.2)
    budgets=', '.join(f'{b:,}' for b in sorted({p['budget'] for p in report['common_cohort_curves']}))
    fig.text(.02,.015,f"Estimated context budgets swept: {budgets}. Lines guide the eye; intermediate budgets were not tested.\n"
             "Small developer-authored workload; one model configuration. Missing tasks are disclosed in the report.",fontsize=8)
    fig.tight_layout(rect=(0,.075,1,1));fig.savefig(path,dpi=160);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--plot",type=Path)
    args=parser.parse_args()
    report=summarize(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report),encoding="utf-8")
    if args.plot:
        plot(report,args.plot)
    print({"report":str(args.output),"arms":len(report["arms"]),
           "common_completed_tasks":len(report["common_completed_tasks"]),
           "answer_attempts":report["answer_attempts_in_ledger"]})


if __name__=="__main__":
    main()

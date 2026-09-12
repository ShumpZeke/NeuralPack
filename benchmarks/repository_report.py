"""Summarize frozen repository answers, keeping protocol and transport failures visible."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import statistics

from benchmarks.repository_eval import grade_answer


def fence_normalized_answer(content):
    """Ignore one enclosing Markdown fence, never extract a favorable subanswer."""
    if not isinstance(content,str):
        return content
    match=re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n```\s*",content,re.DOTALL)
    return match.group(1) if match else content


def summarize(data):
    expected={t["id"]:t["answer"] for t in data["dataset"]["tasks"]}
    answers=[r for r in data["rows"] if r["evidence_mode"]!="LOCAL"]
    arms=sorted({r["arm"] for r in answers})
    normalized={}
    reports=[]
    for arm in arms:
        group=[r for r in answers if r["arm"]==arm]
        completed=[r for r in group if r.get("transport_success")]
        for row in completed:
            normalized[(arm,row["task"])]=grade_answer(fence_normalized_answer(row.get("content")),expected[row["task"]])["task_success"]
        prompt=[r["usage"]["prompt_tokens"] for r in completed if r.get("usage") and r["usage"].get("prompt_tokens") is not None]
        completion=[r["usage"]["completion_tokens"] for r in completed if r.get("usage") and r["usage"].get("completion_tokens") is not None]
        cache_rows=[r for r in completed if r.get("usage") and
                    (r["usage"].get("prompt_tokens_details") or {}).get("cached_tokens") is not None]
        cached=[r["usage"]["prompt_tokens_details"]["cached_tokens"] for r in cache_rows]
        reports.append({"arm":arm,"tasks_planned":len(group),"completed_answers":len(completed),
                        "strict_json_successes":sum(bool(r.get("task_success")) for r in completed),
                        "fence_normalized_successes":sum(normalized[(arm,r["task"])] for r in completed),
                        "parse_errors":sum(bool(r.get("parse_error")) for r in completed),
                        "output_limit_hits":sum(any(c.get("finish_reason")=="length" for c in
                                                    r.get("raw_response",{}).get("choices",[])) for r in completed),
                        "missing_or_transport_errors":len(group)-len(completed),
                        "reported_input_tokens_total":sum(prompt) if prompt else None,
                        "reported_input_tokens_median":statistics.median(prompt) if prompt else None,
                        "reported_output_tokens_total":sum(completion) if completion else None,
                        "answers_with_cache_usage":len(cache_rows),
                        "reported_cached_input_tokens_total":sum(cached) if cached else None,
                        "median_answer_ms":statistics.median(r["latency_ms"] for r in completed) if completed else None})
    comparisons=[]
    for arm in arms:
        if arm=="bm25_windows":
            continue
        tasks=[task for task in expected if (arm,task) in normalized and ("bm25_windows",task) in normalized]
        comparisons.append({"arm":arm,"baseline":"bm25_windows","paired_completed_tasks":len(tasks),
                            "wins":sum(normalized[(arm,t)] and not normalized[("bm25_windows",t)] for t in tasks),
                            "losses":sum(not normalized[(arm,t)] and normalized[("bm25_windows",t)] for t in tasks),
                            "ties":sum(normalized[(arm,t)]==normalized[("bm25_windows",t)] for t in tasks)})
    task_results=[{"task":t,"fence_normalized_success":{a:normalized.get((a,t)) for a in arms}} for t in expected]
    return {"assessment":"Requires review; the summarizer does not promote a method",
            "evidence_modes":sorted({r["evidence_mode"] for r in answers}),
            "arms":reports,"paired_fence_normalized_comparisons":comparisons,"tasks":task_results,
            "limitations":["Small curated developer-known workload and one target model; not independent validation",
                           "Primary score requires the requested exact JSON object; secondary only removes an enclosing Markdown fence",
                           "Source spans are diagnostics, not a proof of sufficient evidence",
                           "Retrieval budgets use chars/4; actual target token usage is reported separately",
                           "Timing is sequential single-run observation; provider cache effects are uncontrolled",
                           "Endpoint cache and concurrent service load are uncontrolled; latency is observational",
                           "No verified dollar billing rate; no dollar savings claim"],
            "generative_optimization_calls":data["generative_optimization_calls"],
            "api_attempts_this_run":data["live_api_attempts"],"retrieval_summaries":data["summaries"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=summarize(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report["arms"],indent=2))


if __name__=="__main__":
    main()

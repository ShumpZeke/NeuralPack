"""Bind cycle-14 conclusions to exact artifacts and final product code."""
import gzip
import hashlib
import json
from pathlib import Path
import statistics as st
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    repo = Path(__file__).resolve().parents[1]; out = repo/'experiments/results'
    hashes = {p.relative_to(repo).as_posix():sha(p) for p in (repo/'npk').rglob('*.py')}
    profile = json.loads(gzip.decompress((out/'cycle14-storage-profile.json.gz').read_bytes()))
    mutations = json.loads((out/'cycle14-mutations.json').read_text())
    assert profile['candidate_hashes'] == mutations['source_hashes'] == hashes
    assert not profile['evidence_differences'] and all(r['status']=='KILLED' for r in mutations['rows'])
    tests = ET.parse(out/'cycle14-acceptance-final.xml').find('.//testsuite').attrib
    secrets = ET.parse(out/'cycle14-secret-acceptance.xml').find('.//testsuite').attrib
    assert tests['failures']==tests['errors']==secrets['failures']==secrets['errors']=='0'
    arms = {}
    for arm in ('champion','candidate'):
        rows = [r for r in profile['rows'] if r['arm']==arm]
        arms[arm] = {key:st.median(r[key] for r in rows) for key in ('compile_ms','verify_ms','noop_ms','warm_median_ms')}
        arms[arm]['updates_ms'] = {operation:st.median(u['update_ms'] for r in rows for u in r['updates'] if u['operation']==operation)
                                   for operation in ('small_file','large_file','one_percent','ten_percent')}
    answer = json.loads((out/'cycle14-answers.json').read_text())
    archive = json.loads((out/'cycle14-archive-scan.json').read_text())
    result = {'verdict':'PIVOT REQUIRED','champion_before':profile['champion_commit'],
              'default_runtime':'deterministic BM25; zero generative calls; no API key; graph off',
              'kept':['known metadata-value/content validation','stronger mutation tripwires','pinned external source and executable regressions'],
              'not_promoted':['Qwen semantic sidecar','fielded BM25','hybrid fields/Qwen','graph expansion'],
              'failing_before_regression_cases':15,'final_test_suite':tests,'post_stage_secret_suite':secrets,
              'product_mutants_killed':28,'grader_mutants_killed':1,'candidate_source_sha256':hashes,
              'local_selections':1080,'local_budget_sweep':[512,2048,8192],
              'live':{k:answer[k] for k in ('plan_sha256','attempts','completed_unique_requests','transport_errors',
                         'unique_reported_input_tokens','unique_reported_output_tokens','generative_optimization_calls','dollar_cost')},
              'paired_cost_medians':arms,'incremental_fresh_equality_checks':sum(len(u['evidence']) for r in profile['rows'] for u in r['updates']),
              'cross_version_evidence_differences':[],'archive_scan':archive,
              'next_hypothesis':'CONJECTURE: hierarchical module/document then passage retrieval improves source relevance more cheaply than global dense retrieval; attack multi-module and absent-source cases',
              'limits':['One model configuration and stochastic observation per unique prompt','Twelve developer-authored new cases, eight share configparser; eight reused Click controls',
                        'Not independent sealed validation','No full-context or remote-preprocessor answer arm in this cycle; no dollar savings claim',
                        'Manifest checks cover known invariants, not arbitrary semantic validity or publisher authentication','Fast queries assume a previously accepted artifact',
                        'Target tokenizers remain advisory; estimates use floor(chars/4)','Risk remains uncalibrated and out-of-corpus retrieval remains weak']}
    paths = [p for p in out.glob('cycle14-*') if p.is_file() and p.name not in ('cycle14-summary.json','cycle14-storage-profile.json')]
    result['artifacts'] = {p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(paths)}
    result['record_code_sha256'] = sha(Path(__file__))
    write_json(out/'cycle14-summary.json',result)
    print({'verdict':result['verdict'],'artifacts':len(paths),'tests':tests['tests'],'skips':tests['skipped'],
           'mutants':29,'live_attempts':answer['attempts'],'archive_matches':archive['recognized_pattern_matches']})


if __name__=='__main__': main()

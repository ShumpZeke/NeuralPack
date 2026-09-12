"""Bind cycle-15 decisions to final code, complete raw reports and acceptance."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    repo = Path(__file__).resolve().parents[1]; out = repo/'experiments/results'
    read = lambda name: json.loads((out/name).read_text())
    current = {p.relative_to(repo).as_posix(): sha(p) for p in (repo/'npk').rglob('*.py')}
    old = read('cycle14-summary.json')['candidate_source_sha256']
    assert all(digest == old[name] for name, digest in current.items() if name.startswith('npk/pack/'))
    mutations = read('cycle15-final-mutations.json')
    assert mutations['source_hashes'] == current
    assert len(mutations['rows']) == 34 and all(r['status'] == 'KILLED' for r in mutations['rows'])
    acceptance = ET.parse(out/'cycle15-final-acceptance.xml').find('.//testsuite').attrib
    secrets = ET.parse(out/'cycle15-secret-acceptance.xml').find('.//testsuite').attrib
    assert acceptance['failures'] == acceptance['errors'] == secrets['failures'] == secrets['errors'] == '0'
    profile = read('cycle15-auditor-profile.json')
    assert profile['source_sha256']['npk/auditor.py'] == current['npk/auditor.py']
    live = {}
    for model in ('nemotron', 'deepseek'):
        report = read(f'cycle15-{model}-answers.json')
        assert report['reporter_sha256'] == sha(repo/'benchmarks/modern_seed_report.py')
        assert report['pending_unique_requests'] == []
        live[model] = {key: report[key] for key in ('plan_sha256', 'attempts', 'completed_unique_requests', 'transport_errors',
                                                  'unique_reported_input_tokens', 'unique_reported_output_tokens', 'generative_optimization_calls', 'dollar_cost')}
    archive = read('cycle15-archive-scan.json')
    assert archive['archive_sha256'] == sha(out/archive['archive']) and archive['recognized_pattern_matches'] == 0
    result = {
        'verdict': 'PIVOT REQUIRED', 'champion_before': '463b38f', 'default_retrieval_changed': False,
        'compiler_query_code_matches_cycle14': True, 'default_generative_calls': 0,
        'kept': ['identified fixture audit schema with undefined metrics and cost N/A', 'complete research-row reconstruction',
                 'scanner read-error accounting', 'executable composed oracles and regression/mutation tripwires'],
        'not_promoted': ['document routing sidecars', 'deferred metadata lookup', 'graph expansion'],
        'failing_before': {'auditor': 21, 'research_report': 6, 'scanner': 3},
        'candidate_source_sha256': current, 'acceptance': acceptance, 'post_stage_secret_scan': secrets,
        'product_mutants_killed': 31, 'grader_report_mutants_killed': 2, 'scanner_mutants_killed': 1,
        'local_selections': 1512, 'local_budgets': [512, 2048, 8192], 'live_budgets': [2048, 8192],
        'available_source_tokens_per_expanded_task': 559738, 'live': live,
        'ranking_equality_checks': {'hierarchy_repeats': 756, 'late_metadata': 300},
        'audit_profile': profile['summary'], 'archive_scan': archive,
        'known_unresolved': ['Legacy pricing registry still labels placeholder provenance as verified',
                            'Legacy benchmark writers still contain accuracy labels and fabricated completion counts',
                            'Target-specific tokenizers remain unimplemented; floor(chars/4) estimates are not token guarantees',
                            'Risk remains uncalibrated and out-of-corpus routing unreliable',
                            'No independent sealed task validation or current full-context/remote-preprocessor economic comparison'],
        'next_hypothesis': 'Repair remaining legacy pricing/reporting; then test deterministic query decomposition plus original-query fusion and constraint preservation',
        'limits': ['Developer-authored composed cases share known component behavior; controls are explicitly previously inspected',
                   'One unique attempt per prompt/model, deduped observations and missing transport outcomes are explicit',
                   'Required-source spans are conservative diagnostics, not answer accuracy or sufficiency proof',
                   'Host timing varies; CPU timer granularity limits short-call measurements; no universal speedup claim',
                   'Evidence integrity checks do not authenticate provider execution or establish independent evaluation']}
    result['artifacts'] = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size}
                           for p in sorted(out.glob('cycle15-*')) if p.is_file() and p.name != 'cycle15-summary.json'}
    result['record_code_sha256'] = sha(Path(__file__))
    write_json(out/'cycle15-summary.json', result)
    print({'verdict': result['verdict'], 'tests': acceptance['tests'], 'skips': acceptance['skipped'],
           'mutants_killed': 34, 'live_attempts': sum(r['attempts'] for r in live.values()),
           'live_answers': sum(r['completed_unique_requests'] for r in live.values()), 'artifacts': len(result['artifacts'])})


if __name__ == '__main__': main()

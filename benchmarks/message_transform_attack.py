"""Capture a LOCAL preservation attack against a specified source snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): raise ValueError('new evidence output required')
    sys.path.insert(0, str(a.package.resolve()))
    from npk.planner import ContextExecutionPlanner
    from npk.context.safety import check_invariants
    from benchmarks.message_transform_cases import cases
    rows = []
    with patch('socket.socket.connect', side_effect=AssertionError('LOCAL attack attempted network')):
        for case in cases():
            original = case['messages']
            output, plan = ContextExecutionPlanner().plan_and_optimize(original)
            rows.append({**case, 'output': output, 'unchanged': output == original,
                         'invariants_pass': check_invariants(original, output).ok,
                         'plan': plan.to_dict()})
    report = {'evidence_mode': 'LOCAL', 'generative_calls': 0, 'rows': rows,
              'code_sha256': {f.relative_to(a.package).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
                              for f in (a.package/'npk').rglob('*.py')},
              'limitations': ['Five targeted preservation counterexamples, not target-model answer accuracy',
                              'An unchanged result is byte preservation for these messages, not a general sufficiency proof']}
    a.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print({'cases': len(rows), 'unchanged': sum(r['unchanged'] for r in rows),
           'changed_but_invariants_pass': [r['id'] for r in rows if not r['unchanged'] and r['invariants_pass']]})


if __name__ == '__main__': main()

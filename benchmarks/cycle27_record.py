"""Reconstruct frozen selections and answers, then archive byte-exact cycle evidence."""
import argparse
import base64
from collections import Counter
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import statistics
from unittest.mock import patch
import xml.etree.ElementTree as ET
from benchmarks.compiled_source_contract import require_compiled_sources
from benchmarks.evidence_diagnostics import Piece,render
from benchmarks.operation_report import build
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from benchmarks.unit_answer_plan import reconstruct,tokens
from npk.pack import verify
from npk.pack.compile import _source_lines
from npk.pack.source_policy import PATTERNS


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def suite(path):return ET.parse(path).find('.//testsuite').attrib


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',action='store_true');args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results';runs=repo/'experiments/runs/packs'
    local=runs/'cycle27-operation-v1';live=runs/'cycle27-operation-live-v1';corpus=runs/'cycle24-sqlalchemy-corpus-v1'
    data=read(local/'results.json');acquired=read(corpus/'acquisition.json');plan=read(live/'plan.json')
    assert data['status']=='COMPLETE' and data['evidence_mode']=='LOCAL' and data['generative_calls']==0
    assert data['source_manifest']==acquired['source_manifest']==plan['source_manifest']
    originals=manifest_sources(corpus/'source',acquired['source_manifest'],'public-source')
    sources={k.removeprefix('public-source/'):_source_lines(v.decode()) for k,v in originals.items()}
    full=render([Piece(path,1,len(lines),'\n'.join(lines)) for path,lines in sorted(sources.items())],True)
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert all(data['code_sha256'][name]==digest for name,digest in current.items())
    with patch('socket.socket.connect',side_effect=AssertionError('Archive audit attempted network')):
        for name in ('fixed2048','semantic2048'):
            pack=runs/'cycle24-unit-retrieval-v3'/(name+'.npk')
            assert sha(pack.read_bytes())==data['corpora'][name]['pack_sha256'] and verify(pack)['ok']
            require_compiled_sources(pack,data['source_manifest'])
        audited=build(local,live)
    assert audited==read(out/'cycle27-operation-answers.json') and audited['status']=='COMPLETE'
    assert sha((live/'plan.json').read_bytes())=='801f6945f1f6526ccbc6ce66e498ee74112d4019519d5df9940d4cfee6b66cd5'
    assert len(plan['observations'])==240 and len(plan['requests'])==217
    assert not read(live/'failure-pauses.json')['active']
    tasks={t['id']:t for t in data['tasks']};cells={}
    for row in data['rows']:
        pieces,context=reconstruct(row,sources);task=tasks[row['task']]
        assert (local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
        assert all(row[k]==value for k,value in source_coverage(pieces,task['required']).items())
        assert row['corpus_tokens']==data['corpora']['fixed2048']['corpus_tokens']
        assert row['available_tokens']==data['corpora']['fixed2048']['available_tokens']
        assert row['baseline_prompt_tokens_estimate']==tokens(f'SOURCE\n{full}\n\nQUESTION\n{task["question"]}')
        assert row['selected_prompt_tokens_estimate']==tokens(f'SOURCE\n{context}\n\nQUESTION\n{task["question"]}')
        cells.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    assert len(data['rows'])==2880 and len(cells)==len(data['unique'])==960
    assert set(cells)=={(task,method,budget) for task in tasks for method in data['methods'] for budget in data['budgets']}
    for row in data['unique']:
        group=cells[row['task'],row['method'],row['budget']]
        assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
        assert row=={k:v for k,v in group[0].items() if k not in ('trial','latency_ms')}|{'median_ms':statistics.median(r['latency_ms'] for r in group)}
    for point in data['summary']:
        group=[r for r in data['unique'] if all(r[k]==point[k] for k in ('cohort','layout','method','budget'))]
        assert len(group)==point['tasks']==10
        assert sum(r['all_required_spans'] for r in group)==point['all_required_passages']
        assert statistics.median(r['median_ms'] for r in group)==point['median_ms']
        assert statistics.mean(r['selected_tokens'] for r in group)==point['mean_selected_tokens']
    oracle=read(out/'cycle27-operation-tasks.json');assert oracle['repetitions']==2 and len(oracle['tasks'])==10
    assert oracle['oracle_source_sha256']==sha((repo/'benchmarks/operation_oracles.py').read_bytes())
    assert oracle['helper_source_sha256']==sha((repo/'benchmarks/sqlalchemy_oracles.py').read_bytes())
    assert sha((out/'cycle27-operation-tasks.json').read_bytes())==data['new_oracle_sha256']
    proof=read(out/'cycle27-encoder-input-proof.json');assert proof['requests']==40 and proof['identical_padded_inputs']==20
    assert {r['task'] for r in proof['rows']}==set(tasks) and len(proof['input_groups'])==21
    groups={}
    for row in proof['rows']:
        digest=sha(json.dumps(row['features'],sort_keys=True,separators=(',',':')).encode())
        assert digest==row['encoder_input_sha256'];groups.setdefault(digest,[]).append(row['task'])
    assert groups==proof['input_groups']
    padded=[r['features'] for r in proof['rows'] if r['layout']=='padded']
    assert len(padded)==20 and all(features==padded[0] for features in padded)
    print({'source_selections_reconstructed':len(data['rows']),'unique_cells':len(cells),
           'terminal_payloads':len(plan['requests']),'answer_observations_regraded':len(plan['observations']),
           'final_operation_views_equivalent':audited['current_operation_view_equivalence'],
           'accounting':audited['attempt_accounting']},flush=True)
    if not args.archive:return
    archive=out/'cycle27-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    acceptance=suite(out/'cycle27-final-acceptance.xml')
    assert acceptance['failures']==acceptance['errors']=='0' and int(acceptance['tests'])-int(acceptance['skipped'])==803
    mutations=read(out/'cycle27-final-mutations.json')
    assert len(mutations['rows'])==73 and Counter(r['status'] for r in mutations['rows'])=={'KILLED':73}
    assert mutations['source_hashes']==current
    for name,failures in (('view-contracts-before',2),('unicode-before',3),('rate-limit-before',2)):
        before=suite(out/('cycle27-'+name+'.xml'));assert int(before['failures'])==failures and before['errors']=='0'
    for name in ('view-contracts-after','unicode-after','final-contracts'):
        after=suite(out/('cycle27-'+name+'.xml'));assert after['failures']==after['errors']=='0'
    files={};blobs={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(pattern.search(text) for _,pattern in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body):
        assert name not in files;screen(body);digest=sha(body);files[name]=digest;blobs[digest]=base64.b64encode(body).decode()
    for name,body in originals.items():add(name,body)
    add('corpus/acquisition.json',(corpus/'acquisition.json').read_bytes())
    license_body=(corpus/'LICENSE.txt').read_bytes();assert sha(license_body)==acquired['license_sha256'];add('LICENSE.txt',license_body)
    executed=read(local/'execution-sources.json');assert set(executed)==set(data['code_sha256'])
    for name,text in executed.items():
        body=text.encode();assert sha(body)==data['code_sha256'][name];add('local/execution/'+name,body)
    for p in sorted(local.glob('*.json')):add('local/'+p.name,p.read_bytes())
    for p in sorted((local/'contexts').glob('*.txt')):add('local/contexts/'+p.name,p.read_bytes())
    for p in sorted(live.rglob('*')):
        if not p.is_file():continue
        if p.name=='preparation-sources.json.gz':
            body=p.read_bytes();assert sha(body)==plan['preparation_sources_sha256']
            decoded=gzip.decompress(body);add('live/preparation-sources.decoded.json',decoded)
            for name,item in json.loads(decoded).items():
                source=item['text'].encode();assert sha(source)==item['sha256'];add('live/preparation/'+name,source)
        else:
            assert p.suffix in ('.json','.txt','.py','.sha256'), 'Unexpected archive file type'
            add('live/'+p.relative_to(live).as_posix(),p.read_bytes())
    for entry in read(live/'ledger.json').values():
        if entry['result']['evidence_mode']!='LIVE':continue
        for name,digest in entry['result']['execution_code_sha256'].items():
            p=live/'execution-sources'/(Path(name).stem+'-'+digest+'.py');assert sha(p.read_bytes())==digest
    for p in sorted((runs/'cycle27-view-before').glob('*.py')):add('before-focused-fallback/'+p.name,p.read_bytes())
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for name in ('research/CYCLE27_OPERATION_QUERIES.md','research/math/TRUNCATED_QUERY_COLLISIONS.md','README.md','EVOLUTION_LOG.md'):
        add('final/'+name,(repo/name).read_bytes())
    for p in sorted(out.glob('cycle27-*')):
        if p.suffix in ('.json','.xml','.md') and p.name not in ('cycle27-record.json','cycle27-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    dependency=out/'cycle26-evidence.json.xz';expected='3913127258707db078592f36036b63cdf4df692bd6af33d163ed3a43fbaea440'
    assert sha(dependency.read_bytes())==expected
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,
                        'dependencies':{dependency.name:expected},
                        'preparation_gzip_note':'Decoded JSON bytes and each embedded source are stored; original gzip digest remains in frozen plan'},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for digest,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==digest;screen(body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle27-archive-scan.json',scan)
    record={'status':'COMPLETE_CYCLE','verdict':'PIVOT REQUIRED','production_change':None,'tests':acceptance,'mutants_killed':73,
            'archive_scan':scan,'source_selections_reconstructed':len(data['rows']),'unique_cells':len(cells),
            'final_operation_views_equivalent':audited['current_operation_view_equivalence'],
            'accounting':audited['attempt_accounting'],'reported_usage_by_mode':audited['reported_usage_by_mode'],
            'answer_report_sha256':sha((out/'cycle27-operation-answers.json').read_bytes()),
            'figure_sha256':{p.name:sha(p.read_bytes()) for p in sorted(out.glob('cycle27-*.png'))},
            'kept':['Executable scenarios and strong hybrid controls','Empty focused-search broadening and Unicode parser repairs',
                    'Rate-limit batch pause in target-experiment scheduler','Actual tokenizer-input collision evidence'],
            'discarded':['Default promotion of operation views','Answer-quality claims from annotated passages','Assumption that a bounded full-query encoder sees the question'],
            'next':'Compare declared manual corpus with pinned API source/docstrings, at matched budgets with BM25 and ordinary hybrid controls'}
    write_json(out/'cycle27-record.json',record);print(scan,flush=True)


if __name__=='__main__':main()

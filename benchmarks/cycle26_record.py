"""Reconstruct source evidence, audit index updates, then optionally archive."""
import argparse
import base64
import hashlib
import json
import lzma
from pathlib import Path
import re
import statistics
from unittest.mock import patch
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from benchmarks.spelling_index import open_index,normalized_rank,canonical_rank
from benchmarks.spelling_index_updates import equivalent
from benchmarks.unit_answer_plan import reconstruct,tokens
from benchmarks.evidence_diagnostics import Piece,render
from benchmarks.compiled_source_contract import require_compiled_sources
from npk.pack import verify
from npk.pack.compile import _source_lines
from npk.pack.format import open_pack
from npk.pack.source_policy import PATTERNS


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',action='store_true');args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results';runs=repo/'experiments/runs/packs'
    roots={name:runs/('cycle26-'+name) for name in ('index-v1','index-v2','index-updates-v1','index-updates-v2')}
    data={name:read(root/'results.json') for name,root in roots.items()}
    assert all(d['status']=='COMPLETE' and d['evidence_mode']=='LOCAL' and d['generative_calls']==0 for d in data.values())
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert all(d['code_sha256'][name]==digest for d in data.values() for name,digest in current.items())
    acquired=read(runs/'cycle24-sqlalchemy-corpus-v1/acquisition.json')
    originals=manifest_sources(runs/'cycle24-sqlalchemy-corpus-v1/source',acquired['source_manifest'],'public-source')
    source={k.removeprefix('public-source/'):_source_lines(v.decode()) for k,v in originals.items()}
    full=render([Piece(path,1,len(lines),'\n'.join(lines)) for path,lines in sorted(source.items())],True)
    all_cells={};reconstructed=0
    for name in ('index-v1','index-v2'):
        d=data[name];assert d['source_manifest']==acquired['source_manifest'];tasks={t['id']:t for t in d['tasks']};cells={}
        for row in d['rows']:
            task=tasks[row['task']];pieces,context=reconstruct(row,source)
            assert (roots[name]/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
            expected=bool(any(re.search(r'(?<!\w)'+re.escape(task['identifier'])+r'(?!\w)',p.text) for p in pieces)) if 'identifier' in task else source_coverage(pieces,task['required'])['all_required_spans']
            assert row['metric_pass']==expected
            assert row['corpus_tokens']==d['corpora']['fixed2048']['corpus_tokens']
            assert row['available_tokens']==d['corpora']['fixed2048']['available_tokens']
            cells.setdefault((row['task'],row['method'],row['budget']),[]).append(row);reconstructed+=1
        assert len(d['rows'])==7272 and len(cells)==2424
        assert set(cells)=={(t,m,b) for t in tasks for m in d['methods'] for b in d['budgets']}
        for group in cells.values():
            assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
        for point in d['summary']:
            group=[g for g in cells.values() if all(g[0][k]==point[k] for k in ('cohort','method','budget'))]
            assert len(group)==point['tasks'] and sum(g[0]['metric_pass'] for g in group)==point['metric_pass']
            assert statistics.median(statistics.median(r['latency_ms'] for r in g) for g in group)==point['median_ms']
            assert statistics.mean(g[0]['selected_tokens'] for g in group)==point['mean_selected_tokens']
        assert sha((roots[name]/'spelling.sqlite').read_bytes())==d['build']['index_sha256']
        all_cells[name]=cells
    assert data['index-v1']['tasks']==data['index-v2']['tasks']
    same=0
    for key,rows in all_cells['index-v2'].items():
        before=all_cells['index-v1'][key][0];after=rows[0]
        assert all(before[k]==after[k] for k in ('context_sha256','metric_pass','pieces','selected_tokens','status'))
        same+=1
    best=data['index-v2'];unique=[g[0] for g in all_cells['index-v2'].values()]
    marked_pairs=[(g[0],all_cells['index-v2'][task,'canonical_marked',budget][0]) for (task,method,budget),g in all_cells['index-v2'].items() if method=='canonical_all']
    marked_same=sum(a['context_sha256']==b['context_sha256'] for a,b in marked_pairs)
    update_checks=0;tables=0
    with patch('socket.socket.connect',side_effect=AssertionError('Archive audit attempted network')):
        for name in ('index-updates-v1','index-updates-v2'):
            d=data[name];assert len(d['rows'])==12
            assert {(r['case'],r['trial']) for r in d['rows']}=={(c,t) for c in d['cases'] for t in range(3)}
            for row in d['rows']:
                folder=roots[name]/row['case']/str(row['trial']);pack=folder/'project.npk';index=folder/'spelling.sqlite';fresh=folder/'fresh.sqlite'
                for path,key in ((pack,'pack_sha256'),(index,'index_sha256'),(fresh,'fresh_sha256')):assert sha(path.read_bytes())==row[key]
                assert verify(pack)['ok'];require_compiled_sources(pack,d['source_manifests'][row['case']])
                equivalent(index,fresh);tables+=5
                with open_pack(pack) as con,open_index(index,con) as a,open_index(fresh,con) as b:
                    for query in row['queries']:
                        assert normalized_rank(a,query)==normalized_rank(b,query)
                        assert canonical_rank(a,query)==canonical_rank(b,query);update_checks+=2
    frame_rows=[];tasks={t['id']:t for t in best['tasks']}
    for row in unique:
        query=tasks[row['task']]['query'];_,context=reconstruct(row,source)
        frame_rows.append({k:row[k] for k in ('task','cohort','method','budget','corpus_tokens','available_tokens','selected_tokens','context_sha256')}|
                          {'query_sha256':sha(query.encode()),'baseline_prompt_tokens_estimate':tokens(f'SOURCE\n{full}\n\nQUESTION\n{query}'),
                           'selected_prompt_tokens_estimate':tokens(f'SOURCE\n{context}\n\nQUESTION\n{query}')})
    frontiers=[]
    for cohort in ('known_spelling','new_spelling','known_behavior'):
        points=[p for p in best['summary'] if p['cohort']==cohort]
        for p in points:
            dominated=any(q['mean_selected_tokens']<=p['mean_selected_tokens'] and q['metric_pass']>=p['metric_pass'] and
                          (q['mean_selected_tokens']<p['mean_selected_tokens'] or q['metric_pass']>p['metric_pass']) for q in points)
            if not dominated:frontiers.append(p)
    report={'status':'AUDITED_LOCAL','verdict':'PIVOT REQUIRED','generative_calls':0,'production_change':None,
            'selections_reconstructed':reconstructed,'identical_query_cells_before_after_adapter_fix':same,
            'canonical_marked_identical_contexts':marked_same,'canonical_marked_pairs':len(marked_pairs),
            'update_rank_checks':update_checks,'update_table_comparisons':tables,
            'curve':best['summary'],'pairs':best['pairs'],'descriptive_token_metric_frontier':frontiers,
            'build':best['build'],'updates_before_serialization':data['index-updates-v1']['summary'],
            'updates_after_serialization':data['index-updates-v2']['summary'],
            'per_task_prompt_accounting':frame_rows,
            'accounting_note':'Hypothetical SOURCE/QUESTION frame, chars/4 estimate, excludes provider/system wrappers; no target call, billed tokens, dollars or answer accuracy measured',
            'cost_usd':None,'net_savings_usd':None,'billing_break_even_requests':None,
            'limitations':best['limitations']+data['index-updates-v2']['limitations']}
    write_json(out/'cycle26-summary.json',report)
    print({k:report[k] for k in ('status','selections_reconstructed','identical_query_cells_before_after_adapter_fix','canonical_marked_identical_contexts','canonical_marked_pairs','update_rank_checks','update_table_comparisons')},flush=True)
    if not args.archive:return
    archive=out/'cycle26-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    suite=ET.parse(out/'cycle26-acceptance.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0' and int(suite['tests'])-int(suite['skipped'])==785
    mutations=read(out/'cycle26-mutations.json');assert len(mutations['rows'])==69 and all(r['status']=='KILLED' for r in mutations['rows'])
    assert mutations['source_hashes']==current
    before=ET.parse(out/'cycle26-race-before.xml').find('.//testsuite').attrib
    assert before['failures']=='1' and before['errors']=='0'
    after=ET.parse(out/'cycle26-race-after.xml').find('.//testsuite').attrib
    assert after['failures']==after['errors']=='0'
    files={};blobs={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body):
        assert name not in files;screen(body);digest=sha(body);files[name]=digest;blobs[digest]=base64.b64encode(body).decode()
    for name,body in originals.items():add(name,body)
    for name,root in roots.items():
        executed=read(root/'execution-sources.json');assert set(executed)==set(data[name]['code_sha256'])
        for path,text in executed.items():
            body=text.encode();assert sha(body)==data[name]['code_sha256'][path];add(name+'/execution/'+path,body)
        for p in sorted(root.glob('*.json')):add(name+'/'+p.name,p.read_bytes())
        for p in sorted((root/'contexts').glob('*.txt')):add(name+'/contexts/'+p.name,p.read_bytes())
        for case,manifest in data[name].get('source_manifests',{}).items():
            for path,body in manifest_sources(root/case/'source',manifest,name+'/'+case+'/source').items():add(path,body)
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for p in sorted((runs/'cycle26-mutation-attempt-v1').iterdir()):add('mutation-attempt-v1/'+p.name,p.read_bytes())
    for name in ('research/CYCLE26_SPELLING_INDEX.md','research/math/SPELLING_COLLISIONS.md','EVOLUTION_LOG.md','README.md'):add('final/'+name,(repo/name).read_bytes())
    for p in sorted(out.glob('cycle26-*')):
        if p.suffix in ('.json','.xml') and p.name not in ('cycle26-record.json','cycle26-archive-scan.json'):add('results/'+p.name,p.read_bytes())
    dependency=out/'cycle25-evidence.json.xz';expected='5e72112094a90c9ebfd3f2c719e800c0b23f637c244c1fd2c59422cbc0f7b6a9'
    assert sha(dependency.read_bytes())==expected
    license_body=(runs/'cycle24-sqlalchemy-corpus-v1/LICENSE.txt').read_bytes();assert sha(license_body)==acquired['license_sha256'];add('LICENSE.txt',license_body)
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,'dependencies':{dependency.name:expected}},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for digest,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==digest;screen(body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle26-archive-scan.json',scan)
    record={'status':'COMPLETE_CYCLE','verdict':'PIVOT REQUIRED','production_change':None,'tests':suite,'mutants_killed':69,'archive_scan':scan,
            'summary_sha256':sha((out/'cycle26-summary.json').read_bytes()),
            'kept':['Research normalization controls with collisions','Serialized research side-index updates','Adapter and interleaving regression tests'],
            'discarded':['General default promotion of spelling indexes','Marked-only extra channel on this corpus','Unnecessary baseline execution in the normalized control','Unsupported answer-quality claims from source hits'],
            'next':'Test operation-aware static query views on executable behavior scenarios against existing clause and lexical baselines; freeze variants before answer calls'}
    write_json(out/'cycle26-record.json',record);print(scan,flush=True)


if __name__=='__main__':main()

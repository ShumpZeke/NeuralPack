"""Reconstruct spelling probes and replay profiled contexts before archiving."""
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
from benchmarks.source_archive import manifest_sources
from benchmarks.unit_answer_plan import reconstruct
from benchmarks.compiled_source_contract import require_compiled_sources
from npk.pack import PackSelector,verify
from npk.pack.compile import _source_lines
from npk.pack.select import _content_terms
from npk.pack.source_policy import PATTERNS


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results';runs=repo/'experiments/runs/packs'
    roots={'spelling':runs/'cycle25-spelling-v1','runtime':runs/'cycle25-runtime-v1'}
    archive=out/'cycle25-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    data={k:read(r/'results.json') for k,r in roots.items()};a=data['spelling'];b=data['runtime']
    assert a['status']==b['status']=='COMPLETE' and b['spelling_results_sha256']==sha((roots['spelling']/'results.json').read_bytes())
    originals=manifest_sources(runs/'cycle24-sqlalchemy-corpus-v1/source',a['source_manifest'],'public-source')
    source={k.removeprefix('public-source/'):_source_lines(body.decode()) for k,body in originals.items()}
    tasks={t['id']:t for t in a['tasks']};cells={}
    for row in a['rows']:
        pieces,context=reconstruct(row,source)
        assert (roots['spelling']/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
        expected=any(re.search(r'(?<!\w)'+re.escape(row['identifier'])+r'(?!\w)',p.text) for p in pieces)
        assert row['identifier_present']==bool(expected)  # Labels alone cannot count as a source hit.
        assert row['identifier']==tasks[row['task']]['identifier']
        cells.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    assert len(a['rows'])==2304 and len(cells)==768
    for group in cells.values():
        assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
    for point in a['summary']:
        group=[rs for rs in cells.values() if all(rs[0][k]==point[k] for k in ('kind','variant','method','budget'))]
        assert len(group)==point['tasks']==16
        assert sum(g[0]['identifier_present'] for g in group)==point['identifier_present']
        assert statistics.median(statistics.median(r['latency_ms'] for r in g) for g in group)==point['median_ms']
    assert len(b['prototype_cells'])==192 and len(b['original_behavior_cells'])==40 and all(r['unchanged'] for r in b['original_behavior_cells'])
    for item in b['prototype_cells']:
        assert item['context_sha256']==cells[item['task'],'vocabulary_split',item['budget']][0]['context_sha256']
    replayed=0
    with patch('socket.socket.connect',side_effect=AssertionError('Archive replay attempted network')):
        for profile in b['profiles']:
            root=roots['runtime']/str(profile['requested_size']);pack=root/'project.npk'
            assert sha(pack.read_bytes())==profile['artifact_sha256'] and verify(pack)['ok']
            require_compiled_sources(pack,profile['source_manifest']);seen={}
            for row in profile['rows']:seen.setdefault((row['method'],row['query']),[]).append(row)
            for (method,query),group in seen.items():
                assert sorted(r['trial'] for r in group)==[0,1,2] and len({r['context_sha256'] for r in group})==1
                if method=='previous':
                    with patch('npk.pack.select._lexical_terms',lambda con,q:_content_terms(q)):
                        selected=PackSelector(pack).select(query,budget_tokens=2048)
                else:selected=PackSelector(pack).select(query,budget_tokens=2048)
                assert sha(selected.context_text().encode())==group[0]['context_sha256']
                assert selected.query==query and selected.total_tokens==group[0]['selected_tokens']<=2048
                replayed+=1
    assert replayed==144 and sum(len(p['rows']) for p in b['profiles'])==432
    files={};blobs={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body):
        assert name not in files;screen(body);digest=sha(body)
        files[name]=digest;blobs[digest]=base64.b64encode(body).decode()
    for name,body in originals.items():add(name,body)
    for profile in b['profiles']:
        root=roots['runtime']/str(profile['requested_size'])
        for name,body in manifest_sources(root/'source',profile['source_manifest'],'runtime/'+str(profile['requested_size'])+'/source').items():add(name,body)
    for name,root in roots.items():
        executed=read(root/'execution-sources.json');assert set(executed)==set(data[name]['code_sha256'])
        for path,text in executed.items():
            body=text.encode();assert sha(body)==data[name]['code_sha256'][path];add(name+'/execution/'+path,body)
        for p in sorted(root.glob('*.json')):add(name+'/'+p.name,p.read_bytes())
    for p in sorted((roots['spelling']/'contexts').glob('*.txt')):add('spelling/contexts/'+p.name,p.read_bytes())
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for name in ('research/CYCLE25_IDENTIFIER_SPELLING.md','EVOLUTION_LOG.md','README.md'):add('final/'+name,(repo/name).read_bytes())
    suite=ET.parse(out/'cycle25-final-acceptance.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0' and int(suite['tests'])-int(suite['skipped'])==775
    mutations=read(out/'cycle25-mutations.json')
    assert len(mutations['rows'])==65 and all(r['status']=='KILLED' for r in mutations['rows'])
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert mutations['source_hashes']==current
    assert all(b['code_sha256'][path]==digest for path,digest in current.items())
    for p in sorted(out.glob('cycle25-*')):
        if p.suffix in ('.json','.xml') and p.name not in ('cycle25-record.json','cycle25-archive-scan.json'):add('results/'+p.name,p.read_bytes())
    dependency=out/'cycle24-evidence.json.xz';expected=read(out/'cycle24-archive-scan.json')['archive_sha256']
    assert sha(dependency.read_bytes())==expected
    license_body=(runs/'cycle24-sqlalchemy-corpus-v1/LICENSE.txt').read_bytes()
    assert sha(license_body)==read(runs/'cycle24-sqlalchemy-corpus-v1/acquisition.json')['license_sha256'];add('LICENSE.txt',license_body)
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,
                        'dependencies':{dependency.name:expected}},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for digest,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==digest;screen(body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle25-archive-scan.json',scan)
    record={'status':'COMPLETE_CYCLE','verdict':'PIVOT REQUIRED','runtime_change':'Vocabulary-checked camel-case splitting',
            'tests':suite,'mutants_killed':65,'archive_scan':scan,'selections_reconstructed':2304,
            'profile_unique_requests_replayed':replayed,'prototype_equivalence_cells':192,'unchanged_behavior_cells':40,
            'lookup_curve':a['summary'],'pairs_vs_previous':a['pairs'],
            'profile':[{k:v for k,v in p.items() if k not in ('rows','source_manifest')} for p in b['profiles']],
            'kept':['Vocabulary-aware spelling repair','Literal collision and case-order regressions'],
            'discarded':['Unconditional compound splitting as the default','Lookup counts as answer accuracy'],
            'next':'Evaluate source-aware identifier normalization with explicit collisions before adding an index',
            'limitations':a['limitations']+b['limitations']}
    write_json(out/'cycle25-record.json',record);print({'archive':scan,'reconstructed':2304,'profile_requests_replayed':replayed})


if __name__=='__main__':main()

"""Reconstruct boundary evidence and archive executed sources, not just claims."""
import base64
import hashlib
import json
import lzma
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from npk.pack.source_policy import PATTERNS


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results';runs=repo/'experiments/runs/packs'
    roots={name:runs/('cycle23-boundary-'+('gate' if name=='gate' else name)+'-v1') for name in ('gate','retrieval','updates')}
    archive=out/'cycle23-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    data={name:read(root/'results.json') for name,root in roots.items()}
    assert all(d['status']=='COMPLETE' for d in data.values())
    assert [len(data[name]['rows']) for name in roots]==[300,720,72]
    assert sum(r['query_equivalence_checks'] for r in data['updates']['rows'])==720
    for name,root in roots.items():assert (out/f'cycle23-boundary-{name}.json').read_bytes()==(root/'results.json').read_bytes()
    assert data['retrieval']['parent_results_sha256']==sha((roots['gate']/'results.json').read_bytes())
    assert data['updates']['parent_results_sha256']==sha((roots['retrieval']/'results.json').read_bytes())
    files={};blobs={};kinds={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body):
        assert name not in files;screen(body);digest=sha(body)
        files[name]=digest;blobs[digest]=base64.b64encode(body).decode();kinds[digest]='text'
    source=roots['gate']/'source'
    originals=manifest_sources(source,data['gate']['source_manifest'],'public-source')
    for name,body in originals.items():add(name,body)
    for case,manifest in data['updates']['source_manifests'].items():
        for name,body in manifest_sources(roots['updates']/case/'source',manifest,'updates/'+case+'/source').items():add(name,body)
    tasks={t['id']:t for t in data['retrieval']['tasks']};assert len(tasks)==10
    for task in tasks.values():
        for item in task['required']:
            lines=originals['public-source/'+item['path']].decode().split('\n');start,end=item['span']
            body='\n'.join(lines[start-1:end]);assert body==item['text'] and sha(body.encode())==item['sha256']
    by_cell={}
    for row in data['retrieval']['rows']:
        assert row['task'] in tasks and row['method'] in data['retrieval']['methods'] and row['budget'] in data['retrieval']['budgets']
        pieces=[];ev=[]
        for item in row['evidence']:
            start,end=map(int,item['span'].rsplit(':',1)[1].split('-'))
            assert item['span'].rsplit(':',1)[0]==item['path']
            lines=originals['public-source/'+item['path']].decode().split('\n')
            assert 1<=start<=end<=len(lines);body='\n'.join(lines[start-1:end]);pieces.append(body)
            assert item['tokens']==max(1,len(body)//4);ev.append(SimpleNamespace(**item))
        context='\n\n'.join(pieces);digest=sha(context.encode())
        assert row['context_sha256']==digest and (roots['retrieval']/'contexts'/(digest+'.txt')).read_bytes()==context.encode()
        assert row['selected_tokens']==(max(1,len(context)//4) if pieces else 0)<=row['budget']
        if not pieces:assert row['status']=='fallback_required' and row['seed_failed']
        metric=source_coverage(ev,tasks[row['task']]['required'])
        assert all(row[key]==value for key,value in metric.items())
        key=(row['task'],row['method'],row['budget']);by_cell.setdefault(key,[]).append(row)
    assert len(by_cell)==240
    for rows in by_cell.values():
        assert sorted(r['trial'] for r in rows)==[0,1,2] and len({r['context_sha256'] for r in rows})==1
    for point in data['retrieval']['summary']:
        group=[rows[0] for key,rows in by_cell.items() if key[1:]==(point['method'],point['budget'])]
        assert len(group)==point['tasks']==10
        assert sum(r['all_required_spans'] for r in group)==point['all_required_spans']
        assert sum(r['selected_tokens'] for r in group)/len(group)==point['mean_selected_tokens']
    points=[p for p in data['retrieval']['summary'] if p['all_required_spans']>0]
    frontier=[p for p in points if not any(q['mean_selected_tokens']<=p['mean_selected_tokens'] and
              q['all_required_spans']>=p['all_required_spans'] and
              (q['mean_selected_tokens']<p['mean_selected_tokens'] or q['all_required_spans']>p['all_required_spans']) for q in points)]
    for name,root in roots.items():
        executed=read(root/'execution-sources.json');assert set(executed)==set(data[name]['code_sha256'])
        for path,text in executed.items():
            body=text.encode();assert sha(body)==data[name]['code_sha256'][path];add(name+'/execution/'+path,body)
        for filename in ('manifest.json','results.json','execution-sources.json'):add(name+'/'+filename,(root/filename).read_bytes())
    for p in sorted((roots['retrieval']/'contexts').glob('*.txt')):add('retrieval/contexts/'+p.name,p.read_bytes())
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for name in ('research/CYCLE23_BOUNDARIES.md','EVOLUTION_LOG.md','README.md'):
        add('final/'+name,(repo/name).read_bytes())
    suite=ET.parse(out/'cycle23-acceptance.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0'
    mutations=read(out/'cycle23-mutations.json')
    assert len(mutations['rows'])==59 and all(r['status']=='KILLED' for r in mutations['rows'])
    assert mutations['source_hashes']=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    for p in sorted(out.glob('cycle23-*')):
        if p.suffix in ('.json','.xml') and p.name not in ('cycle23-record.json','cycle23-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    dependency=out/'cycle22-evidence.json.xz';expected=read(out/'cycle22-archive-scan.json')['archive_sha256']
    assert sha(dependency.read_bytes())==expected
    license_body=(runs/'cycle22-block-update-v1/CPYTHON-LICENSE.txt').read_bytes()
    assert sha(license_body)==read(runs/'cycle22-block-update-v1/license.json')['sha256'];add('CPYTHON-LICENSE.txt',license_body)
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,'kinds':kinds,
                        'dependencies':{dependency.name:expected}},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for digest,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==digest;screen(body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle23-archive-scan.json',scan)
    record={'status':'COMPLETE_LOCAL_EXPERIMENT','verdict':'PIVOT REQUIRED','compiled_runtime_changed':False,
            'tests':suite,'mutants_killed':59,'archive_scan':scan,'retrieval_selections_reconstructed':720,
            'plot_file':'cycle23-boundary-curves.png','plot_sha256':sha((out/'cycle23-boundary-curves.png').read_bytes()),
            'source_manifest':data['gate']['source_manifest'],'retrieval_curve':data['retrieval']['summary'],
            'positive_coverage_frontier':frontier,'update_summary':data['updates']['summary'],
            'kept':['Fixed-size and anchor research controls','Exact-span and oversized-line regressions','Counterexample to universal stability'],
            'not_promoted':['Content anchors as a production default','Temporary row-reuse adapter','Passage coverage as answer accuracy'],
            'next':'Test small indexing units with source-aware passage assembly against the competent fixed-size control on unseen material',
            'limitations':data['retrieval']['limitations']+data['updates']['limitations']+
                          ['Positive-coverage frontier excludes zero-hit points; all such observations remain in the complete curve']}
    write_json(out/'cycle23-record.json',record);print({'archive':scan,'reconstructed_selections':720,'positive_coverage_frontier':frontier})


if __name__=='__main__':main()

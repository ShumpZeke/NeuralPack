"""Close cycle 24 with reconstructed evidence and byte-exact executed sources."""
import base64
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json
from benchmarks.repository_eval import source_coverage
from benchmarks.source_archive import manifest_sources
from benchmarks.unit_answer_plan import reconstruct,tokens
from benchmarks.unit_answer_report import build as audit_answers
from benchmarks.compiled_source_contract import require_compiled_sources
from npk.pack import verify
from npk.pack.compile import _source_lines
from npk.pack.format import open_pack
from npk.pack.source_policy import PATTERNS


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results';runs=repo/'experiments/runs/packs'
    corpus=runs/'cycle24-sqlalchemy-corpus-v1';local=runs/'cycle24-unit-retrieval-v3';live=runs/'cycle24-unit-live-v1'
    archive=out/'cycle24-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    acquired=read(corpus/'acquisition.json');data=read(local/'results.json');plan=read(live/'plan.json')
    assert data['status']=='COMPLETE' and data['acquisition_sha256']==sha((corpus/'acquisition.json').read_bytes())
    assert data['source_manifest']==plan['source_manifest']==acquired['source_manifest']
    originals=manifest_sources(corpus/'source',acquired['source_manifest'],'public-source')
    assert len(originals)==153
    sources={name.removeprefix('public-source/'):_source_lines(body.decode()) for name,body in originals.items()}
    tasks={t['id']:t for t in data['tasks']};assert len(tasks)==10
    oracle=read(out/'cycle24-sqlalchemy-tasks.json')
    assert data['oracle_sha256']==sha((out/'cycle24-sqlalchemy-tasks.json').read_bytes())
    assert oracle['oracle_source_sha256']==sha((repo/'benchmarks/sqlalchemy_oracles.py').read_bytes())
    assert [(t['id'],t['question'],t['expected']) for t in oracle['tasks']]==[(t['id'],t['question'],t['expected']) for t in data['tasks']]
    assert [(t['id'],t['question'],t['expected']) for t in data['tasks']]==[(t['id'],t['question'],t['answer']) for t in plan['dataset']['tasks']]
    for task in tasks.values():
        for item in task['required']:
            start,end=item['span'];body='\n'.join(sources[item['path']][start-1:end])
            assert body==item['text'] and sha(body.encode())==item['sha256']
    cells={}
    for row in data['rows']:
        pieces,context=reconstruct(row,sources)
        assert (local/'contexts'/(row['context_sha256']+'.txt')).read_bytes()==context.encode()
        assert all(row[k]==v for k,v in source_coverage(pieces,tasks[row['task']]['required']).items())
        cells.setdefault((row['task'],row['method'],row['budget']),[]).append(row)
    assert len(data['rows'])==960 and set(cells)=={(t,m,b) for t in tasks for m in data['configurations'] for b in data['budgets']}
    for rows in cells.values():assert sorted(r['trial'] for r in rows)==[0,1,2] and len({r['context_sha256'] for r in rows})==1
    for point in data['summary']:
        rows=[rs[0] for key,rs in cells.items() if key[1:]==(point['method'],point['budget'])]
        assert len(rows)==point['tasks']==10
        assert sum(r['all_required_spans'] for r in rows)==point['all_required_spans']
        assert sum(r['selected_tokens'] for r in rows)/len(rows)==point['mean_selected_tokens']
    for name in data['corpora']:
        pack=local/(name+'.npk');assert sha(pack.read_bytes())==data['corpora'][name]['pack_sha256']
        assert verify(pack)['ok'];require_compiled_sources(pack,acquired['source_manifest'])
    prior=runs/'cycle24-unit-retrieval-v2';origin=data['compilation_origin']
    assert origin['compilation_sha256']==sha((prior/'compilation.json').read_bytes())
    assert origin['manifest_sha256']==sha((prior/'manifest.json').read_bytes())
    assert data['builds']==read(prior/'compilation.json')['builds']
    old=runs/'cycle24-unit-retrieval-v1'
    for pack in old.glob('*.npk'):
        with open_pack(pack) as con:assert con.execute('SELECT COUNT(*) FROM files').fetchone()[0]==0
    answers=audit_answers(live,local)
    assert answers==read(out/'cycle24-unit-answers.json')
    assert answers['audit']['live_attempts_in_ledger']==78 and answers['audit']['unique_responses']==61
    assert answers['audit']['transport_failures']==17
    from benchmarks.evidence_diagnostics import Piece,render
    full=render([Piece(path,1,len(lines),'\n'.join(lines)) for path,lines in sorted(sources.items())],True)
    unique={(r['task'],r['method'],r['budget']):r for r in data['unique']}
    for observation in plan['observations']:
        if observation['method']=='full':context=full
        elif observation['method']=='none':context=''
        else:_,context=reconstruct(unique[observation['task'],observation['method'],observation['budget']],sources)
        assert observation['context_sha256']==sha(context.encode()) and observation['selected_tokens']==tokens(context)
        assert (live/'contexts'/(observation['context_sha256']+'.txt')).read_bytes()==context.encode()
    files={};blobs={};kinds={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body,kind='text'):
        if name in files:raise ValueError('Duplicate archive name')
        if kind=='text':screen(body)
        elif kind=='gzip-json':screen(gzip.decompress(body))
        else:raise ValueError('Unknown archive encoding')
        digest=sha(body);files[name]=digest;blobs[digest]=base64.b64encode(body).decode();kinds[digest]=kind
    for name,body in originals.items():add(name,body)
    license_body=(corpus/'LICENSE.txt').read_bytes();assert sha(license_body)==acquired['license_sha256'];add('LICENSE.txt',license_body)
    add('acquisition.json',(corpus/'acquisition.json').read_bytes())
    for generation in (1,2,3):
        root=runs/f'cycle24-unit-retrieval-v{generation}';manifest=read(root/'manifest.json');executed=read(root/'execution-sources.json')
        assert set(executed)==set(manifest['code_sha256'])
        for name,text in executed.items():
            body=text.encode();assert sha(body)==manifest['code_sha256'][name];add(f'local-v{generation}/execution/'+name,body)
        for p in sorted(root.rglob('*')):
            if p.is_file() and p.suffix in ('.json','.txt'):add(f'local-v{generation}/'+p.relative_to(root).as_posix(),p.read_bytes())
    preparation=(live/'preparation-sources.json.gz').read_bytes()
    assert sha(preparation)==plan['preparation_sources_sha256']
    snapshot=json.loads(gzip.decompress(preparation));assert set(snapshot)==set(plan['code_sha256'])
    for name,item in snapshot.items():
        body=item['text'].encode();assert sha(body)==item['sha256']==plan['code_sha256'][name];add('live/preparation/'+name,body)
    add('live/preparation-sources.json.gz',preparation,'gzip-json')
    for p in sorted(live.rglob('*')):
        if p.is_file() and p.suffix in ('.json','.txt','.py','.sha256'):add('live/'+p.relative_to(live).as_posix(),p.read_bytes())
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for name in ('research/CYCLE24_UNIT_PASSAGES.md','EVOLUTION_LOG.md','README.md'):
        add('final/'+name,(repo/name).read_bytes())
    suite=ET.parse(out/'cycle24-final-acceptance.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0' and int(suite['tests'])-int(suite['skipped'])==765
    mutations=read(out/'cycle24-mutations.json')
    assert len(mutations['rows'])==63 and all(r['status']=='KILLED' for r in mutations['rows'])
    assert mutations['source_hashes']=={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    for p in sorted(out.glob('cycle24-*')):
        if p.suffix in ('.json','.xml','.md') and p.name not in ('cycle24-record.json','cycle24-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    dependency=out/'cycle23-evidence.json.xz';expected=read(out/'cycle23-archive-scan.json')['archive_sha256']
    assert sha(dependency.read_bytes())==expected
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,'kinds':kinds,
                        'dependencies':{dependency.name:expected}},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for digest,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==digest
        screen(gzip.decompress(body) if kinds[digest]=='gzip-json' else body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle24-archive-scan.json',scan)
    points=data['summary']
    frontier=[p for p in points if not any(q['mean_selected_tokens']<=p['mean_selected_tokens'] and
              q['all_required_spans']>=p['all_required_spans'] and
              (q['mean_selected_tokens']<p['mean_selected_tokens'] or q['all_required_spans']>p['all_required_spans']) for q in points)]
    record={'status':'COMPLETE_CYCLE','verdict':'PIVOT REQUIRED','compiler_version':'5.3',
            'tests':suite,'mutants_killed':63,'archive_scan':scan,'local_selections_reconstructed':960,
            'live_contexts_reconstructed':len(plan['observations']),'source_manifest':acquired['source_manifest'],
            'local_curve':points,'local_coverage_frontier':frontier,'compilation':read(local/'compilation.json'),
            'answer_report_sha256':sha((out/'cycle24-unit-answers.json').read_bytes()),
            'plots':{p.name:sha(p.read_bytes()) for p in sorted(out.glob('cycle24-unit-*.png'))},
            'kept':['Compiler source-omission repair','Expected-corpus identity gate','Literal-span and format-confound regressions'],
            'not_promoted':['Paragraph expansion','MiniLM as a mandatory accelerator','Passage coverage as answer accuracy'],
            'next':'Measure operation-aware deterministic query views against existing clause controls; test retained lexical and neural input information before another LIVE run',
            'limitations':data['limitations']+answers['limitations']+['SQLite artifacts are identified by hashes; source, executed code and measurements are archived, optional model weights are revision-pinned external dependencies']}
    write_json(out/'cycle24-record.json',record)
    print({'archive':scan,'local_reconstructed':960,'live_reconstructed':len(plan['observations'])})


if __name__=='__main__':main()

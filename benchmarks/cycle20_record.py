"""Archive completed target controls and optional terminal cycle-18 DeepSeek evidence."""
import base64
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
from benchmarks.prospective_eval import write_json
from benchmarks.target_controls_report import build
from npk.pack.source_policy import PATTERNS
from benchmarks.source_archive import manifest_sources


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results'
    root=repo/'experiments/runs/packs/cycle20-target-controls-v1'
    archive=out/'cycle20-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    report=read(out/'cycle20-target-answers.json');assert report==build(root) and report['status']=='COMPLETE'
    suite=ET.parse(out/'cycle20-acceptance-final.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0'
    mutations=read(out/'cycle20-mutations-final.json');assert len(mutations['rows'])==57
    assert all(r['status']=='KILLED' for r in mutations['rows'])
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert current==mutations['source_hashes']
    rows={name:read(root/name/'results.json')['rows'] for name in ('direct','reasoning')}
    matched=[]
    for method in ('none','bm25','privileged_source'):
        groups={name:{r['task']:r for r in rs if r['method']==method and r.get('transport_success')} for name,rs in rows.items()}
        common=sorted(set(groups['direct'])&set(groups['reasoning']));record={'method':method,'tasks':common}
        for name,group in groups.items():
            record[name]={'passed':sum(group[t]['task_success'] for t in common),
                          'mean_input_tokens':statistics.mean(group[t]['usage']['prompt_tokens'] for t in common) if common else None,
                          'mean_output_tokens':statistics.mean(group[t]['usage']['completion_tokens'] for t in common) if common else None,
                          'mean_latency_ms':statistics.mean(group[t]['latency_ms'] for t in common) if common else None}
        matched.append(record)
    deep_report=out/'cycle18-deepseek-answers.json';deep=None
    deep_root=repo/'experiments/runs/cycle18-clause-live-v1/deepseek'
    if deep_report.exists():
        deep=read(deep_report);assert not deep['pending_unique_requests']
        assert deep['plan_sha256']==sha((deep_root/'plan.json').read_bytes())
        ledger=read(deep_root/'ledger.json');plan=read(deep_root/'plan.json')
        assert set(ledger)==set(plan['requests']) and all(e['state']=='DONE' for e in ledger.values())
    dependencies={}
    for cycle in (18,19):
        record=read(out/('cycle18-checkpoint-scan.json' if cycle==18 else 'cycle19-archive-scan.json'))
        name=record['archive_file'];assert sha((out/name).read_bytes())==record['archive_sha256']
        dependencies[name]=record['archive_sha256']
    files={};blobs={};kinds={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body,compressed=False):
        assert name not in files;screen(gzip.decompress(body) if compressed else body)
        key=sha(body);files[name]=key;blobs[key]=base64.b64encode(body).decode();kinds[key]='gzip' if compressed else 'text'
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    manuals=repo/'experiments/runs/packs/cycle19-manuals-v1'
    acquisition=read(manuals/'acquisition.json')
    public=manifest_sources(manuals/'source',acquisition['source_manifest'],'public-source')
    for name,body in public.items():add(name,body)
    repairs=[]
    for prior,prefix in (('cycle18-checkpoint-evidence.json.xz','public-source/'),('cycle19-evidence.json.xz','manuals/source/')):
        old=json.loads(lzma.decompress((out/prior).read_bytes()))
        expected=read(repo/'experiments/runs/packs/cycle18-clauses-v1/results.json')['source_manifest'] if prior.startswith('cycle18') else acquisition['source_manifest']
        for item in expected:
            if prefix+item['path'] not in old['files']:
                repairs.append({'archive':prior,'missing_path':prefix+item['path'],
                                'supplement_path':'public-source/'+item['path'],'sha256':item['sha256']})
        del old
    profile=repo/'experiments/runs/packs/cycle21-update-stages-v1';profile_data=read(profile/'results.json')
    assert profile_data['status']=='COMPLETE' and profile_data['code_sha256']==current
    assert profile_data['profiler_sha256']==sha((repo/'benchmarks/update_stage_profile.py').read_bytes())
    names=sorted(x['path'] for x in profile_data['source_manifest'])
    for case,count in profile_data['cases'].items():
        manifest=[]
        for item in profile_data['source_manifest']:
            body=public['public-source/'+item['path']]
            assert sha(body)==item['sha256']
            if item['path'] in names[:count]:body+=profile_data['edit_suffix'].encode()
            manifest.append({'path':item['path'],'sha256':sha(body)})
        for name,body in manifest_sources(profile/case/'source',manifest,'update-profile/'+case+'/source').items():add(name,body)
    folders=[(root,'target-controls'),(profile,'update-profile')]+([(deep_root,'cycle18-deepseek')] if deep else [])
    for folder,prefix in folders:
        for p in sorted(folder.rglob('*')):
            if folder==profile and 'source' in p.relative_to(folder).parts:continue
            if p.is_file() and p.suffix in ('.py','.txt','.json','.jsonl','.md','.sha256','.gz'):
                add(prefix+'/'+p.relative_to(folder).as_posix(),p.read_bytes(),p.suffix=='.gz')
    extra=sorted(out.glob('cycle20-*'))+(sorted(out.glob('cycle18-deepseek-*')) if deep else [])
    for p in extra:
        if p.suffix in ('.json','.xml','.md') and p.name not in ('cycle20-record.json','cycle20-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,'kinds':kinds,
                        'dependencies':dependencies},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for key,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==key
        screen(gzip.decompress(body) if kinds[key]=='gzip' else body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle20-archive-scan.json',scan)
    summary={'status':'COMPLETE_TARGET_CONTROLS','verdict':'PIVOT REQUIRED','compiled_runtime_changed':False,
             'candidate_source_sha256':current,'tests':suite,'mutants_killed':57,'archive_scan':scan,
             'accounting':report['accounting'],'matched_target_measurements':matched,
             'configuration_pairs':report['configuration_pairs'],'privileged_source_vs_bm25':report['privileged_source_vs_bm25'],
             'target_report_sha256':sha((out/'cycle20-target-answers.json').read_bytes()),
             'cycle18_deepseek_status':'COMPLETE' if deep else 'PENDING',
             'cycle18_deepseek_report_sha256':sha(deep_report.read_bytes()) if deep else None,
             'source_archive_repairs':repairs,'update_profile_summary':profile_data['summary'],
             'kept':['Exact source and model-configuration controls','Evidence-matching and missing-outcome tripwires',
                     'Qualified retrieval/answer non-identifiability result'],
             'not_promoted':['Privileged source as an automatic retriever','Reasoning as a free or consistent quality improvement'],
             'next':'Do not add a delta API for the measured workload; seek larger bottlenecks before changing the compiler',
             'limitations':report['limitations']+['Matched mean target latencies are single sampled responses under uncontrolled provider load']}
    write_json(out/'cycle20-record.json',summary)
    print({'status':summary['status'],'archive':scan,'matched':matched,'deepseek':summary['cycle18_deepseek_status']})


if __name__=='__main__':main()

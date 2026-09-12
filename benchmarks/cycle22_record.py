"""Seal byte-exact inputs and LOCAL measurements for the block-reuse experiment."""
import base64
import hashlib
import json
import lzma
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
from benchmarks.block_update_profile import edit
from benchmarks.prospective_eval import write_json
from benchmarks.source_archive import manifest_sources
from npk.pack.compile import TEXT_SUFFIXES
from npk.pack.source_policy import PATTERNS


def sha(body):return hashlib.sha256(body).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=Path(__file__).resolve().parents[1];out=repo/'experiments/results'
    runs=repo/'experiments/runs/packs'
    corpus=runs/'cycle22-block-update-v1';profile=runs/'cycle22-block-profile-v1'
    comparison=runs/'cycle22-reuse-compare-v1';archive=out/'cycle22-evidence.json.xz'
    if archive.exists():raise ValueError('Final archive already exists')
    acquisition=read(corpus/'acquisition.json');stage=read(profile/'results.json');data=read(comparison/'results.json')
    current={p.relative_to(repo).as_posix():sha(p.read_bytes()) for p in (repo/'npk').rglob('*.py')}
    assert stage['status']==data['status']=='COMPLETE' and stage['code_sha256']==data['code_sha256']==current
    assert stage['acquisition_sha256']==sha((corpus/'acquisition.json').read_bytes())
    assert stage['profiler_sha256']==sha((repo/'benchmarks/block_update_profile.py').read_bytes())
    assert data['parent_results_sha256']==sha((profile/'results.json').read_bytes())
    for name,digest in data['adapter_sha256'].items():assert sha((repo/'benchmarks'/name).read_bytes())==digest
    for name,parent in [('cycle22-block-profile.json',profile),('cycle22-block-reuse.json',comparison)]:
        assert (out/name).read_bytes()==(parent/'results.json').read_bytes()
    assert len(stage['rows'])==18 and sum(r['query_equivalence_checks'] for r in stage['rows'])==90
    assert len(data['rows'])==60 and sum(r['query_equivalence_checks'] for r in data['rows'])==300
    for summary in data['summary']:
        group=[r for r in data['rows'] if (r['file'],r['case'])==(summary['file'],summary['case'])]
        for method in ('baseline','reuse'):
            rows=[r for r in group if r['method']==method]
            assert sorted(r['trial'] for r in rows)==list(range(5))
            assert statistics.median(r['wall_ms'] for r in rows)==summary['median_ms'][method]
        assert summary['ratio_of_medians']==summary['median_ms']['baseline']/summary['median_ms']['reuse']
    suite=ET.parse(out/'cycle22-acceptance-final.xml').find('.//testsuite').attrib
    assert suite['failures']==suite['errors']=='0'
    mutations=read(out/'cycle22-mutations.json')
    assert mutations['source_hashes']==current and len(mutations['rows'])==58
    assert all(r['status']=='KILLED' for r in mutations['rows'])
    files={};blobs={};kinds={};scans=0
    def screen(body):
        nonlocal scans
        text=body.decode('utf-8');scans+=1
        if any(p.search(text) for _,p in PATTERNS):raise ValueError('Recognized credential pattern; no value printed')
    def add(name,body):
        assert name not in files;screen(body);key=sha(body)
        files[name]=key;blobs[key]=base64.b64encode(body).decode();kinds[key]='text'
    originals=manifest_sources(corpus/'source',acquisition['source_manifest'],'public-source')
    for name,body in originals.items():add(name,body)
    for i,item in enumerate(acquisition['source_manifest']):
        name=Path(item['path']).name;body=originals['public-source/'+item['path']]
        variants=[('base-source',body)]+[(kind+'/source',edit(body,kind,TEXT_SUFFIXES[Path(name).suffix])) for kind in ('append','prepend_blank')]
        for relative,expected in variants:
            folder=profile/f'file-{i}'/relative
            for path,value in manifest_sources(folder,[{'path':name,'sha256':sha(expected)}],f'profile/file-{i}/'+relative).items():add(path,value)
    license_data=read(corpus/'license.json')
    assert sha((corpus/'CPYTHON-LICENSE.txt').read_bytes())==license_data['sha256']
    for name in ('acquisition.json','license.json','CPYTHON-LICENSE.txt'):add('acquisition/'+name,(corpus/name).read_bytes())
    for root,prefix in ((profile,'profile'),(comparison,'comparison')):
        for name in ('manifest.json','results.json'):add(prefix+'/'+name,(root/name).read_bytes())
    for folder in ('npk','benchmarks','tests'):
        for p in sorted((repo/folder).rglob('*.py')):add('final/'+p.relative_to(repo).as_posix(),p.read_bytes())
    for name in ('research/CYCLE22_BLOCK_REUSE.md','research/math/EXACT_BLOCK_REUSE.md','EVOLUTION_LOG.md'):
        add('final/'+name,(repo/name).read_bytes())
    for p in sorted(out.glob('cycle22-*')):
        if p.suffix in ('.json','.xml') and p.name not in ('cycle22-record.json','cycle22-archive-scan.json'):
            add('results/'+p.name,p.read_bytes())
    dependency=out/'cycle20-evidence.json.xz'
    expected=read(out/'cycle20-archive-scan.json')['archive_sha256'];assert sha(dependency.read_bytes())==expected
    payload=json.dumps({'encoding':'SHA-256 addressed byte-exact base64','files':files,'blobs':blobs,'kinds':kinds,
                        'dependencies':{dependency.name:expected}},separators=(',',':')).encode()
    archive.write_bytes(lzma.compress(payload));assert lzma.decompress(archive.read_bytes())==payload
    for key,value in json.loads(lzma.decompress(archive.read_bytes()))['blobs'].items():
        body=base64.b64decode(value,validate=True);assert sha(body)==key;screen(body)
    scan={'archive_file':archive.name,'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
          'files':len(files),'unique_blobs':len(blobs),'decoded_text_scans':scans,'recognized_pattern_matches':0,
          'codec':'standard XZ, Python lzma preset 6','limitation':'Recognized patterns only, not universal secret detection'}
    write_json(out/'cycle22-archive-scan.json',scan)
    record={'status':'COMPLETE_LOCAL_EXPERIMENT','verdict':'PIVOT REQUIRED','compiled_runtime_changed':False,
            'tests':suite,'mutants_killed':58,'archive_scan':scan,'source_manifest':acquisition['source_manifest'],
            'profile_summary':stage['summary'],'matched_update_summary':data['summary'],
            'kept':['Exact block reuse research adapter','Fresh-build equivalence regressions','Raw sources and stage profiles'],
            'not_promoted':['Temporary single-threaded adapter into runtime','Embeddings or dependency graph row reuse'],
            'next':'Test content-anchored boundaries against positional windows, including retrieval and adversarial edits',
            'limitations':data['limitations']+['No answer-quality or dollar-savings claim']}
    write_json(out/'cycle22-record.json',record);print(scan)


if __name__=='__main__':main()

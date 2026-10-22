"""Offline, known-credential-only audit of v1 preservation and new deliverables."""
import argparse
import hashlib
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime,timezone
from pathlib import Path

from dataops_copilot.api_safety import read_api_settings

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT.parents[1]/'work'
V1=ROOT.parent/'dataops-copilot'
V2=ROOT.parent/'dataops-copilot-v2'
RECORDS=ROOT/'artifacts/revision-v2.1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main(archive):
    key,_=read_api_settings(WORK/'runtime/openai.env')
    generated=json.loads((WORK/'runtime/generated-credentials.json').read_text())
    secrets=[key.get_secret_value().encode(),*(s.encode() for s in generated.values())]
    if archive:
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            manifest=json.loads(z.read('package-manifest.json'))
            for item in z.infolist():
                if item.is_dir():continue
                data=z.read(item)
                assert not any(secret in data for secret in secrets),'CREDENTIAL_VALUE_FOUND'
                assert not any(part in {'.venv','__pycache__','work','llm-cache'} for part in Path(item.filename).parts)
                assert Path(item.filename).name not in {'openai.env','.env','llm-cost.sqlite3'}
                assert not item.filename.endswith(('.pptx','.ppt'))
            for name,digest in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
            result={'archive':archive.name,'sha256':sha(archive),'files':len(z.infolist()),'bytes':archive.stat().st_size,'crc_passed':True,'manifest_files_verified':len(manifest),'credential_values_found':0,'api_calls':0}
        (ROOT.parent/'DATAOPS_V2_1_ARCHIVE_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result));return
    frozen=json.loads((V1/'evaluation/freeze.json').read_text())
    assert all(sha(V1/path)==digest for path,digest in frozen['sha256'].items())
    old_manifest=json.loads((V1/'artifacts/checkpoint4/source-manifest.json').read_text())
    assert all(sha(V1/path)==digest for path,digest in old_manifest.items())
    assert sha(ROOT.parent/'dataops-c-materials.zip')=='1cbb4c5c978ec6546f873125ede5636c5948b9546c9b748e227a92cf5085c504'
    vf=json.loads((V2/'evaluation/v2-freeze.json').read_text())
    assert all(sha(V2/path)==digest for path,digest in vf['sha256'].items())
    snapshot=ROOT/'artifacts/revision-v2/evaluated-source'
    assert all(sha(snapshot/path)==digest for path,digest in vf['sha256'].items())
    suites=ET.parse(RECORDS/'tests.xml').getroot().findall('testsuite')
    passed=sum(int(s.attrib['tests']) for s in suites)
    assert passed==109 and all(int(s.get('failures',0))+int(s.get('errors',0))==0 for s in suites)
    assert json.loads((RECORDS/'offline-contract-check.json').read_text())['passed']==20
    assert json.loads((ROOT/'artifacts/checkpoint4/negative-checks.json').read_text())['passed']==6
    pairs=json.loads((ROOT/'artifacts/revision-v2/paired-content-audit.json').read_text())
    assert all(row['full_evidence_content_equal'] for row in pairs['input_checks'])
    total=json.loads((ROOT/'artifacts/revision-v2/paired-results.json').read_text())
    assert total['new_requests']==10 and total['new_estimated_usd']==0.001482713
    with sqlite3.connect(f'file:{(WORK/"runtime/llm-cost.sqlite3").resolve()}?mode=ro',uri=True) as conn:
        count,nano=conn.execute('SELECT count(*),sum(charge) FROM requests').fetchone()
        uncertain=conn.execute("SELECT count(*) FROM requests WHERE status!='billed'").fetchone()[0]
    assert count==93 and nano==15592371 and uncertain==0
    private=[WORK/'runtime/openai.env',WORK/'runtime/llm-cost.sqlite3',*(WORK/'runtime/llm-cache').glob('*.json')]
    assert all(p.stat().st_mode&0o777==0o600 for p in private)
    assert all(p.stat().st_mode&0o777==0o700 for p in (WORK/'runtime',WORK/'runtime/llm-cache'))
    scanned=0
    for folder,dirs,files in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in {'.venv','__pycache__','.pytest_cache','.git'}]
        for name in files:
            p=Path(folder)/name
            if p.is_symlink():continue
            assert not any(secret in p.read_bytes() for secret in secrets),'CREDENTIAL_VALUE_FOUND'
            scanned+=1
    manifest={str(p.relative_to(ROOT)):sha(p) for folder in ('src','tests','scripts','docs','evaluation','deployment','.streamlit','pipeline') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    for name in ('README.md','pyproject.toml','uv.lock','.env.example','.gitignore'):manifest[name]=sha(ROOT/name)
    (RECORDS/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result={'audited_at':datetime.now(timezone.utc).isoformat(),'v1_source_files_unchanged':len(old_manifest),'v1_freeze_verified':True,'v1_zip_unchanged':True,'v2_evaluated_source_preserved':len(vf['sha256']),'current_version':'0.2.1','tests_passed':passed,'free_contract_cases':20,'negative_classes_passed':6,'new_paid_requests':10,'new_estimated_usd':0.001482713,'ledger_requests':count,'ledger_estimated_usd':nano/1e9,'uncertain_requests':uncertain,'permissions_verified':True,'credential_values_found':0,'scanned_files':scanned,'credential_scan_scope':'explicit supplied API key and this demo generated credentials only','paired_input_content_equal':True,'paired_input_array_order_equal':False,'v2_structural_and_assisted_final_pass':'1/2','v2_baseline_pass':'2/2','v2_1_paid_model_validation':False,'independent_human_review':False,'original_8_of_9_target_met':False,'presentation_created':False,'new_api_calls_from_audit':0}
    (RECORDS/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path);args=p.parse_args();main(args.archive)

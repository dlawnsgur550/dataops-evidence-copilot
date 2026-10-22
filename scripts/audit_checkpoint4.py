"""Artifact integrity/security audit. Explicit known credentials only, no API calls."""
from __future__ import annotations
import argparse,hashlib,io,json,os,re,sqlite3,subprocess,xml.etree.ElementTree as ET,zipfile
from datetime import datetime,timezone
from pathlib import Path

from dataops_copilot.api_safety import CostLedger,read_api_settings
from dataops_copilot.evaluation import verify_freeze

ROOT=Path(__file__).resolve().parents[1]
RECORDS=ROOT/'artifacts/checkpoint4'
RUNTIME=ROOT.parents[1]/'work/runtime'

def main(archive=None):
    key,_=read_api_settings(RUNTIME/'openai.env')
    generated=json.loads((RUNTIME/'generated-credentials.json').read_text())
    secrets=[key.get_secret_value().encode(),*(s.encode() for s in generated.values())]
    leaks=[];scanned=0;zip_entries=0
    def check_bytes(label,data,depth=0):
        nonlocal zip_entries
        if any(secret in data for secret in secrets):leaks.append(label)
        if label.endswith('.zip'):
            if depth>3:raise AssertionError('UNEXPECTED_NESTED_ARCHIVE')
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None,'ARCHIVE_CRC_FAILURE'
                for item in z.infolist():
                    if not item.is_dir():
                        zip_entries+=1
                        check_bytes(label+'!'+item.filename,z.read(item),depth+1)
    for directory,folders,files in os.walk(ROOT.parent):
        folders[:]=[n for n in folders if n not in {'.venv','__pycache__','.pytest_cache','.git'}]
        for name in files:
            path=Path(directory)/name
            if path.is_symlink():continue
            if path==archive:continue
            scanned+=1;check_bytes(str(path.relative_to(ROOT.parent)),path.read_bytes())
    assert not leaks,'CREDENTIAL_VALUE_FOUND_IN_OUTPUTS'
    private=[RUNTIME/'openai.env',RUNTIME/'llm-cost.sqlite3',*(RUNTIME/'llm-cache').glob('*.json')]
    assert all(p.stat().st_mode&0o777==0o600 for p in private)
    assert all(p.stat().st_mode&0o777==0o700 for p in (RUNTIME,RUNTIME/'llm-cache'))
    freeze=verify_freeze(ROOT)
    manifest=json.loads((ROOT/'evaluation/dataset-manifest.json').read_text())
    for relative,digest in manifest['evidence_sha256'].items():assert hashlib.sha256((ROOT/'evaluation'/relative).read_bytes()).hexdigest()==digest
    suites=ET.parse(RECORDS/'tests.xml').getroot().findall('testsuite')
    assert sum(int(s.get('tests',0)) for s in suites)==86
    assert all(int(s.get('failures',0))+int(s.get('errors',0))==0 for s in suites)
    live=json.loads((RECORDS/'live-e2e.json').read_text())
    assert live['success'] and len(live['runs'])==7 and len(live['recoveries'])==3
    for row in live['recoveries']:
        assert row['recovery_check']['recovered'] and row['aggregate']['matched']
        assert row['aggregate']['raw_count']==1000 and row['aggregate']['raw_sum']=='502360.39'
    known_runs={r['run_id'] for r in live['runs']}
    mentioned=set(re.findall('manual__[a-f0-9]{32}',(ROOT.parent/'CHECKPOINT_4.md').read_text()))
    assert mentioned.issubset(known_runs),'CHECKPOINT_RUN_ID_NOT_IN_ORIGINAL_RECORD'
    assert json.loads((RECORDS/'container-boundary.json').read_text())['success'] is True
    negative=json.loads((RECORDS/'negative-checks.json').read_text())
    assert negative['passed']==negative['total']==6
    browser=json.loads((RECORDS/'screens/browser-verification.json').read_text())
    free_live=json.loads((RECORDS/'screens/free-live-ui-verification.json').read_text())
    assert browser['success'] and browser['additional_api_calls']==0 and not browser['page_errors']
    assert free_live['success'] and free_live['additional_api_calls']==0 and free_live['current_probe_connected']
    assert len(list((RECORDS/'screens').glob('*.png')))==6
    metrics=json.loads((RECORDS/'evaluation-metrics.json').read_text())
    assert metrics['comparison_evidence_hash_matches'] and metrics['retrieval']['hit_at_3']==9
    assert metrics['final']['assisted_semantic_fault_correct']==5 and not metrics['target_8_of_9_met']
    assert not metrics['independent_human_review_completed']
    assert len(json.loads((RECORDS/'final-evaluation/results.json').read_text())['cases'])==12
    models=json.loads((ROOT/'deployment/embedding-model.json').read_text())
    for name,info in models['files'].items():assert hashlib.sha256((ROOT.parents[1]/'work/models/e5-small'/name).read_bytes()).hexdigest()==info['sha256']
    containers=[]
    for name in ('dataops-c-cp2-airflow','dataops-c-cp2-postgres'):
        info=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
        containers.append({'name':name,'running':info['State']['Running'],'status':info['State']['Status']})
        assert not info['State']['Running']
    process_text=subprocess.check_output(['ps','-axo','pid,command'],text=True)
    mcp=[line for line in process_text.splitlines() if ' -m dataops_copilot.mcp_server ' in line]
    ui=[line for line in process_text.splitlines() if ('streamlit run '+str(ROOT/'src/dataops_copilot/ui.py')) in line]
    assert not mcp and not ui,'OWNED_SERVICE_LEFT_RUNNING'
    original=Path('/Users/lim/Documents/Codex/2026-10-20/1-dataops-observability-copilot-de-apache/outputs/dataops-docs')
    previous=json.loads((ROOT/'artifacts/checkpoint2/final-audit.json').read_text())['original_readonly_reference_sha256']
    unchanged={name:hashlib.sha256((original/name).read_bytes()).hexdigest()==digest for name,digest in previous.items()}
    assert all(unchanged.values())
    cost=CostLedger(RUNTIME/'llm-cost.sqlite3',purpose='evaluation').summary()
    assert cost['requests']==83 and cost['uncertain_requests']==0 and cost['spent_or_reserved_usd']<=0.02
    zip_result=None
    if archive:
        assert archive.is_file()
        check_bytes(archive.name,archive.read_bytes())
        assert not leaks,'CREDENTIAL_VALUE_FOUND_IN_ARCHIVE'
        with zipfile.ZipFile(archive) as z:
            assert not any(any(part in {'.venv','__pycache__','work','llm-cache'} for part in Path(n).parts) for n in z.namelist())
            assert not any(Path(n).name in {'openai.env','llm-cost.sqlite3'} for n in z.namelist())
            assert not any(n.endswith(('.pptx','.ppt')) for n in z.namelist())
            zip_result={'file':archive.name,'members':len(z.infolist()),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'crc_passed':True,'credential_values_found':0}
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
       for folder in ('src','scripts','tests','docs','deployment','pipeline','.streamlit') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    for name in ('README.md','pyproject.toml','uv.lock','.env.example','.gitignore'):hashes[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    (RECORDS/'source-manifest.json').write_text(json.dumps(hashes,indent=2)+'\n')
    result={'requested_materials_ready':True,'full_pdr_complete':False,'diagnosis_target_met':False,'presentation_created':False,
      'audited_at':datetime.now(timezone.utc).isoformat(),'credential_scan_scope':'only explicitly supplied API key plus credentials generated by this demo; outputs and archive','credential_leaks':leaks,'scanned_files':scanned,'nested_zip_entries_checked':zip_entries,
      'private_file_count':len(private),'permissions_verified':True,'frozen_files_verified':len(freeze['sha256']),'freeze_id':freeze['freeze_id'],'original_documents_unchanged':unchanged,
      'tests_passed':86,'actual_recoveries':3,'retrieval_hit_at_3':'9/9','assisted_semantic_diagnosis':'5/9','independent_human_review':False,
      'no_automatic_api_retry':True,'new_model_calls_from_audit':0,'requests_total':cost['requests'],'estimated_usd_total':cost['spent_or_reserved_usd'],'uncertain_requests':0,
      'containers':containers,'remaining_mcp_servers':0,'remaining_ui_servers':0,'archive':zip_result}
    (RECORDS/'final-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'materials_ready':True,'pdr_complete':False,'credential_leaks':0,'tests_passed':86,'estimated_usd_total':cost['spent_or_reserved_usd'],'services_stopped':True,'archive_verified':bool(zip_result)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path);args=p.parse_args();main(args.archive.resolve() if args.archive else None)

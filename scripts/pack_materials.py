"""Audit and package v3.1 without overwriting any earlier deliverable."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
from dataops_copilot.api_safety import CostLedger,read_api_settings

ROOT=Path(__file__).resolve().parents[1];WORK=ROOT.parents[1]/'work';RUNTIME=WORK/'runtime'
DEST=ROOT.parent/'dataops-c-materials-v3.1.zip'
EXCLUDED={'.venv','__pycache__','.pytest_cache','.git','work','llm-cache'}


def main():
    assert not DEST.exists(),'PRESERVE_EXISTING_ARCHIVE'
    key,_=read_api_settings(RUNTIME/'openai.env')
    credentials=json.loads((RUNTIME/'generated-credentials.json').read_text())
    secrets=[key.get_secret_value().encode()]+[v.encode() for v in credentials.values() if isinstance(v,str) and len(v)>12]
    files=[];findings=[]
    for folder,dirs,names in os.walk(ROOT):
        dirs[:]=[d for d in sorted(dirs) if d not in EXCLUDED]
        for name in sorted(names):
            p=Path(folder)/name
            if p.is_symlink() or name in ('openai.env','.env') or '.sqlite' in name or p.suffix in ('.onnx','.safetensors','.ppt','.pptx'):continue
            if name.startswith('.env.') and name!='.env.example':continue
            raw=p.read_bytes()
            if any(s in raw for s in secrets):findings.append(str(p.relative_to(ROOT)))
            files.append((p,raw))
    assert not findings,{'secret_content_files':findings}
    ledger=CostLedger(RUNTIME/'llm-cost.sqlite3',purpose='evaluation').summary()
    assert ledger['requests']==128 and ledger['uncertain_requests']==0
    assert (RUNTIME/'openai.env').stat().st_mode&0o777==0o600
    assert RUNTIME.stat().st_mode&0o777==0o700
    original=json.loads((WORK/'v3/original-hashes.json').read_text())
    preserved=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in original.items());assert preserved
    # The original v3 frozen source and the two evaluated source copies remain exact.
    evaluated=[]
    for root in (ROOT/'artifacts/v3/evaluated-source',ROOT/'artifacts/v3.1/evaluated-source'):
        # Explicit path avoids accidental version substring matches in the parent folder.
        lockpath=root/('evaluation/v3.1/freeze.json' if root.parent.name=='v3.1' else 'evaluation/v3/freeze.json')
        lock=json.loads(lockpath.read_text())['sha256']
        assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==sha for p,sha in lock.items())
        evaluated.append({'source_copy':str(root.relative_to(ROOT)),'verified_files':len(lock)})
    info=json.loads(subprocess.check_output(['docker','inspect','dataops-c-cp2-airflow'],text=True))[0]
    sources={m['Source'] for m in info['Mounts']}
    assert str(RUNTIME) not in sources and str(ROOT.parents[1]) not in sources
    assert not any(x.split('=',1)[0].startswith('OPENAI_') for x in info['Config']['Env'])
    hidden=subprocess.run(['docker','exec','dataops-c-cp2-airflow','sh','-c','test ! -e "$1"','probe',str(RUNTIME/'openai.env')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    assert hidden
    audit={'success':True,'real_secret_leaks':0,'known_secret_values_checked':len(secrets),'prior_archives_preserved':len(original),
       'evaluated_sources_verified':evaluated,'api_key_file_mode':'0600','runtime_directory_mode':'0700','api_key_not_visible_in_container':hidden,
       'openai_env_not_in_container':True,'whole_workspace_not_mounted':True,'ledger':ledger,'additional_estimated_usd':round(ledger['spent_or_reserved_usd']-0.015592371,9),'presentation_files_in_archive':0}
    p=ROOT/'artifacts/v3.1/security-audit.json';p.write_text(json.dumps(audit,indent=2)+'\n')
    files=[(x,b) for x,b in files if x!=p]+[(p,p.read_bytes())]
    manifest={}
    with zipfile.ZipFile(DEST,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p,raw in files:
            name='dataops-copilot-v3.1/'+str(p.relative_to(ROOT));archive.writestr(name,raw);manifest[name]=hashlib.sha256(raw).hexdigest()
        archive.writestr('package-manifest.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(DEST) as archive:
        assert archive.testzip() is None
        assert all(hashlib.sha256(archive.read(name)).hexdigest()==sha for name,sha in manifest.items())
        assert all(not name.endswith(('.ppt','.pptx','.sqlite3')) for name in archive.namelist())
    sha=hashlib.sha256(DEST.read_bytes()).hexdigest();DEST.with_suffix('.zip.sha256').write_text(sha+'  '+DEST.name+'\n')
    result={'archive':DEST.name,'sha256':sha,'files':len(manifest)+1,'bytes':DEST.stat().st_size,'secret_leaks':0,'api_calls':0}
    (ROOT.parent/'dataops-c-materials-v3.1-manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()

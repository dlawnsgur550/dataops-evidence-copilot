"""개발 확인 뒤 최종 평가 전 입력·코드·프롬프트·문서·모델 버전 고정."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from dataops_copilot.evaluation import frozen_files

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'evaluation/freeze.json'
if path.exists():raise RuntimeError('ALREADY_FROZEN_PRESERVE_EXISTING_EVALUATION')
hashes=frozen_files(ROOT)
path.write_text(json.dumps({'frozen_at':datetime.now(timezone.utc).isoformat(),'freeze_id':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),'sha256':hashes,'no_final_case_prompt_tuning':True,'model':'gpt-6-luna','service_tier':'flex','reasoning':'none','output_caps':{'triage':256,'inspector':160,'rca':1200,'reviewer':512}},indent=2)+'\n')
print(json.dumps({'frozen_files':len(hashes),'freeze_id':json.loads(path.read_text())['freeze_id']}))

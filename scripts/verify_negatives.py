"""Six required deterministic negative classes, with saved actual evidence; no API calls."""
import json
from pathlib import Path
from pydantic import ValidationError
from dataops_copilot.models import Report,Status,TargetRef,ToolError
from dataops_copilot.rules import code_review

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'artifacts/checkpoint4'

def main():
    schema=Report.model_validate_json((ROOT/'artifacts/checkpoint2/schema-report.json').read_text())
    connection=Report.model_validate_json((ROOT/'artifacts/checkpoint2/connection-report.json').read_text())
    checks=[]
    def verify(name,report,diagnosis,evidence,expected):
        violations=code_review(diagnosis,evidence,report.incident_ref,report.retrieval_hits)
        assert any(expected in v for v in violations),(name,violations)
        checks.append({'negative_type':name,'detected':True,'violations':violations})
    verify('fabricated_evidence',schema,schema.diagnosis.model_copy(update={'evidence_ids':schema.diagnosis.evidence_ids+['invented']}),schema.evidence,'FABRICATED_EVIDENCE_ID')
    try:TargetRef.model_validate({})
    except ValidationError:checks.append({'negative_type':'missing_target','detected':True,'violations':['PYDANTIC_EMPTY_TARGET_REJECTED']})
    else:raise AssertionError('Empty target accepted')
    action=schema.diagnosis.recovery_actions[0].model_copy(update={'kind':'retry','steps':['재실행만 수행합니다.']})
    verify('retry_only',schema,schema.diagnosis.model_copy(update={'recovery_actions':[action]}),schema.evidence,'INAPPROPRIATE_RECOVERY_KIND')
    evidence=[e.model_copy(update={'status':Status.UNAVAILABLE,'data':None,'error':ToolError(code='LOG_MISSING',retryable=False,message='not archived')}) if e.kind=='get_task_context' else e for e in schema.evidence]
    verify('missing_logs',schema,schema.diagnosis,evidence,'UNSUPPORTED_CATEGORY')
    action=connection.diagnosis.recovery_actions[0].model_copy(update={'target_ref':TargetRef(connection_id='mcp_readonly')})
    verify('other_connection_success',connection,connection.diagnosis.model_copy(update={'recovery_actions':[action]}),connection.evidence,'ACTION_WRONG_CONNECTION')
    evidence=[e.model_copy(update={'target_ref':TargetRef(incident=e.target_ref.incident.model_copy(update={'run_id':'foreign-run'}))}) if e.kind=='get_dbt_artifacts' else e for e in schema.evidence]
    verify('old_artifact_mixed',schema,schema.diagnosis,evidence,'FOREIGN_EXECUTION')
    (DEST/'negative-checks.json').write_text(json.dumps({'passed':len(checks),'total':6,'api_calls':0,'checks':checks},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':len(checks),'total':6,'api_calls':0}))

if __name__=='__main__':main()

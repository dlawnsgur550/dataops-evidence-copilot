"""Executable R00-R17 checks for the v3 bounded-claim/report contract.

No inference from a model's free-form judgement. Unsupported model objections are
recorded, while code violations remain mandatory. No write tool is available.
"""
import hashlib
import json
import re
from .claim_contract import ClaimProposal, ClaimReview
from .models import Diagnosis, Evidence, RecoveryAction, TargetRef, abstain

RULE_COMPONENT={'R00':'cause','R01':'cause','R02':'cause','R03':'cause','R04':'observations','R05':'observations',
 'R06':'actions','R07':'observations','R08':'cause','R09':'cause','R10':'observations','R11':'observations',
 'R12':'actions','R13':'actions','R14':'actions','R15':'actions','R16':'cause','R17':'cause'}


def content_hash(evidence):
    items=sorted([e.model_dump(mode='json') if isinstance(e,Evidence) else e for e in evidence],key=lambda e:(e['kind'],e['evidence_id']))
    return hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def integrity(e,incident,target):
    errors=[]
    if e.kind in ('get_task_context','get_dbt_artifacts'):
        if e.temporal_scope!='run_snapshot' or e.target_ref.incident is None or e.target_ref.incident.execution_key()!=incident.execution_key():errors.append('R01')
    elif e.temporal_scope!='current_observation':errors.append('R04')
    if e.kind in ('compare_schema','get_quality_profile') and e.target_ref.table_id!=target.table_id:errors.append('R01')
    if e.kind=='compare_schema' and (e.target_ref.baseline_id!=target.baseline_id or (e.status=='success' and e.data.get('baseline_id')!=target.baseline_id)):errors.append('R01')
    if e.kind=='check_connection' and e.target_ref.connection_id!=target.connection_id:errors.append('R01')
    if e.kind=='get_dbt_artifacts' and e.status=='success':
        d=e.data;inv=d.get('invocation_id')
        ok=bool(inv) and inv==d.get('manifest_invocation_id')
        if d.get('artifact_status')=='partial':
            ok=ok and d.get('run_results_invocation_id') is None and d.get('available_artifacts')==['manifest'] and d.get('missing_artifacts')==['run_results'] and d.get('stdout_invocation_ids')==[inv] and d.get('exit_code')==2 and d.get('command')=='run' and bool(re.fullmatch('[0-9a-f]{64}',str(d.get('command_log_sha256',''))))
        else:ok=ok and inv==d.get('run_results_invocation_id')
        if not ok:errors.append('R01')
    return sorted(set(errors))


def facts(evidence,incident,target):
    good=[e for e in evidence if e.status=='success' and not integrity(e,incident,target)]
    valid={e.kind:e for e in good};byid={e.evidence_id:e for e in good}
    c=(valid.get('get_task_context').data if valid.get('get_task_context') else {})
    a=(valid.get('get_dbt_artifacts').data if valid.get('get_dbt_artifacts') else {})
    s=(valid.get('compare_schema').data if valid.get('compare_schema') else {})
    q=(valid.get('get_quality_profile').data if valid.get('get_quality_profile') else {})
    p=(valid.get('check_connection').data if valid.get('check_connection') else {})
    logs='\n'.join(c.get('log_lines',[])).lower();category='UNKNOWN';required=[]
    bound=c and a and c.get('table_id')==target.table_id and a.get('table_id')==target.table_id
    complete=a.get('artifact_status','complete')=='complete'
    if bound:
        column=a.get('column_id');base=['get_task_context','get_dbt_artifacts']
        if a.get('issue')=='connection_refused' and c.get('state')=='failed' and 'connection refused' in logs and c.get('dbt_connection_id')==a.get('connection_id')==target.connection_id:
            category='CONNECTION_FAILURE';required=base
        elif complete and a.get('issue')=='missing_column' and c.get('state')=='failed' and column in target.schema_columns and f'column "{column}" does not exist' in logs and column in s.get('removed',[]):
            category='SCHEMA_CHANGE';required=base+['compare_schema']
        elif complete and a.get('issue')=='not_null' and c.get('state')=='failed' and column==target.quality_column and 'not_null' in logs and a.get('test_results',{}).get('not_null_'+column)=='fail' and q.get('null_counts',{}).get(column,0)>0:
            category='DATA_QUALITY';required=base+['get_quality_profile']
        elif complete and a.get('exit_code',0)==0 and c.get('state')=='success' and set(c.get('task_statuses',{}))==set(target.tasks) and all(v=='success' for v in c['task_statuses'].values()) and a.get('issue') is None and set(target.required_tests).issubset(a.get('test_results',{})) and all(a['test_results'][k]=='pass' for k in target.required_tests) and all(v=='pass' for v in a['test_results'].values()):
            category='NORMAL';required=base
    coverage='unknown'
    if a:
        coverage='run_results_missing' if a.get('artifact_status')=='partial' else 'complete'
    probe='unknown' if 'connected' not in p else 'connected' if p['connected'] is True else 'unavailable'
    return {'category':category,'required_ids':[valid[k].evidence_id for k in required],'byid':byid,'valid':valid,
        'context':c,'artifacts':a,'coverage':coverage,'probe':probe,'config_error':a.get('confirmed_config_error','unknown')}


def assess(proposal,evidence,incident,target):
    f=facts(evidence,incident,target);checks=[]
    def check(rule,claim,ok,reason,component=None):
        checks.append({'rule_id':rule,'claim_id':claim,'component':component or RULE_COMPONENT[rule],
                       'verdict':'PASS' if ok else 'REJECT','reason':reason})
    check('R00','category',isinstance(proposal,ClaimProposal),'구조화된 유한 명제만 수용')
    check('R01','evidence_ids',len({e.evidence_id for e in evidence})==len(evidence),'근거 식별자 중복 금지')
    check('R02','evidence_ids',len(set(proposal.evidence_ids))==len(proposal.evidence_ids) and all(x in f['byid'] for x in proposal.evidence_ids),'성공하고 실행·대상이 일치하는 근거만 인용')
    check('R02','evidence_ids',set(f['required_ids']).issubset(proposal.evidence_ids),'원인별 필수 근거 모두 인용')
    check('R03','category',proposal.category==f['category'],'로그·산출물·현재 보조 관측으로 범주 검증')
    check('R08','category',f['category']!='NORMAL' or proposal.category=='NORMAL','전체 태스크·필수 검사 정상 시 불필요한 보류 금지')
    check('R09','category',proposal.category!='UNKNOWN' or f['category']=='UNKNOWN','근거 부족일 때만 판단 보류')
    check('R04','current_connection',proposal.current_connection=='unknown' or proposal.current_connection==f['probe'],'현재 연결 관측을 과거 장애·복구와 분리')
    check('R02','current_connection',proposal.current_connection=='unknown' or bool(f['valid'].get('check_connection') and f['valid']['check_connection'].evidence_id in proposal.evidence_ids),'현재 연결 주장도 해당 관측 근거 인용',component='observations')
    check('R05','config_error',proposal.config_error=='unknown' or proposal.config_error==f['config_error'],'설정 오류를 근거 없이 확정하지 않음')
    check('R07','artifact_coverage',proposal.artifact_coverage=='unknown' or proposal.artifact_coverage==f['coverage'],'검증된 partial 명령 영수증에서만 파일 누락 확정')
    check('R02','artifact_coverage',proposal.artifact_coverage=='unknown' or bool(f['valid'].get('get_dbt_artifacts') and f['valid']['get_dbt_artifacts'].evidence_id in proposal.evidence_ids),'산출물 범위 주장도 해당 영수증 인용',component='observations')
    check('R12','business_equivalence',proposal.business_equivalence=='unknown' or proposal.business_equivalence==target.business_equivalence,'업무 의미 동일성은 명시적 계약 필요')
    check('R14','propose_action',not proposal.propose_action or proposal.category not in ('NORMAL','UNKNOWN'),'정상·판단 보류에 복구 조치 없음')
    for rule,reason in [('R06','설정 수정은 확인되면 수정, 미확인이면 유지하는 조건부 절차'),('R10','복구 완료 주장은 생성하지 않으며 별도 실행 검사 사용'),('R11','실제 태스크 상태와 manifest 영향 가능성은 별도 렌더링'),('R13','검증 절차는 앞으로 수행할 제안으로 표시'),('R15','원본 보존과 승인된 업무 정책 적용'),('R17','원래 구조화 후보와 판정 모두 보고서에 보존')]:
        check(rule,'propose_action' if RULE_COMPONENT[rule]=='actions' else 'category',True,reason)
    return f,checks


def render(proposal,f,incident,target,hits,checks):
    cause_ok=all(c['verdict']=='PASS' for c in checks if c['component']=='cause')
    if not cause_ok:return abstain('구조화된 원인 주장이 필수 근거 검사를 통과하지 못했습니다.')
    category=proposal.category
    if category=='UNKNOWN':return abstain('선택 실행의 로그·산출물과 필수 보조 관측이 충분하지 않습니다.')
    a=f['artifacts'];c=f['context'];column=a.get('column_id');ids=f['required_ids']
    cause={
      'SCHEMA_CHANGE':f"선택 실행의 {target.table_id} 참조에서 {column} 컬럼 부재가 로그·dbt 산출물에 기록됐습니다. 현재 스키마 차이는 별도 시점의 보조 관측입니다.",
      'DATA_QUALITY':f"선택 실행의 {target.table_id}.{column} not_null 검사가 실패했습니다. 현재 NULL 건수는 별도 시점의 관측입니다.",
      'CONNECTION_FAILURE':f"선택 실행에서 {target.connection_id} 연결 거부가 로그·dbt 산출물에 기록됐습니다. 현재 연결 결과만으로 과거 실패의 부재나 복구를 확정하지 않습니다.",
      'NORMAL':'선택 실행의 전체 필수 태스크와 dbt 필수 품질 검사가 성공했습니다.'}[category]
    missing=['검증된 partial 명령 영수증에서 run_results 미생성이 확인됐습니다. manifest와 명령 로그의 실행 식별자를 확인했습니다.'] if f['coverage']=='run_results_missing' else []
    impact=[]
    failed=[k for k,v in c.get('task_statuses',{}).items() if v in ('failed','upstream_failed')]
    if failed:impact.append('관측된 실패 또는 차단 태스크: '+', '.join(sorted(failed)))
    if category!='NORMAL' and a.get('potential_downstream'):impact.append('manifest 의존관계상 영향 가능성: '+', '.join(a['potential_downstream'])+'; 실제 모델 실패 확정과 구분합니다.')
    actions=[]
    doc={'SCHEMA_CHANGE':'rb-schema','DATA_QUALITY':'rb-quality','CONNECTION_FAILURE':'rb-connection'}.get(category)
    action_ok=all(x['verdict']=='PASS' for x in checks if x['component']=='actions')
    if proposal.propose_action and action_ok and doc in {h.doc_id for h in hits}:
        kind,pre,steps={
          'SCHEMA_CHANGE':('schema_alignment',['원본을 보존하고 생산자 계약과 업무 의미를 확인합니다.'],['두 컬럼의 의미가 승인된 계약에서 동일하면 개발자가 매핑을 검토해 맞춥니다. 의미가 다르거나 미확인이면 자동 치환하지 않고 담당자 확인까지 유지합니다.']),
          'DATA_QUALITY':('data_remediation',['원본을 보존하고 업무 키 정의와 승인된 정정 정책을 확인합니다.'],['원천 오류가 확인되고 정정 정책이 승인되면 개발자가 해당 정책으로 수정하거나 격리합니다. 임의 키 생성이나 원본 삭제는 제안하지 않습니다.']),
          'CONNECTION_FAILURE':('connection_config',['실패한 프로세스의 실제 대상 설정과 서비스 상태를 개발자가 확인합니다.'],['설정 오류가 확인되면 개발자가 확인된 오류만 수정합니다. 오류가 확인되지 않으면 설정을 유지하고 추가 근거를 수집합니다.'])
        }[category]
        actions=[RecoveryAction(action_id='conditional-human-001',target_ref=TargetRef(connection_id=target.connection_id) if category=='CONNECTION_FAILURE' else TargetRef(table_id=target.table_id),kind=kind,prerequisites=pre,steps=steps,
          verification=['향후 사람이 별도 새 실행을 수행해 전체 필수 태스크 성공, '+', '.join(target.required_tests)+' 통과와 집계 정합성을 확인합니다. 이 문장은 현재 복구 완료를 뜻하지 않습니다.'],evidence_ids=ids,runbook_ids=[doc])]
    return Diagnosis(category=category,diagnosis_status='supported',severity='low' if category=='NORMAL' else 'high' if failed else 'unknown',cause=cause,evidence_ids=ids,missing_evidence=missing,impact=impact,recovery_actions=actions)


def resolve_review(review,checks):
    bad={(c['component'],c['rule_id'],c['claim_id']) for c in checks if c['verdict']!='PASS'}
    return [{'finding':f.model_dump(),'status':'verified' if (f.component,f.rule_id,f.claim_id) in bad else 'unsubstantiated',
             'reason':'실행 가능한 규칙과 근거로 반례를 검증합니다. 설명 없는 거절은 원인 판정을 덮어쓰지 않습니다.'} for f in review.findings]
